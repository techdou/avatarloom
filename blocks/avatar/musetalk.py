"""MuseTalk Avatar Block —— RTX 5090 真实口型驱动数字人。

输入：参考肖像图 + TTS 音频流（PCM16/16k）
输出：avatar.speech_frame（说话期间活动帧 + 渲染完成后的真实口型帧）、
      avatar.video.ready（渲染完成的 mp4 元数据）、avatar.idle_frame

实现：长驻 muse_worker 子进程（模型只加载一次），TTS 完成后把整段回复音频
交给 worker 渲染成 MuseTalk 口型视频，再把帧流式 emit 给前端。
不依赖 mmpose / face_detection（bbox 与融合蒙版均由 mediapipe 提供）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import time
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any

import numpy as np
from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    AVATAR_VIDEO_READY,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import (
    Block,
    BlockContext,
    BlockManifest,
    BlockSetupError,
    Capability,
    ResourceRequirements,
)


class MuseTalkAvatarBlock(Block):
    """MuseTalk——参考图 + 音频驱动口型（真实 worker 渲染）。"""

    def __init__(self) -> None:
        super().__init__()
        # 全部运行期状态放实例级——此前 deque/dict/list 挂类属性，
        # 多实例（fallback 重建、单测）共享 _tasks/_bufs 互相串扰
        self._worker_proc: Any = None
        self._worker_stdin: Any = None
        self._worker_lock = asyncio.Lock()
        self._worker_lines: deque[str] = deque()
        self._bufs: dict[str, bytearray] = {}
        self._last_activity: dict[str, float] = {}
        self._frame_indexes: dict[str, int] = {}
        self._tasks: list[asyncio.Task[None]] = []
        # 按 session 的回复渲染 task（AL-P1-006：reset 时按 session 精确取消，
        # 此前只进 _tasks 列表、打断后旧渲染继续跑并与新 run 交错下发）
        self._render_tasks: dict[str, asyncio.Task[None]] = {}
        self._portrait_bytes: bytes = b""
        self._portrait_jpeg: bytes = b""
        self._portrait_path: str = ""
        self._fps: int = 25
        self._activity_fps: float = 2.5
        self._render_timeout_s: float = 600.0
        # worker 请求 id 计数器——每个 render 请求带唯一 id，
        # 响应按 id 匹配，避免取消后残留响应被下一轮误收（off-by-one 毒化）
        self._req_counter: int = 0

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="avatar.musetalk",
            name="MuseTalk Avatar",
            category="avatar",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=True),
            inputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            outputs=[AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME, AVATAR_VIDEO_READY],
            resources=ResourceRequirements(
                accelerator=["cuda"],
                estimated_vram_mb=7000,
                pip_extras=["musetalk"],
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "device": {"type": "string", "default": "cuda"},
                    "portrait": {"type": "string"},
                    "fps": {"type": "integer", "default": 25},
                    "workerPython": {"type": "string"},
                    "workerScript": {"type": "string"},
                    "musetalkRoot": {"type": "string"},
                    "modelDir": {"type": "string"},
                    "version": {"type": "string", "default": "v1", "enum": ["v1", "v15"]},
                    "batchSize": {"type": "integer", "default": 8},
                    "crf": {"type": "integer", "default": 18},
                    "extraMargin": {"type": "integer", "default": 0},
                    "activityFps": {"type": "number", "default": 2.5},
                },
            },
            install_extras=["musetalk"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._fps = int(cfg.get("fps", 25))
        self._activity_fps = float(cfg.get("activityFps", 2.5))
        self._render_timeout_s = float(cfg.get("renderTimeoutS", 300))
        workspace = Path(ctx.workspace_root).resolve()  # noqa: ASYNC240 -- setup 一次性路径解析（非热路径）

        portrait_cfg = str(cfg.get("portrait", ""))
        p = Path(portrait_cfg)
        if not p.is_absolute():
            p = workspace / p
        if not p.exists():
            raise BlockSetupError(
                "avatar.musetalk", f"portrait not found: {p}. 已回退 static"
            )
        self._portrait_path = str(p)
        self._portrait_bytes = p.read_bytes()
        self._portrait_jpeg = self._to_jpeg(self._portrait_bytes)

        musetalk_root = str(cfg.get("musetalkRoot", "/root/autodl-tmp/musetalk"))
        model_dir = str(
            cfg.get("modelDir", str(Path(musetalk_root) / "models"))
        )
        version = str(cfg.get("version", "v1"))
        worker_python = str(
            cfg.get(
                "workerPython",
                "/root/autodl-tmp/musetalk-venv/bin/python",
            )
        )
        worker_script = str(
            cfg.get("workerScript", str(workspace / "scripts" / "muse_worker.py"))
        )
        if not Path(worker_script).is_absolute():
            worker_script = str(workspace / worker_script)
        if not Path(worker_script).exists():  # noqa: ASYNC240 -- spawn 前一次性预检，缺失即报错
            raise BlockSetupError(
                "avatar.musetalk", f"worker script not found: {worker_script}"
            )

        self._worker_lock = asyncio.Lock()
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                # 诊断探针：worker 在会话里 rc=-11 且解释器零输出（独立复现全部正常），
                # 先验证同一 fork+exec 上下文中最小 python 能否正常启动
                probe = await asyncio.create_subprocess_exec(
                    worker_python,
                    "-c",
                    "print('PROBE_OK')",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=None,
                )
                probe_out, _ = await probe.communicate()
                if probe.returncode != 0:
                    raise BlockSetupError(
                        "avatar.musetalk",
                        f"fork/exec 探针失败 rc={probe.returncode} out={probe_out!r}",
                    )
                self._worker_proc = await asyncio.create_subprocess_exec(
                    worker_python,
                    # faulthandler：worker 段错误（SIGSEGV）时打印 C/Python 栈到 stderr，
                    # 否则崩溃无输出，排障只能靠猜
                    "-X",
                    "faulthandler",
                    worker_script,
                    "--model-dir",
                    model_dir,
                    "--version",
                    version,
                    "--device",
                    str(cfg.get("device", "cuda")),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=musetalk_root,
                    env=None,
                )
                self._worker_stdin = self._worker_proc.stdin
                reader = asyncio.create_task(self._drain_worker())
                self._tasks.append(reader)
                await asyncio.wait_for(self._wait_line(30.0), timeout=120.0)
                await self._call_worker({"cmd": "ping"}, timeout=30.0)
                # 后台预热：会话建立即加载 MuseTalk 模型，首次渲染免去模型加载等待
                warm = asyncio.create_task(self._warm_worker(ctx))
                self._tasks.append(warm)
                break  # 启动成功
            except Exception as e:
                last_error = e
                leftover = " | ".join(list(self._worker_lines)[-10:])
                await self._stop_worker()
                self._worker_lines.clear()
                if attempt < 2:
                    # worker 启动在真实会话上下文里偶发段错误（独立复现 100% 成功），
                    # 重试几乎必成——不让偶发崩溃直接把 avatar 降级成 static
                    await ctx.logger.awarning(
                        "avatar.musetalk worker 启动失败，重试",
                        attempt=attempt + 1,
                        error=str(e),
                        worker_output=leftover,
                    )
                    await asyncio.sleep(1.0)
                    continue
                raise BlockSetupError(
                    "avatar.musetalk",
                    f"worker 启动失败（重试 3 次）: {last_error} | worker_output={leftover!r}",
                ) from last_error

        self._mark_ready()
        await ctx.logger.ainfo(
            "avatar.musetalk ready",
            device=cfg.get("device", "cuda"),
            portrait=self._portrait_path,
            version=version,
        )

    async def _warm_worker(self, ctx: BlockContext) -> None:
        try:
            async with self._worker_lock:
                resp = await self._call_worker({"cmd": "warm"}, timeout=300)
            await ctx.logger.ainfo(
                "avatar.musetalk warm",
                load_s=resp.get("load_s"),
                warm_s=resp.get("warm_s"),
            )
        except Exception as e:
            await ctx.logger.awarning("avatar.musetalk warm failed", error=str(e))

    async def process(self, ctx: BlockContext, event: Event) -> None:
        sid = ctx.session_id
        if event.type == TTS_AUDIO_DELTA:
            pcm_b64 = event.payload.get("pcm_b64", "")
            # 垫音（filler）：不混入 reply 渲染缓冲——否则 TTS_AUDIO_COMPLETED
            # 触发 _render_reply 时会把 filler+真回复的混合音频拿去渲染（错乱）。
            # 但活动帧照产（张嘴沉吟，VoxEMW 同款效果）。
            if pcm_b64 and not event.payload.get("filler"):
                with suppress(Exception):
                    self._bufs.setdefault(sid, bytearray()).extend(
                        base64.b64decode(pcm_b64)
                    )
            await self._emit_activity(ctx, sid)
        elif event.type == TTS_AUDIO_COMPLETED:
            # 同 session 旧渲染还在跑先取消（连说两轮的场景）——以新回复为准
            old = self._render_tasks.pop(sid, None)
            if old is not None and not old.done():
                old.cancel()
            task = asyncio.create_task(self._render_reply(ctx))
            self._render_tasks[sid] = task
            self._tasks.append(task)

    async def reset(self, session_id: str) -> None:
        # 打断：取消本 session 进行中的回复渲染（AL-P1-006）。
        # 注意：worker 进程侧的当次渲染无法中止（协议无 abort cmd），
        # 取消只释放 Python 侧——渲染结果随 task 消亡被丢弃，不会交错下发。
        task = self._render_tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
        self._bufs.pop(session_id, None)
        self._last_activity.pop(session_id, None)
        self._frame_indexes[session_id] = 0

    async def shutdown(self) -> None:
        await self._stop_worker()
        for t in self._tasks:
            if not t.done():
                t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                # 这些 task 是我们自己 cancel 的——自取消吞掉；
                # 仅当前任务自身被外部取消时透传（防 asyncio.run 挂起）
                current = asyncio.current_task()
                if current is not None and current.cancelling() > 0:
                    raise
            except Exception:
                pass
        self._tasks.clear()
        # 会话态一并清理——GPU worker 已停，残留缓冲/索引无意义
        self._render_tasks.clear()
        self._bufs.clear()
        self._last_activity.clear()
        self._frame_indexes.clear()
        self._worker_lines.clear()

    # ------------------------------------------------------------------
    # worker 通信
    # ------------------------------------------------------------------

    async def _drain_worker(self) -> None:
        assert self._worker_proc and self._worker_proc.stdout
        try:
            while True:
                line = await self._worker_proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self._worker_lines.append(text)
        except Exception:
            logging.getLogger(__name__).exception("MuseTalk worker stdout drain failed")

    async def _wait_line(
        self, timeout: float, expected: str | None = None, req_id: int | None = None
    ) -> dict:
        """等待 worker 响应行。

        匹配优先级：req_id（精确匹配某次请求）> expected（按 cmd 名）> None（任意行）。
        req_id 匹配解决了取消后残留响应被下一轮误收的 off-by-one 毒化问题。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._worker_lines:
                raw = self._worker_lines.popleft()
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if req_id is not None:
                    # 精确匹配——id 不符的旧响应直接丢弃（这正是修复的核心）
                    if obj.get("id") == req_id:
                        return obj
                    continue
                if expected is None or obj.get("cmd") == expected:
                    return obj
                # 非目标行（如中间状态）——丢弃，继续等目标响应
                continue
            if self._worker_proc and self._worker_proc.returncode is not None:
                raise RuntimeError(f"worker exited rc={self._worker_proc.returncode}")
            await asyncio.sleep(0.05)
        raise TimeoutError("worker no response")

    async def _call_worker(self, req: dict, timeout: float) -> dict:
        if not self._worker_stdin or not self._worker_proc:
            raise RuntimeError("worker not running")
        # 每个请求分配唯一 id——worker 回响应时原样带回，_wait_line 按 id 精确匹配。
        # 这解决了"取消渲染后 worker 仍输出旧响应，下一轮 _call_worker 把旧响应当
        # 新结果接收"的 off-by-one 毒化问题。
        self._req_counter += 1
        req_id = self._req_counter
        req["id"] = req_id
        self._worker_stdin.write(
            (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
        )
        await self._worker_stdin.drain()
        resp = await self._wait_line(timeout, req_id=req_id)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "worker error"))
        return resp

    async def _stop_worker(self) -> None:
        if self._worker_proc and self._worker_proc.returncode is None:
            try:
                self._worker_proc.terminate()
                await asyncio.wait_for(self._worker_proc.wait(), timeout=5)
            except Exception:
                with suppress(Exception):
                    self._worker_proc.kill()
        self._worker_proc = None
        self._worker_stdin = None

    # ------------------------------------------------------------------
    # 渲染流程
    # ------------------------------------------------------------------

    async def _emit_activity(self, ctx: BlockContext, sid: str) -> None:
        now = time.monotonic()
        if now - self._last_activity.get(sid, 0.0) < 1.0 / max(
            0.1, self._activity_fps
        ):
            return
        self._last_activity[sid] = now
        if self._portrait_jpeg:
            await self._emit_frame(
                ctx, self._portrait_jpeg, is_speech=True, width=1280, height=720
            )

    async def _render_reply(self, ctx: BlockContext) -> None:
        sid = ctx.session_id
        mp4_path = None
        try:
            pcm = bytes(self._bufs.pop(sid, bytearray()))
            if not pcm:
                await self._emit_idle(ctx)
                return
            out_dir = (
                Path(ctx.workspace_root).resolve()  # noqa: ASYNC240 -- 每回复一次的输出目录解析（非热路径）
                / "runs"
                / "avatar"
                / sid
                / time.strftime("%Y%m%d-%H%M%S")
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            wav_path = out_dir / "reply.wav"
            wav_path.write_bytes(_wav_bytes_16k(pcm))
            mp4_path = out_dir / "reply.mp4"

            cfg = ctx.config
            req = {
                "cmd": "render",
                "portrait": self._portrait_path,
                "audio": str(wav_path),
                "out": str(mp4_path),
                "fps": self._fps,
                "batch_size": int(cfg.get("batchSize", 8)),
                "crf": int(cfg.get("crf", 18)),
                "extra_margin": int(cfg.get("extraMargin", 0)),
                "max_side": int(cfg.get("maxSide", 1280)),
                "parsing_mode": str(cfg.get("parsingMode", "auto")),
                "keep_frames": True,
            }
            async with self._worker_lock:
                monitor = asyncio.create_task(self._render_monitor(ctx))
                try:
                    resp = await self._call_worker(req, timeout=self._render_timeout_s)
                finally:
                    monitor.cancel()
        except asyncio.CancelledError:
            # 打断（reset 取消了本 task）——静默退出，不 emit 任何帧/视频事件
            return
        except Exception as e:
            tail = " | ".join(list(self._worker_lines)[-5:])
            await ctx.logger.aerror(
                "avatar.musetalk render failed",
                error=str(e),
                worker_tail=tail,
            )
            # 落盘兜底：worker 已把结果写入 <mp4>.json
            fallback = (
                mp4_path.parent / (mp4_path.stem + ".json") if mp4_path else None
            )
            if fallback and fallback.exists():
                try:
                    resp = json.loads(fallback.read_text(encoding="utf-8"))
                    await self._emit_video_ready(ctx, sid, resp)
                    await ctx.logger.ainfo(
                        "avatar.musetalk video ready (file fallback)",
                        mp4=resp.get("mp4", ""),
                    )
                except Exception as e2:
                    await ctx.logger.aerror("avatar fallback failed", error=str(e2))
            await self._emit_idle(ctx)
            return

        await self._emit_video_ready(ctx, sid, resp)
        await ctx.logger.ainfo(
            "avatar.musetalk video ready",
            mp4=resp.get("mp4", ""),
            frames=resp.get("frames", 0),
        )

        frames_dir = Path(resp.get("frames_dir", ""))
        if frames_dir.is_dir():  # noqa: ASYNC240 -- 渲染收尾一次性目录检查（每回复一次）
            for frame_file in sorted(frames_dir.glob("*.jpg")):  # noqa: ASYNC240 -- 同上：收尾一次性枚举，async 化收益不抵复杂度
                jpeg = frame_file.read_bytes()
                if jpeg:
                    await self._emit_frame(
                        ctx, jpeg, is_speech=True, width=1280, height=720
                    )
                await asyncio.sleep(0)
        await self._emit_idle(ctx)

    async def _render_monitor(self, ctx: BlockContext) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                rc = (
                    self._worker_proc.returncode
                    if self._worker_proc is not None
                    else "?"
                )
                await ctx.logger.ainfo(
                    "musetalk render wait",
                    lines=len(self._worker_lines),
                    proc_rc=rc,
                )
        except asyncio.CancelledError:
            pass

    async def _emit_video_ready(
        self, ctx: BlockContext, sid: str, resp: dict[str, Any]
    ) -> None:
        await ctx.emit(
            Event(
                type=AVATAR_VIDEO_READY,
                session_id=sid,
                source="avatar.musetalk",
                run_id=ctx.run_id,
                payload={
                    "video_path": resp.get("mp4", ""),
                    "frames": resp.get("frames", 0),
                    "audio_s": resp.get("audio_s", 0),
                    "infer_s": resp.get("infer_s", 0),
                    "fps_actual": resp.get("fps_actual", 0),
                    "fps": self._fps,
                },
            )
        )

    async def _emit_idle(self, ctx: BlockContext) -> None:
        await self._emit_frame(
            ctx, self._portrait_jpeg or b"", is_speech=False, width=1280, height=720
        )

    async def _emit_frame(
        self,
        ctx: BlockContext,
        jpeg: bytes,
        *,
        is_speech: bool,
        width: int,
        height: int,
    ) -> None:
        sid = ctx.session_id
        idx = self._frame_indexes.get(sid, 0)
        self._frame_indexes[sid] = idx + 1
        await ctx.emit(
            Event(
                type=AVATAR_SPEECH_FRAME if is_speech else AVATAR_IDLE_FRAME,
                session_id=sid,
                source="avatar.musetalk",
                run_id=ctx.run_id,
                payload={
                    "frame_b64": base64.b64encode(jpeg).decode("ascii"),
                    "width": width,
                    "height": height,
                    "format": "jpeg",
                    "frame_index": idx,
                    "is_speech": is_speech,
                },
            )
        )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _to_jpeg(data: bytes) -> bytes:
        try:
            import cv2

            arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if arr is not None:
                ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 88])
                if ok:
                    return buf.tobytes()
        except Exception:
            pass
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(data))
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            return buf.getvalue()
        except Exception:
            return data


def _wav_bytes_16k(pcm16: bytes, sr: int = 16000) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm16))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm16))
        + pcm16
    )
