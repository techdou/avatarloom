"""事件类型枚举和 Event Envelope。

Envelope 规范见 docs/02-事件协议状态机与音画同步.md：

    {
      "id": "evt_xxx",
      "type": "transcript.completed",
      "session_id": "ses_xxx",
      "run_id": "run_xxx",
      "timestamp": 0,
      "source": "stt.sensevoice",
      "sequence": 1,
      "payload": {}
    }

所有跨 Block、跨服务、前后端通信都必须用这个信封。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from avatarloom_protocol.state import State

# ---------------------------------------------------------------------------
# 事件类型枚举
# ---------------------------------------------------------------------------


class EventType(str):
    """事件类型字符串常量。

    用 str 子类而不是 Enum，便于第三方 Block 自定义事件类型字符串
    直接和我们的字面量比较（"my.custom.event" == EventType.XXX）。
    """


# session.*
SESSION_STARTED = EventType("session.started")
SESSION_CLOSED = EventType("session.closed")
SESSION_STATE_CHANGED = EventType("session.state_changed")
SESSION_ERROR = EventType("session.error")

# audio.* （上行麦克风、下行 TTS PCM 都用这个）
AUDIO_APPENDED = EventType("audio.appended")  # 浏览器上行 PCM chunk
AUDIO_INTERRUPTED = EventType("audio.interrupted")  # 打断清空音频队列

# speech.* （VAD）
SPEECH_DETECTED = EventType("speech.detected")  # VAD 检测到开始说话
SPEECH_ENDED = EventType("speech.ended")  # VAD 检测到停顿/说完

# transcript.* （STT）
TRANSCRIPT_COMPLETED = EventType("transcript.completed")
TRANSCRIPT_PARTIAL = EventType("transcript.partial")

# llm.*
LLM_TEXT_DELTA = EventType("llm.text.delta")
LLM_TEXT_DONE = EventType("llm.text.done")
LLM_ERROR = EventType("llm.error")

# tts.*
TTS_AUDIO_DELTA = EventType("tts.audio.delta")
TTS_AUDIO_COMPLETED = EventType("tts.audio.completed")
TTS_ERROR = EventType("tts.error")

# avatar.*
AVATAR_SPEECH_FRAME = EventType("avatar.speech_frame")  # 说话期间的视频帧（JPEG/PCM 驱动）
AVATAR_IDLE_FRAME = EventType("avatar.idle_frame")  # 待机帧
AVATAR_RESET = EventType("avatar.reset")
AVATAR_DEGRADED = EventType("avatar.degraded")  # 降级到 StaticAvatar
AVATAR_VIDEO_READY = EventType("avatar.video.ready")  # 真实口型视频渲染完成（含 mp4 路径）

# vision.*
VISION_RESULT = EventType("vision.result")

# persona.*
PERSONA_CHANGED = EventType("persona.changed")

# response.* （一轮回复的生命周期）
RESPONSE_STARTED = EventType("response.started")
RESPONSE_DONE = EventType("response.done")
RESPONSE_INTERRUPTED = EventType("response.interrupted")

# block.*
BLOCK_SETUP = EventType("block.setup")
BLOCK_READY = EventType("block.ready")
BLOCK_ERROR = EventType("block.error")
BLOCK_HEALTH = EventType("block.health")

# run.*
RUN_STARTED = EventType("run.started")
RUN_METRICS = EventType("run.metrics")
RUN_COMPLETED = EventType("run.completed")

# artifact.*
ARTIFACT_CREATED = EventType("artifact.created")


# ---------------------------------------------------------------------------
# Event Envelope
# ---------------------------------------------------------------------------

# 前缀映射，用于 source 命名规范（如 "stt.sensevoice"、"llm.openai-compat"）
CATEGORY_PREFIXES = (
    "session",
    "audio",
    "speech",
    "transcript",
    "llm",
    "tts",
    "avatar",
    "vision",
    "persona",
    "response",
    "block",
    "run",
    "artifact",
)


def _new_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _now_ms() -> int:
    """毫秒时间戳。用整数避免浮点精度问题。"""
    return int(time.time() * 1000)


class EventEnvelope(BaseModel):
    """事件信封——所有事件的统一容器。

    payload 字段是 Any，由具体事件类型约束（见 payloads.py）。
    Envelope 层只管路由、序列化、追踪。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: _new_id("evt"))
    type: str = Field(description="事件类型，如 'transcript.completed'")
    session_id: str = Field(description="会话 ID，ses_ 前缀")
    run_id: str | None = Field(default=None, description="当前 Run ID，run_ 前缀")
    timestamp: int = Field(default_factory=_now_ms, description="毫秒 Unix 时间戳")
    source: str = Field(description="事件来源 Block，如 'stt.sensevoice'")
    sequence: int = Field(default=0, description="会话内单调递增序号")
    payload: dict[str, Any] = Field(default_factory=dict, description="事件负载")


class Event(EventEnvelope):
    """事件别名。Event 更符合口语，EventEnvelope 更符合协议文档用语。"""


# ---------------------------------------------------------------------------
# 便捷构造器：标准事件工厂
# ---------------------------------------------------------------------------


def make_event(
    type_: str,
    session_id: str,
    source: str,
    *,
    run_id: str | None = None,
    sequence: int = 0,
    payload: dict[str, Any] | None = None,
) -> Event:
    """构造标准事件。"""
    return Event(
        type=type_,
        session_id=session_id,
        source=source,
        run_id=run_id,
        sequence=sequence,
        payload=payload or {},
    )


def make_state_event(
    session_id: str,
    from_state: State,
    to_state: State,
    sequence: int = 0,
    run_id: str | None = None,
) -> Event:
    """构造状态变更事件。"""
    return Event(
        type=SESSION_STATE_CHANGED,
        session_id=session_id,
        source="session.state_machine",
        run_id=run_id,
        sequence=sequence,
        payload={"from": from_state.value, "to": to_state.value},
    )


# ---------------------------------------------------------------------------
# 事件分类辅助
# ---------------------------------------------------------------------------


def event_category(event_type: str) -> str:
    """从事件类型提取分类前缀。'transcript.completed' -> 'transcript'。"""
    return event_type.split(".", 1)[0] if "." in event_type else event_type
