"""AVTR-1 Avatar Block —— 流式说话头（TensorRT，对标 VoxEMW 的实时架构）。

与 avatar.musetalk 的本质区别：不是整段离线渲染，而是 TTS 音频边到边喂引擎，
每 0.2s 音频块即时产 5 帧@25fps——说话期间帧与音频天然逐块对齐。

实现：长驻 avtr1_worker 子进程（pixi renderer env，模型/TRT 引擎只加载一次），
stdin JSON 行命令 + stdout 二进制包（控制 JSON / JPEG 帧）。流式语义
（运动上下文永续/句尾淡出/欠载停帧/打断只清音频）全在 worker 侧，见
scripts/avtr1_worker.py 模块 docstring。

listen 轨（用户麦克风 active listening）v1 不接：我方事件模型暂无用户音频到
avatar 块的通道，后续如需可加 uplink 事件转发。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
from contextlib import suppress
from pathlib import Path
from typing import Any

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
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
    HealthStatus,
    ResourceRequirements,
)

PKT_CONTROL = 0x01
PKT_FRAME = 0x02
FRAME_TAG_SPEECH = 0x01
# 帧发射队列上限（~2.5s @25fps）：慢客户端时丢旧帧保新帧，
# 防止 reader 内联 emit 的背压级联拖死 worker 控制通道
FRAME_QUEUE_MAX = 64


class Avtr1AvatarBlock(Block):
    """AVTR-1——参考图 + 音频流实时口型（流式 worker）。"""

    def __init__(self) -> None:
        super().__init__()
        self._worker_proc: Any = None
        self._worker_stdin: Any = None
        self._write_lock = asyncio.Lock()   # stdin 写入串行（多协程喂音频）
        self._pending: dict[int, dict] = {}  # id → 控制应答（reader 填入）
        self._pending_events: dict[int, asyncio.Event] = {}
        self._req_counter = 0
        self._tasks: list[asyncio.Task[None]] = []
        # 帧发射解耦：reader 只入队，独立 emitter 消费——慢客户端背压
        # 不会级联卡死 worker stdout 管道（队满丢最旧）
        self._frame_queue: asyncio.Queue[tuple[bytes, bool]] = asyncio.Queue(
            maxsize=FRAME_QUEUE_MAX
        )
        # 每 session 运行态
        self._ctxs: dict[str, BlockContext] = {}
        self._speaking: dict[str, bool] = {}
        self._frame_indexes: dict[str, int] = {}
        self._ready = False

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="avatar.avtr1",
            name="AVTR-1 Streaming Avatar",
            category="avatar",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=True),
            inputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            outputs=[AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME],
            resources=ResourceRequirements(
                accelerator=["cuda"],
                estimated_vram_mb=8000,
                pip_extras=[],
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "device": {"type": "string", "default": "cuda"},
                    "portrait": {"type": "string"},
                    "workerPython": {"type": "string"},
                    "workerScript": {"type": "string"},
                    "storage": {"type": "string"},
                    "bg": {"type": "string", "default": "plain_white"},
                    "cfgSelfAudio": {"type": "number", "default": 2.0},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        workspace = Path(ctx.workspace_root).resolve()  # noqa: ASYNC240 -- setup 一次性路径解析

        portrait_cfg = str(cfg.get("portrait", ""))
        p = Path(portrait_cfg)
        if not p.is_absolute():
            p = workspace / p
        if not p.exists():
            raise BlockSetupError("avatar.avtr1", f"portrait not found: {p}. 已回退 static")
        portrait = str(p)

        worker_python = str(
            cfg.get("workerPython")
            or "/root/autodl-tmp/avtr-1/.pixi/envs/renderer/bin/python"
        )
        worker_script = str(cfg.get("workerScript", str(workspace / "scripts" / "avtr1_worker.py")))
        if not Path(worker_script).is_absolute():
            worker_script = str(workspace / worker_script)
        if not Path(worker_script).exists():  # noqa: ASYNC240 -- spawn 前预检
            raise BlockSetupError("avatar.avtr1", f"worker script not found: {worker_script}")
        storage = str(cfg.get("storage") or "/root/autodl-tmp/avtr1_storage")
        bg = str(cfg.get("bg", "plain_white"))
        cfg_self_audio = float(cfg.get("cfgSelfAudio", 2.0))

        try:
            self._worker_proc = await asyncio.create_subprocess_exec(
                worker_python,
                "-X", "faulthandler",
                worker_script,
                "--storage", storage,
                "--image", portrait,
                "--bg", bg,
                "--cfg-self-audio", str(cfg_self_audio),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,  # 引擎日志走 /tmp/avtr1_worker_boot.log
            )
            self._worker_stdin = self._worker_proc.stdin
            reader = asyncio.create_task(self._read_packets())
            self._tasks.append(reader)
            self._tasks.append(asyncio.create_task(self._frame_emitter()))
            # ready 要等模型+TRT 引擎加载+静音预热完成，首次可能数分钟；
            # worker 中途死亡时 reader 会 fail pending，这里立即失败而非等满超时
            await self._call_worker({"cmd": "ping"}, timeout=600.0)
        except Exception as e:
            await self._stop_worker()
            raise BlockSetupError("avatar.avtr1", f"worker 启动失败: {e}") from e

        self._ready = True
        self._mark_ready()
        await ctx.logger.ainfo("avatar.avtr1 ready", portrait=portrait, storage=storage)

    # ------------------------------------------------------------------
    # 包读取：控制应答按 id 配对；帧直接 emit
    # ------------------------------------------------------------------

    async def _read_packets(self) -> None:
        assert self._worker_proc and self._worker_proc.stdout
        stream = self._worker_proc.stdout
        try:
            while True:
                header = await stream.readexactly(5)
                pkt_type = header[0]
                (length,) = struct.unpack(">I", header[1:])
                payload = await stream.readexactly(length)
                if pkt_type == PKT_CONTROL:
                    try:
                        obj = json.loads(payload.decode("utf-8"))
                    except Exception:
                        continue
                    rid = obj.get("id")
                    # 配对键是 _pending_events（_call_worker 登记等待的字典）——
                    # 此前误查 _pending（应答落地字典），挂起期间恒空 → 所有应答
                    # 被丢弃、ping 必等满超时（avtr1 真实 setup 从未配对成功过）
                    if rid is not None and rid in self._pending_events:
                        self._pending[rid] = obj
                        ev = self._pending_events.get(rid)
                        if ev is not None:
                            ev.set()
                elif pkt_type == PKT_FRAME and length >= 1:
                    tag = payload[0]
                    jpeg = payload[1:]
                    if self._frame_queue.full():
                        # 丢最旧保最新（帧流语义：旧帧过期即无价值）
                        with suppress(asyncio.QueueEmpty):
                            self._frame_queue.get_nowait()
                    self._frame_queue.put_nowait((jpeg, tag == FRAME_TAG_SPEECH))
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception:
            logging.getLogger(__name__).exception("avtr1 worker packet reader failed")
        finally:
            # worker 死亡（stdout EOF / 异常）：立即 fail 所有 pending 等待方，
            # 否则 setup ping 只能干等满超时、运行期调用方永久挂起
            self._on_worker_gone()

    def _on_worker_gone(self) -> None:
        self._ready = False
        self._worker_stdin = None  # _send 的 None 守卫拦截后续命令
        if self._pending_events:
            logging.getLogger(__name__).error(
                "avtr1 worker exited unexpectedly; failing %d pending call(s)",
                len(self._pending_events),
            )
        for rid, ev in self._pending_events.items():
            self._pending[rid] = {"ok": False, "error": "avtr1 worker exited"}
            ev.set()

    async def _frame_emitter(self) -> None:
        while True:
            jpeg, is_speech = await self._frame_queue.get()
            await self._emit_frame(jpeg, is_speech=is_speech)

    async def _emit_frame(self, jpeg: bytes, *, is_speech: bool) -> None:
        # 帧发给所有活跃 session 的最近 ctx（单会话产品，正常只有一个）
        for sid, ctx in self._ctxs.items():
            idx = self._frame_indexes.get(sid, 0)
            self._frame_indexes[sid] = idx + 1
            with suppress(Exception):  # 帧丢失不致命——下一帧马上到
                await ctx.emit(
                    Event(
                        type=AVATAR_SPEECH_FRAME if is_speech else AVATAR_IDLE_FRAME,
                        session_id=sid,
                        source="avatar.avtr1",
                        run_id=ctx.run_id,
                        payload={
                            "frame_b64": base64.b64encode(jpeg).decode("ascii"),
                            "width": 1280,
                            "height": 720,
                            "format": "jpeg",
                            "frame_index": idx,
                            "is_speech": is_speech,
                        },
                    )
                )

    # ------------------------------------------------------------------
    # worker 命令
    # ------------------------------------------------------------------

    async def _send(self, req: dict) -> None:
        """fire-and-forget 命令（audio/speech_active/reset——不带 id 无应答）。"""
        if not self._worker_stdin:
            return
        async with self._write_lock:
            self._worker_stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
            await self._worker_stdin.drain()

    async def _call_worker(self, req: dict, timeout: float) -> dict:
        if not self._worker_stdin or not self._worker_proc:
            raise RuntimeError("worker not running")
        self._req_counter += 1
        rid = self._req_counter
        req["id"] = rid
        ev = asyncio.Event()
        self._pending_events[rid] = ev
        try:
            await self._send(req)
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            resp = self._pending.get(rid, {})
            if not resp.get("ok"):
                raise RuntimeError(resp.get("error", "worker error"))
            return resp
        finally:
            self._pending.pop(rid, None)
            self._pending_events.pop(rid, None)

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
    # 事件处理
    # ------------------------------------------------------------------

    async def process(self, ctx: BlockContext, event: Event) -> None:
        sid = ctx.session_id
        self._ctxs[sid] = ctx  # 帧通路用最近 ctx
        if event.type == TTS_AUDIO_DELTA:
            if not self._speaking.get(sid):
                # 回复开始：开 speech_active（禁 idle 生成，防句间插 idle 帧卡画面）
                self._speaking[sid] = True
                await self._send({"cmd": "speech_active", "on": True})
            pcm_b64 = event.payload.get("pcm_b64", "")
            # 垫音不喂引擎（与 musetalk 一致；且 fillerEnabled 已默认关）
            if pcm_b64 and not event.payload.get("filler"):
                await self._send({"cmd": "audio", "pcm": pcm_b64})
        elif event.type == TTS_AUDIO_COMPLETED:
            if self._speaking.get(sid):
                self._speaking[sid] = False
                # 段结束：worker 侧对尾巴淡出+右补零排空，嘴型自然闭合
                await self._send({"cmd": "speech_active", "on": False})

    async def reset(self, session_id: str) -> None:
        # 打断：清音频缓冲（运动上下文 worker 侧保留，姿态自然衰减归位）
        self._speaking[session_id] = False
        self._frame_indexes[session_id] = 0
        await self._send({"cmd": "reset"})

    async def on_session_end(self, session_id: str) -> None:
        # 会话结束：移除运行态——常驻 worker 的 idle 帧发射不再发往死会话
        self._ctxs.pop(session_id, None)
        self._speaking.pop(session_id, None)
        self._frame_indexes.pop(session_id, None)

    async def health(self) -> HealthStatus:
        alive = self._worker_proc is not None and self._worker_proc.returncode is None
        return HealthStatus(
            block_id="avatar.avtr1",
            status="healthy" if (self._ready and alive) else "degraded",
        )

    async def shutdown(self) -> None:
        for t in self._tasks:
            if not t.done():
                t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling() > 0:
                    raise
            except Exception:
                pass
        self._tasks.clear()
        await self._stop_worker()
        self._ctxs.clear()
        self._speaking.clear()
        self._frame_indexes.clear()
