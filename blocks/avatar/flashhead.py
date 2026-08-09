"""FlashHead Avatar Block——SoulX-FlashHead 流式说话头（真实实现）。

独立 py310 venv 常驻服务（scripts/flashhead_service.py，ws://127.0.0.1:8767）：
  入：TTS 音频 delta（int16 PCM）→ {"type":"audio","pcm":base64}
      TTS 完成/打断 → {"type":"reset"}
  出：JPEG 帧流（512x512，25fps）→ AVATAR_SPEECH_FRAME

与 MuseTalk 的区别：FlashHead 是端到端说话头，头部/眼睛随音频自然运动，
嘴部由模型直接生成，不是静态肖像贴嘴。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    SPEECH_DETECTED,
    SPEECH_ENDED,
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

from runtime.orchestrator.avatar_state import AvatarState, transition_avatar_state

logger = logging.getLogger("avatar.flashhead")


class FlashHeadAvatarBlock(Block):
    """FlashHead——TTS 音频流驱动的实时说话头。"""

    def __init__(self) -> None:
        super().__init__()
        # 全部运行期状态放实例级——类属性会让多实例（fallback 重建/单测）互相串扰，
        # 与 musetalk 的实例级修复保持一致。
        self._proc: Any = None
        self._ws: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._frame_index: int = 0
        self._avatar_state: Any = None  # AvatarState 实例（transition_avatar_state 推导）
        self._portrait_bytes: bytes = b""
        self._portrait_path: str = ""
        self._fps: int = 25
        self._shutdown: bool = False  # shutdown() 置位——reader 退出后不再 emit
        self._current_ctx: BlockContext | None = None

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="avatar.flashhead",
            name="FlashHead Avatar (SoulX)",
            category="avatar",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=True),
            inputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED, SPEECH_DETECTED, SPEECH_ENDED],
            outputs=[AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME],
            resources=ResourceRequirements(
                accelerator=["cuda"],
                estimated_vram_mb=8000,
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "portrait": {"type": "string"},
                    "fps": {"type": "integer", "default": 25},
                    "servicePython": {"type": "string"},
                    "serviceScript": {"type": "string"},
                    "servicePort": {"type": "integer", "default": 8767},
                    "modelDir": {"type": "string"},
                    "wav2vecDir": {"type": "string"},
                    "jpegQuality": {"type": "integer", "default": 85},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        workspace = Path(ctx.workspace_root).resolve()  # noqa: ASYNC240 -- setup 一次性路径解析（非热路径），引入 anyio.Path 反增依赖
        self._fps = int(cfg.get("fps", 25))

        portrait_cfg = str(cfg.get("portrait", "")).strip()
        if not portrait_cfg:
            raise BlockSetupError(
                "avatar.flashhead",
                "portrait 配置缺失（FlashHead 需要一张正脸参考图）",
            )
        p = Path(portrait_cfg)
        if not p.is_absolute():
            p = workspace / p
        if not p.exists():
            raise BlockSetupError("avatar.flashhead", f"portrait not found: {p}")
        self._portrait_path = str(p)
        self._portrait_bytes = p.read_bytes()

        # 默认路径可用环境变量覆盖（AVATARLOOM_FLASHHEAD_*），降低非 AutoDL 环境启动成本
        service_python = str(
            cfg.get("servicePython")
            or os.environ.get("AVATARLOOM_FLASHHEAD_SERVICE_PYTHON")
            or "/root/autodl-tmp/avatarloom-avatar-venv/bin/python"
        )
        service_script = str(
            cfg.get("serviceScript", str(workspace / "scripts" / "flashhead_service.py"))
        )
        if not Path(service_script).is_absolute():
            service_script = str(workspace / service_script)
        if not Path(service_script).exists():  # noqa: ASYNC240 -- spawn 前一次性预检，缺失即报错
            raise BlockSetupError(
                "avatar.flashhead", f"service script not found: {service_script}"
            )

        model_dir = str(
            cfg.get("modelDir")
            or os.environ.get("AVATARLOOM_FLASHHEAD_MODEL_DIR")
            or "/root/autodl-tmp/models/SoulX-FlashHead-1_3B"
        )
        wav2vec_dir = str(
            cfg.get("wav2vecDir")
            or os.environ.get("AVATARLOOM_FLASHHEAD_WAV2VEC_DIR")
            or "/root/autodl-tmp/models/wav2vec2-base-960h"
        )
        port = int(cfg.get("servicePort", 8767))
        jpeg_quality = int(cfg.get("jpegQuality", 85))

        # 路径预检：缺失时明确报错（而不是 spawn 失败难定位）
        if not Path(service_python).exists():  # noqa: ASYNC240 -- spawn 前一次性预检，缺失即报错
            raise BlockSetupError(
                "avatar.flashhead", f"service python not found: {service_python}"
            )
        if not Path(model_dir).is_dir():  # noqa: ASYNC240 -- spawn 前一次性预检，缺失即报错
            raise BlockSetupError(
                "avatar.flashhead", f"FlashHead 模型目录不存在: {model_dir}"
            )
        if not Path(wav2vec_dir).is_dir():  # noqa: ASYNC240 -- spawn 前一次性预检，缺失即报错
            raise BlockSetupError(
                "avatar.flashhead", f"wav2vec 目录不存在: {wav2vec_dir}"
            )

        log_path = "/tmp/flashhead_service.log"
        # 子进程 stdout 重定向 fd：需在 spawn 失败后仍可读日志，生命周期跨 setup 多个
        # 提前返回分支，with 包裹会迫使整个 setup 缩进重排——各分支显式 close 已覆盖。
        log_file = open(log_path, "ab")  # noqa: ASYNC230, SIM115
        try:
            self._proc = await asyncio.create_subprocess_exec(
                service_python,
                service_script,
                "--model-dir",
                model_dir,
                "--wav2vec-dir",
                wav2vec_dir,
                "--port",
                str(port),
                "--image",
                self._portrait_path,
                "--jpeg-quality",
                str(jpeg_quality),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(workspace),
            )
        except Exception as e:
            log_file.close()
            raise BlockSetupError("avatar.flashhead", f"service spawn failed: {e}") from e

        import websockets

        ws_url = f"ws://127.0.0.1:{port}"
        deadline = asyncio.get_event_loop().time() + 180
        ws = None
        while asyncio.get_event_loop().time() < deadline:
            if self._proc.returncode is not None:
                log_file.close()
                raise BlockSetupError(
                    "avatar.flashhead",
                    f"service exited rc={self._proc.returncode}（见 {log_path}）",
                )
            try:
                ws = await websockets.connect(ws_url, open_timeout=10)
                break
            except Exception as e:
                logger.warning("flashhead ws connect failed, retrying: %s", e)
                await asyncio.sleep(2)
        if ws is None:
            await self._stop()
            log_file.close()
            raise BlockSetupError(
                "avatar.flashhead", f"cannot connect {ws_url}（见 {log_path}）"
            )
        self._ws = ws
        try:
            ready = await asyncio.wait_for(ws.recv(), timeout=30)
            ready = json.loads(ready)
            assert ready.get("type") == "ready"
            await ws.send(
                json.dumps({"type": "set_image", "path": self._portrait_path})
            )
        except Exception as e:
            await self._stop()
            log_file.close()
            raise BlockSetupError(
                "avatar.flashhead", f"handshake failed: {e}（见 {log_path}）"
            ) from e
        log_file.close()

        self._avatar_state = AvatarState()
        # 当前 process 期 ctx——reader task 从这里取 run_id/session_id，
        # 而非固定使用 setup 期的 ctx（后者 run_id 恒为 None，帧归因失真）
        self._current_ctx = ctx
        self._reader_task = asyncio.create_task(self._frame_reader())
        self._mark_ready()
        await ctx.logger.ainfo(
            "avatar.flashhead ready",
            ws=ws_url,
            portrait=self._portrait_path,
        )

    async def process(self, ctx: BlockContext, event: Event) -> None:
        # 更新当前 ctx——reader task 从这里取 run_id/session_id（非 setup 期的固定 ctx）
        self._current_ctx = ctx
        # 统一状态机：所有事件走 transition_avatar_state 推导 speech_active/idle_mode
        # （对齐 VoxEMW avatar_state_transition，避免两套状态机漂移）
        ev_type = event.type
        has_audio = ev_type == TTS_AUDIO_DELTA and bool(event.payload.get("pcm_b64"))
        new_state = transition_avatar_state(
            self._avatar_state, ev_type, has_audio=has_audio
        )
        changed = (
            new_state.speech_active != self._avatar_state.speech_active
            or new_state.idle_mode != self._avatar_state.idle_mode
        )
        if changed and self._ws is not None:
            try:
                if new_state.speech_active != self._avatar_state.speech_active:
                    await self._ws.send(
                        json.dumps(
                            {"type": "speech_active", "on": new_state.speech_active}
                        )
                    )
                if new_state.idle_mode != self._avatar_state.idle_mode:
                    await self._ws.send(
                        json.dumps(
                            {"type": "idle_mode", "mode": new_state.idle_mode}
                        )
                    )
            except Exception as e:
                await ctx.logger.aerror("flashhead state send failed", error=str(e))
        self._avatar_state = new_state

        if ev_type == TTS_AUDIO_DELTA:
            pcm_b64 = event.payload.get("pcm_b64", "")
            if pcm_b64 and self._ws is not None:
                try:
                    await self._ws.send(
                        json.dumps({"type": "audio", "pcm": pcm_b64})
                    )
                except Exception as e:
                    await ctx.logger.aerror("flashhead send audio failed", error=str(e))
        elif ev_type == TTS_AUDIO_COMPLETED:
            if self._ws is not None:
                try:
                    await self._ws.send(json.dumps({"type": "reset"}))
                except Exception as e:
                    await ctx.logger.aerror("flashhead reset failed", error=str(e))
            await self._emit_idle(ctx)

    async def _frame_reader(self) -> None:
        try:
            async for message in self._ws:
                ctx = self._current_ctx  # 取当前 process 期 ctx（run_id 正确归属当前轮）
                if ctx is None:
                    continue  # setup 完成但首个 process 未到达——帧暂弃
                if isinstance(message, (bytes, bytearray)):
                    data = bytes(message)
                    # service 下行协议：首字节 tag（0x00=idle / 0x01=speech）+ JPEG
                    tag = data[0] if data else 0x01
                    jpeg = data[1:]
                    if not jpeg:
                        continue
                    is_speech = tag == 0x01
                    idx = self._frame_index
                    self._frame_index += 1
                    await ctx.emit(
                        Event(
                            type=AVATAR_SPEECH_FRAME if is_speech else AVATAR_IDLE_FRAME,
                            session_id=ctx.session_id,
                            source="avatar.flashhead",
                            run_id=ctx.run_id,
                            payload={
                                "frame_b64": base64.b64encode(jpeg).decode("ascii"),
                                "width": 512,
                                "height": 512,
                                "format": "jpeg",
                                "frame_index": idx,
                                "is_speech": is_speech,
                            },
                        )
                    )
                else:
                    # JSON 控制帧（error 等）
                    try:
                        obj = json.loads(message)
                        if obj.get("type") == "error":
                            await ctx.logger.aerror(
                                "flashhead service error",
                                message=obj.get("message"),
                            )
                    except Exception:
                        pass
        except Exception as e:
            if ctx is not None:
                await ctx.logger.aerror("flashhead frame reader ended", error=str(e))
        finally:
            # reader 退出后置 ws 为 None：process() 的 None 守卫会拦截后续 send，
            # 避免对已死 ws 反复报错刷屏。emit 一帧 idle 做兜底，下游不至于画面卡死。
            self._ws = None
            if not self._shutdown and ctx is not None:
                try:
                    await self._emit_idle(ctx)
                except Exception as e:
                    await ctx.logger.aerror(
                        "flashhead idle fallback emit failed", error=str(e)
                    )

    async def _emit_idle(self, ctx: BlockContext) -> None:
        await ctx.emit(
            Event(
                type=AVATAR_IDLE_FRAME,
                session_id=ctx.session_id,
                source="avatar.flashhead",
                run_id=ctx.run_id,
                payload={
                    "frame_b64": base64.b64encode(self._portrait_bytes).decode(
                        "ascii"
                    ),
                    "width": 512,
                    "height": 512,
                    "format": "jpeg",
                    "frame_index": self._frame_index,
                    "is_speech": False,
                },
            )
        )

    async def reset(self, session_id: str) -> None:
        self._frame_index = 0
        if self._ws is not None:
            with suppress(Exception):
                await self._ws.send(json.dumps({"type": "reset"}))

    async def shutdown(self) -> None:
        self._shutdown = True  # 先置位——reader 退出后不 emit（ctx 可能已 unwire）
        await self._stop()

    async def _stop(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                # reader 是我们自己 cancel 的——自取消属正常退出路径，吞掉；
                # 只有当前任务自身也被取消（loop teardown/外部打断）才透传，
                # 否则吞掉外部取消会让 asyncio.run 的 gather 永远等本任务
                current = asyncio.current_task()
                if current is not None and current.cancelling() > 0:
                    raise
            except Exception:
                pass
            self._reader_task = None
        if self._ws is not None:
            with suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                with suppress(Exception):
                    self._proc.kill()
        self._proc = None
