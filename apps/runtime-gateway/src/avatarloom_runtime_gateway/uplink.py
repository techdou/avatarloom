"""上行消息分发——浏览器 → Gateway 的 JSON 控制消息 + 二进制 PCM/JPEG。

从 ws_handler.py 抽出的上行链路：
- ``handle_json(text)``：解析 JSON 信封，按 ``type`` 字段表驱动路由到对应 handler
- ``handle_bytes(data)``：按首字节 tag 路由（0x00+PCM → STT、0x02+JPEG → Vision、其他拒绝）

依赖注入：dispatcher 通过 ``UplinkContext`` Protocol 访问 session 状态
（orchestrator/session 是否就绪、生命周期方法 start/stop/set_persona、
下行 enqueue_json/send_error）。新增消息类型只需在 ``_JSON_HANDLERS`` 加一行映射。
"""

from __future__ import annotations

import base64
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from avatarloom_runtime_gateway.protocol import (
    MAX_CAMERA_FRAME_BYTES,
    TAG_CAMERA_FRAME,
    TAG_PCM_UPLINK,
    ClientMessage,
)
from runtime.orchestrator import Orchestrator
from runtime.session import Session

if TYPE_CHECKING:
    from avatarloom_runtime_gateway.event_bridge import OrchestratorEventBridge

logger = logging.getLogger(__name__)

# WS 上行消息大小上限——单条 JSON/二进制超此即拒绝，防内存 DoS
MAX_MSG_SIZE = 2 * 1024 * 1024  # 2MB


@runtime_checkable
class UplinkContext(Protocol):
    """dispatcher 访问 session 状态的最小接口。

    WebSocketSession 自然满足此 Protocol——它有 ``session`` / ``orchestrator``
    属性、``_start_session`` / ``_stop_session`` / ``_set_persona`` 方法、
    以及 ``_bridge``（提供 enqueue_json/send_error）。
    """

    session: Session | None
    orchestrator: Orchestrator | None
    bridge: OrchestratorEventBridge

    async def start_session(self, payload: dict[str, Any]) -> None: ...

    async def stop_session(self) -> None: ...

    async def set_persona(self, persona_id: str | None) -> None: ...


