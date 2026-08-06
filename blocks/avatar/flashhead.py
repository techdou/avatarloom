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
from pathlib import Path
from typing import Any

logger = logging.getLogger("avatar.flashhead")

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


class FlashHeadAvatarBlock(Block):
    """FlashHead——TTS 音频流驱动的实时说话头。"""

    _proc: Any = None
    _ws: Any = None
    _reader_task: asyncio.Task[None] | None = None
    _frame_index: int = 0
    _avatar_state: Any = None  # AvatarState 实例（transition_avatar_state 推导）
    _portrait_bytes: bytes = b""
    _portrait_path: str = ""
    _fps: int = 25

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
        workspace = Path(ctx.workspace_root).resolve()
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

        service_python = str(
            cfg.get(
                "servicePython",
                "/root/autodl-tmp/avatarloom-avatar-venv/bin/python",
            )
        )
        service_script = str(
            cfg.get("serviceScript", str(workspace / "scripts" / "flashhead_service.py"))
        )
        if not Path(service_script).is_absolute():
            service_script = str(workspace / service_script)
        if not Path(service_script).exists():
            raise BlockSetupError(
                "avatar.flashhead", f"service script not found: {service_script}"
            )

        model_dir = str(
            cfg.get("modelDir", "/root/autodl-tmp/models/SoulX-FlashHead-1_3B")
        )
        wav2vec_dir = str(
            cfg.get("wav2vecDir", "/root/autodl-tmp/models/wav2vec2-base-960h")
        )
        port = int(cfg.get("servicePort", 8767))
        jpeg_quality = int(cfg.get("jpegQuality", 85))

        log_path = "/tmp/flashhead_service.log"
        log_file = open(log_path, "ab")
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
        self._reader_task = asyncio.create_task(self._frame_reader(ctx))
        self._mark_ready()
        await ctx.logger.ainfo(
            "avatar.flashhead ready",
            ws=ws_url,
            portrait=self._portrait_path,
        )

    async def process(self, ctx: BlockContext, event: Event) -> None:
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

    async def _frame_reader(self, ctx: BlockContext) -> None:
        try:
            async for message in self._ws:
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
            await ctx.logger.aerror("flashhead frame reader ended", error=str(e))
        finally:
            # reader 退出后置 ws 为 None：process() 的 None 守卫会拦截后续 send，
            # 避免对已死 ws 反复报错刷屏。emit 一帧 idle 做兜底，下游不至于画面卡死。
            self._ws = None
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
            try:
                await self._ws.send(json.dumps({"type": "reset"}))
            except Exception:
                pass

    async def shutdown(self) -> None:
        await self._stop()

    async def _stop(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
