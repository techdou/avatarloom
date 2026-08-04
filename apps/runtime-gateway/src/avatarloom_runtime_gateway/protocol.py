"""WebSocket 消息协议——浏览器 <-> Runtime Gateway。

设计：
- 上行（浏览器 -> Gateway）：
  - JSON: 控制消息（start_session, stop_session, set_persona, audio.appended 元数据）
  - 二进制: PCM16 音频 chunk（带 1 字节 tag 前缀，便于区分）
- 下行（Gateway -> 浏览器）：
  - JSON: 事件（session.*, transcript.*, llm.*, tts.*, avatar.*）
  - 二进制: TTS PCM chunk（带 tag 前缀）+ Avatar JPEG 帧

二进制 tag 规范（参考 VoxEMW orchestrator）：
  上行：
    0x02 + JPEG    用户摄像头截帧（vision）
  下行：
    0x01 + tag(1B) + JPEG   数字人视频帧（tag 0x00=idle, 0x01=speech）
    0x03 + PCM16    TTS 音频 chunk

  无 tag 的二进制 = PCM16 上行音频（最常见情况，简化前端）
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClientMessageType(StrEnum):
    """浏览器上行 JSON 消息类型。"""

    START_SESSION = "session.start"
    STOP_SESSION = "session.stop"
    SET_PERSONA = "persona.set"
    AUDIO_CHUNK = "audio.chunk"  # 伴随二进制 PCM 的元数据
    AUDIO_INTERRUPT = "audio.interrupt"  # 显式打断
    PING = "ping"


class ServerEventType(StrEnum):
    """Gateway 下行 JSON 事件类型（转发 Orchestrator 事件 + Gateway 自身状态）。"""

    SESSION_STARTED = "session.started"
    SESSION_CLOSED = "session.closed"
    STATE_CHANGED = "session.state_changed"
    TRANSCRIPT = "transcript.completed"
    LLM_DELTA = "llm.text.delta"
    LLM_DONE = "llm.text.done"
    TTS_DELTA_META = "tts.audio.delta"  # 元数据（pcm 在二进制消息里）
    TTS_DONE = "tts.audio.completed"
    AVATAR_FRAME_META = "avatar.frame"  # 元数据（jpeg 在二进制消息里）
    RESPONSE_STARTED = "response.started"
    RESPONSE_DONE = "response.done"
    ERROR = "error"
    PONG = "pong"


# ---------------------------------------------------------------------------
# 二进制 tag
# ---------------------------------------------------------------------------

TAG_PCM_UPLINK = 0x00  # 上行 PCM（实际无 tag，纯二进制即 PCM）
TAG_CAMERA_FRAME = 0x02  # 上行摄像头截帧
TAG_TTS_PCM_DOWNLINK = 0x03  # 下行 TTS PCM
TAG_AVATAR_JPEG = 0x01  # 下行 Avatar JPEG（+ 子 tag idle/speech）


# ---------------------------------------------------------------------------
# 上行消息 schemas
# ---------------------------------------------------------------------------


class ClientMessage(BaseModel):
    """上行消息信封。"""

    model_config = ConfigDict(extra="allow")

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class StartSessionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile_id: str | None = None
    persona_id: str | None = None
    workspace_root: str = "."


# ---------------------------------------------------------------------------
# 下行事件 schema
# ---------------------------------------------------------------------------


class ServerEvent(BaseModel):
    """下行事件信封。"""

    model_config = ConfigDict(extra="allow")

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