class UplinkDispatcher:
    """上行消息分发器。

    持一个 ``UplinkContext``（即 WebSocketSession）引用，把 JSON / 二进制消息
    路由到对应 handler。路由表驱动——新增 JSON 消息类型只需在 ``_JSON_HANDLERS``
    加一行 ``"type.name": "_handler_name"`` 映射。
    """

    def __init__(self, ctx: UplinkContext) -> None:
        self._ctx = ctx
        # 未知 tag 警告去重——error JSON 每连接只发一次，避免旧前端裸 PCM 刷屏
        self._warned_unknown_tag = False

    # ------------------------------------------------------------------
    # JSON 上行
    # ------------------------------------------------------------------

    async def handle_json(self, text: str) -> None:
        """处理上行 JSON 消息——表驱动路由。"""
        # 消息大小上限——防止恶意客户端发超大 JSON 撑爆内存
        if len(text) > MAX_MSG_SIZE:
            await self._ctx.bridge.send_error(f"message too large (max {MAX_MSG_SIZE} bytes)")
            return
        try:
            data = json.loads(text)
            msg = ClientMessage(**data)
        except Exception as e:
            await self._ctx.bridge.send_error(f"invalid message: {e}")
            return

        handler_name = _JSON_HANDLERS.get(msg.type)
        if handler_name is None:
            return
        handler = getattr(self, handler_name, None)
        if handler is None:
            return
        await handler(msg.payload)

    async def _on_start_session(self, payload: dict[str, Any]) -> None:
        await self._ctx.start_session(payload)

    async def _on_stop_session(self, _payload: dict[str, Any]) -> None:
        await self._ctx.stop_session()

    async def _on_set_persona(self, payload: dict[str, Any]) -> None:
        await self._ctx.set_persona(payload.get("persona_id"))

    async def _on_audio_chunk(self, payload: dict[str, Any]) -> None:
        await self._handle_audio_chunk(payload)

    async def _on_audio_interrupt(self, _payload: dict[str, Any]) -> None:
        await self._handle_interrupt()

    async def _on_vision_frame_error(self, payload: dict[str, Any]) -> None:
        await self._handle_vision_frame_error(payload)

    async def _on_ping(self, _payload: dict[str, Any]) -> None:
        await self._ctx.bridge.enqueue_json({"type": "pong"})

    # ------------------------------------------------------------------
    # 二进制上行
    # ------------------------------------------------------------------

    async def handle_bytes(self, data: bytes) -> None:
        """处理上行二进制：显式 tag 路由（AL-P1-001）。

        0x00 + PCM16 → STT；0x02 + JPEG → Vision；未知 tag 拒绝。
        不再"其他一律 PCM"——裸 PCM 首字节可能恰为 0x02 被误送 Vision。
        """
        if not self._ctx.session or not self._ctx.orchestrator:
            return
        if not data:
            return
        # 二进制消息大小上限——防止超大帧撑爆内存
        if len(data) > MAX_MSG_SIZE:
            logger.warning("ws binary message too large: %d bytes", len(data))
            return
        tag = data[0]

        if tag == TAG_PCM_UPLINK:
            pcm = data[1:]
            # 奇数字节/空 chunk 无法按 int16 解码，丢弃
            if len(pcm) < 2 or len(pcm) % 2 != 0:
                return
            samples = len(pcm) // 2
            pcm_b64 = base64.b64encode(pcm).decode("ascii")
            await self._ctx.orchestrator.ingest_audio(self._ctx.session, pcm_b64, samples)
            return

        if tag == TAG_CAMERA_FRAME:
            jpeg = data[1:]
            # AL-P1-011：大小 + JPEG SOI header 校验，防任意内容打远程 Vision API
            if len(jpeg) > MAX_CAMERA_FRAME_BYTES:
                logger.warning("camera frame too large: %d bytes, rejected", len(jpeg))
                await self._ctx.bridge.send_error(
                    f"camera frame too large ({len(jpeg)} > {MAX_CAMERA_FRAME_BYTES})"
                )
                return
            if not jpeg.startswith(b"\xff\xd8\xff"):
                logger.warning("camera frame is not JPEG (bad SOI), rejected")
                await self._ctx.bridge.send_error("camera frame is not a valid JPEG")
                return
            jpeg_b64 = base64.b64encode(jpeg).decode("ascii")
            await self._ctx.orchestrator.ingest_vision_frame(self._ctx.session, jpeg_b64)
            return

        # 未知 tag：拒绝。error JSON 每连接只发一次，避免旧前端裸 PCM 刷屏
        logger.warning("unknown uplink binary tag 0x%02x (%d bytes), rejected", tag, len(data))
        if not self._warned_unknown_tag:
            self._warned_unknown_tag = True
            await self._ctx.bridge.send_error(
                f"unknown binary tag 0x{tag:02x}——上行协议要求 0x00+PCM16 / 0x02+JPEG"
            )

    # ------------------------------------------------------------------
    # 辅助 handler（被 JSON 路由调用）
    # ------------------------------------------------------------------

    async def _handle_audio_chunk(self, payload: dict[str, Any]) -> None:
        """处理 audio.chunk JSON 消息（带 pcm_b64）。"""
        if not self._ctx.session or not self._ctx.orchestrator:
            return
        pcm_b64 = payload.get("pcm_b64", "")
        if not pcm_b64:
            return
        # samples 由服务端按解码长度计算，不信任客户端上报（防指标/时长误导）
        try:
            pcm = base64.b64decode(pcm_b64, validate=True)
        except Exception:
            await self._ctx.bridge.send_error("audio.chunk: invalid base64 pcm_b64")
            return
        if len(pcm) < 2 or len(pcm) % 2 != 0:
            await self._ctx.bridge.send_error("audio.chunk: PCM must be even-length int16")
            return
        samples = len(pcm) // 2
        await self._ctx.orchestrator.ingest_audio(self._ctx.session, pcm_b64, samples)

    async def _handle_interrupt(self) -> None:
        """显式打断。"""
        if not self._ctx.session or not self._ctx.orchestrator:
            return
        await self._ctx.orchestrator.handle_user_speech_started(self._ctx.session)

    async def _handle_vision_frame_error(self, payload: dict[str, Any]) -> None:
        """浏览器截帧失败——通知 Orchestrator 降级（唤醒同轮 Vision 等待）。"""
        if not self._ctx.session or not self._ctx.orchestrator:
            return
        reason = str(payload.get("reason") or "unknown")
        await self._ctx.orchestrator.handle_vision_frame_error(self._ctx.session, reason)


# ---------------------------------------------------------------------------
# JSON 消息路由表——新增消息类型只加一行映射
# ---------------------------------------------------------------------------

_JSON_HANDLERS: dict[str, str] = {
    "session.start": "_on_start_session",
    "session.stop": "_on_stop_session",
    "persona.set": "_on_set_persona",
    "audio.chunk": "_on_audio_chunk",
    "audio.interrupt": "_on_audio_interrupt",
    "vision.frame_error": "_on_vision_frame_error",
    "ping": "_on_ping",
}
