"""WebSocket 会话处理。

负责：
- 接收浏览器上行（JSON 控制 + 二进制 PCM）
- 转发 PCM 到 Orchestrator.ingest_audio
- 接收 Orchestrator emit 的事件，转发给浏览器（JSON + 二进制 PCM/JPEG）
- 管理会话生命周期

音频编码：PCM16/16kHz/单声道，base64 编码放 JSON payload.pcm_b64。
v0.1 用 JSON 承载音频（简化前端实现）；二进制通道留给 Avatar JPEG。
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    AVATAR_VIDEO_READY,
    RESPONSE_DONE,
    SESSION_STATE_CHANGED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from avatarloom_runtime_gateway.config import Settings
from avatarloom_runtime_gateway.protocol import (
    TAG_AVATAR_JPEG,
    TAG_TTS_PCM_DOWNLINK,
    ClientMessage,
)
from runtime.orchestrator import Orchestrator
from runtime.orchestrator.config import BlockRef, OrchestratorConfig
from runtime.recorder import RunRecorder
from runtime.session import Session

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Mock Profile 默认配置（无 GPU/API Key 也能跑）
def _mock_profile_config() -> OrchestratorConfig:
    return OrchestratorConfig(
        profile_id="mock",
        blocks={
            "vad": BlockRef(
                id="vad.mock",
                deployment="mock",
                config={
                    "energy_threshold": 300.0,
                    "min_speech_chunks": 2,
                    "silence_chunks_to_end": 3,
                },
            ),
            "stt": BlockRef(id="stt.mock", deployment="mock"),
            "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 30}),
            "tts": BlockRef(id="tts.mock", deployment="mock", config={"ms_per_char": 50}),
            "avatar": BlockRef(id="avatar.mock", deployment="mock"),
        },
    )


class WebSocketSession:
    """单浏览器连接的 WS 会话。"""

    def __init__(self, ws: WebSocket, settings: Settings) -> None:
        self.ws = ws
        self.settings = settings
        self.orchestrator: Orchestrator | None = None
        self.session: Session | None = None
        self.recorder: RunRecorder | None = None
        self._downlink_queue: asyncio.Queue[dict[str, Any] | bytes] = asyncio.Queue(maxsize=512)
        self._downlink_task: asyncio.Task[None] | None = None
        self._closed = False

    async def run(self) -> None:
        """主循环：接收上行消息，处理控制 + 音频。"""
        # 启动下行发送任务
        self._downlink_task = asyncio.create_task(self._downlink_sender())

        try:
            while not self._closed:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if "text" in msg and msg["text"] is not None:
                    await self._handle_json(msg["text"])
                elif "bytes" in msg and msg["bytes"] is not None:
                    await self._handle_bytes(msg["bytes"])
        except WebSocketDisconnect:
            pass
        finally:
            await self.cleanup()

    async def _handle_json(self, text: str) -> None:
        """处理上行 JSON 消息。"""
        try:
            import json

            data = json.loads(text)
            msg = ClientMessage(**data)
        except Exception as e:
            await self._send_error(f"invalid message: {e}")
            return

        if msg.type == "session.start":
            await self._start_session(msg.payload)
        elif msg.type == "session.stop":
            await self._stop_session()
        elif msg.type == "persona.set":
            await self._set_persona(msg.payload.get("persona_id"))
        elif msg.type == "audio.chunk":
            # PCM 在 payload.pcm_b64 里
            await self._handle_audio_chunk(msg.payload)
        elif msg.type == "audio.interrupt":
            await self._handle_interrupt()
        elif msg.type == "ping":
            await self._enqueue_json({"type": "pong"})

    async def _handle_bytes(self, data: bytes) -> None:
        """处理上行二进制：默认当作 PCM16。"""
        if not self.session or not self.orchestrator:
            return
        # 16-bit samples
        samples = len(data) // 2
        pcm_b64 = base64.b64encode(data).decode("ascii")
        await self.orchestrator.ingest_audio(self.session, pcm_b64, samples)

    async def _handle_audio_chunk(self, payload: dict[str, Any]) -> None:
        """处理 audio.chunk JSON 消息（带 pcm_b64）。"""
        if not self.session or not self.orchestrator:
            return
        pcm_b64 = payload.get("pcm_b64", "")
        samples = payload.get("samples", 0)
        if pcm_b64:
            await self.orchestrator.ingest_audio(self.session, pcm_b64, samples)

    async def _handle_interrupt(self) -> None:
        """显式打断。"""
        if not self.session or not self.orchestrator:
            return
        await self.orchestrator.handle_user_speech_started(self.session)

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    async def _start_session(self, payload: dict[str, Any]) -> None:
        """启动新会话。"""
        profile_id = payload.get("profile_id") or self.settings.default_profile
        persona_id = payload.get("persona_id")

        # v0.1：默认用 Mock profile（profile 加载逻辑在阶段 9 完善）
        config = None
        profiles_dir = Path(self.settings.workspace_root) / "profiles"
        profile_path = profiles_dir / f"{profile_id}.yaml"
        if profile_path.exists():
            try:
                from runtime.orchestrator.profile_loader import load_profile

                config = load_profile(profile_path)
            except Exception as e:
                await self._send_error(f"profile load failed: {e}")
                return
        if config is None:
            config = _mock_profile_config()
            config.profile_id = profile_id

        # Recorder 接收所有事件
        self.recorder = RunRecorder(root=self.settings.runs_root)
        orchestrator = Orchestrator(
            config,
            event_sink=self._on_orchestrator_event,
        )
        try:
            await orchestrator.setup()
        except Exception as e:
            await self._send_error(f"orchestrator setup failed: {e}")
            return

        self.orchestrator = orchestrator
        self.session = await orchestrator.start_session(
            persona_id=persona_id,
            workspace_root=self.settings.workspace_root,
        )

        await self._enqueue_json(
            {
                "type": "session.started",
                "payload": {
                    "session_id": self.session.session_id,
                    "profile_id": profile_id,
                    "persona_id": persona_id,
                    "state": self.session.state.value,
                },
            }
        )
        logger.info("ws session started: %s (profile=%s)", self.session.session_id, profile_id)

    async def _stop_session(self) -> None:
        """停止会话。"""
        await self.cleanup()

    async def _set_persona(self, persona_id: str | None) -> None:
        """切换 Persona。v0.1 简化：只 emit persona.changed，实际切换在阶段 7 完善。"""
        if not self.session:
            return
        if persona_id:
            self.session.persona_id = persona_id
        await self._enqueue_json(
            {
                "type": "persona.changed",
                "payload": {"persona_id": persona_id},
            }
        )

    # ------------------------------------------------------------------
    # Orchestrator 事件 -> 浏览器
    # ------------------------------------------------------------------

    async def _on_orchestrator_event(self, event: Event) -> None:
        """Orchestrator emit 的事件出口——转发给浏览器。

        - session.* / transcript.* / llm.* / response.* → JSON 下行
        - tts.audio.delta → 二进制 PCM 下行（tag + PCM）+ JSON 元数据
        - avatar.*_frame → 二进制 JPEG 下行（tag + JPEG）+ JSON 元数据
        """
        # Recorder 记录
        if self.recorder and event.run_id:
            await self.recorder.record(event)

        # 状态变更/会话事件
        if event.type == SESSION_STATE_CHANGED:
            await self._enqueue_json(
                {
                    "type": "session.state_changed",
                    "payload": event.payload,
                }
            )
        elif event.type == "session.started":
            await self._enqueue_json({"type": "session.started", "payload": event.payload})
        elif event.type == TRANSCRIPT_COMPLETED:
            await self._enqueue_json(
                {
                    "type": "transcript.completed",
                    "payload": event.payload,
                }
            )
        elif event.type == "llm.text.delta":
            await self._enqueue_json({"type": "llm.text.delta", "payload": event.payload})
        elif event.type == "llm.text.done":
            await self._enqueue_json({"type": "llm.text.done", "payload": event.payload})
            # 启动新一轮 Run 记录
            if self.recorder and event.run_id and event.run_id not in self.recorder._active:
                await self.recorder.start_run(
                    event.run_id,
                    event.session_id,
                    self.session.profile_id if self.session else "mock",
                )
        elif event.type == RESPONSE_DONE:
            await self._enqueue_json({"type": "response.done", "payload": event.payload})
            # 结束 Run 记录
            if self.recorder and event.run_id and event.run_id in self.recorder._active:
                await self.recorder.finalize_run(event.run_id)

        # TTS 音频：二进制下行 + JSON 元数据
        elif event.type == TTS_AUDIO_DELTA:
            pcm_b64 = event.payload.get("pcm_b64", "")
            if pcm_b64:
                try:
                    pcm = base64.b64decode(pcm_b64)
                    # 下行格式：0x03 + PCM
                    await self._downlink_queue.put(bytes([TAG_TTS_PCM_DOWNLINK]) + pcm)
                except Exception:
                    pass
            # 元数据（不含 pcm_b64，减小 JSON 体积）
            meta = {k: v for k, v in event.payload.items() if k != "pcm_b64"}
            await self._enqueue_json({"type": "tts.audio.delta", "payload": meta})

        elif event.type == TTS_AUDIO_COMPLETED:
            await self._enqueue_json({"type": "tts.audio.completed", "payload": event.payload})

        elif event.type == AVATAR_VIDEO_READY:
            await self._enqueue_json(
                {"type": "avatar.video.ready", "payload": event.payload}
            )

        # Avatar 帧：二进制下行
        elif event.type in (AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME):
            frame_b64 = event.payload.get("frame_b64", "")
            if frame_b64:
                try:
                    jpeg = base64.b64decode(frame_b64)
                    # 下行格式：0x01 + 0x00/0x01(子tag) + JPEG
                    sub_tag = 0x01 if event.type == AVATAR_SPEECH_FRAME else 0x00
                    await self._downlink_queue.put(bytes([TAG_AVATAR_JPEG, sub_tag]) + jpeg)
                except Exception:
                    pass

    async def _downlink_sender(self) -> None:
        """独立任务：从队列取消息发送，避免阻塞 Orchestrator。"""
        try:
            while not self._closed:
                msg = await self._downlink_queue.get()
                if self.ws.client_state != WebSocketState.CONNECTED:
                    break
                try:
                    if isinstance(msg, bytes):
                        await self.ws.send_bytes(msg)
                    else:
                        import json

                        await self.ws.send_text(json.dumps(msg, ensure_ascii=False))
                except Exception:
                    logger.exception("downlink send error")
                    break
        except asyncio.CancelledError:
            pass

    async def _enqueue_json(self, data: dict[str, Any]) -> None:
        """入队 JSON 下行消息。队满丢最旧。"""
        try:
            if self._downlink_queue.full():
                try:
                    self._downlink_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            self._downlink_queue.put_nowait(data)
        except asyncio.QueueFull:
            pass

    async def _send_error(self, message: str) -> None:
        await self._enqueue_json({"type": "error", "payload": {"message": message}})

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """清理会话资源。"""
        if self._closed:
            return
        self._closed = True

        if self.session and self.orchestrator:
            try:
                await self.orchestrator.end_session(self.session, reason="client_disconnect")
            except Exception:
                logger.exception("end_session error")

        if self.orchestrator:
            try:
                await self.orchestrator.shutdown()
            except Exception:
                logger.exception("orchestrator shutdown error")

        if self._downlink_task:
            self._downlink_task.cancel()
            try:
                await self._downlink_task
            except asyncio.CancelledError:
                pass

        self.orchestrator = None
        self.session = None
        self.recorder = None
