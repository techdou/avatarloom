"""事件负载结构。

每种事件类型的 payload 定义为 Pydantic 模型。这些模型同时承担：
1. 服务端类型约束
2. JSON Schema 导出（供 TS 客户端和 Control API 校验）

设计：payload 模型只描述结构，不含业务逻辑。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _BasePayload(BaseModel):
    """所有 payload 的基类。允许扩展字段，第三方 Block 可加自定义字段。"""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# session.*
# ---------------------------------------------------------------------------


class SessionStartedPayload(_BasePayload):
    session_id: str
    profile_id: str = Field(description="Runtime Profile ID")
    persona_id: str | None = None
    workspace_root: str = "."


class SessionClosedPayload(_BasePayload):
    session_id: str
    reason: Literal["normal", "error", "interrupted", "timeout"] = "normal"


class SessionStateChangedPayload(_BasePayload):
    """状态变更 payload。实际 WS 发送的字段是 from/to（见 envelope.make_state_event），
    不是 from_state/to_state——保持与线上 JSON 一致。trigger 未实际发送，保留可选。"""

    from_: str = Field(alias="from")
    to: str
    trigger: str | None = None


class SessionErrorPayload(_BasePayload):
    code: str
    message: str
    block_id: str | None = None
    recoverable: bool = True


# ---------------------------------------------------------------------------
# audio.*
# ---------------------------------------------------------------------------


class AudioAppendedPayload(_BasePayload):
    """浏览器上行麦克风 PCM chunk。"""

    # PCM16 base64 编码（ASCII 安全，便于 ws 传输）
    pcm_b64: str = Field(description="base64 编码的 PCM16 数据")
    sample_rate: int = 16000
    channels: int = 1
    samples: int = Field(description="本 chunk 的采样数", ge=0)
    timestamp_ms: int = Field(default=0, description="会话内相对时间戳")


class AudioInterruptedPayload(_BasePayload):
    """打断时清空音频队列。"""

    reason: Literal["user_speech", "cancel", "session_closed"] = "user_speech"


# ---------------------------------------------------------------------------
# speech.* （VAD）
# ---------------------------------------------------------------------------


class SpeechDetectedPayload(_BasePayload):
    """VAD 检测到开始说话。"""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SpeechEndedPayload(_BasePayload):
    """VAD 检测到说完（端点检测）。"""

    duration_ms: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# transcript.* （STT）
# ---------------------------------------------------------------------------


class TranscriptCompletedPayload(_BasePayload):
    text: str
    language: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # 可选：情绪/语种等附加标签（VoxEMW 的 SenseVoice 情绪侧信道用法）
    tags: dict[str, str] = Field(default_factory=dict)


class TranscriptPartialPayload(_BasePayload):
    text: str
    is_final: bool = False


# ---------------------------------------------------------------------------
# llm.*
# ---------------------------------------------------------------------------


class LlmRequestPayload(_BasePayload):
    text: str
    language: str = "zh"
    transcript_event_id: str | None = None
    vision_context: str | None = None


class LlmTextDeltaPayload(_BasePayload):
    text: str
    # 句子切分信息：TTS 按句喂
    sentence_index: int = Field(default=0, ge=0)
    is_sentence_end: bool = False


class LlmTextDonePayload(_BasePayload):
    full_text: str
    # "interrupted" 是打断链路的实际取值（LLM block reset 路径），
    # "cancelled" 保留为历史兼容别名。
    finish_reason: Literal["stop", "length", "cancelled", "interrupted", "error"] = "stop"
    # 性能指标（由 LLM Block 自报）
    first_token_ms: int | None = None
    total_tokens: int | None = None


# ---------------------------------------------------------------------------
# tts.*
# ---------------------------------------------------------------------------


class TtsAudioDeltaPayload(_BasePayload):
    pcm_b64: str = Field(description="base64 PCM16 数据")
    sample_rate: int = 16000
    samples: int = Field(ge=0)
    # 音频主时钟用：本 chunk 对应的文本（用于前端对齐字幕）
    text: str | None = None


class TtsAudioCompletedPayload(_BasePayload):
    total_samples: int = Field(ge=0)
    duration_ms: int = Field(default=0, ge=0)
    # 性能指标
    first_audio_ms: int | None = None


# ---------------------------------------------------------------------------
# avatar.*
# ---------------------------------------------------------------------------


class AvatarFramePayload(_BasePayload):
    """数字人视频帧。"""

    # JPEG/PNG base64
    frame_b64: str
    width: int = 1280
    height: int = 720
    format: Literal["jpeg", "png"] = "jpeg"
    # 帧序号（前端检测丢帧）
    frame_index: int = Field(ge=0)
    # 该帧对应的音频时间戳（音画同步对齐用）
    audio_timestamp_ms: int | None = None
    is_speech: bool = Field(default=True, description="True=说话帧，False=待机帧")


class AvatarResetPayload(_BasePayload):
    reason: Literal["user_interrupt", "session_reset", "degraded"] = "user_interrupt"


class AvatarDegradedPayload(_BasePayload):
    """Avatar 降级事件。"""

    from_block: str
    to_block: str
    reason: str


class AvatarVideoReadyPayload(_BasePayload):
    video_path: str
    frames: int = Field(default=0, ge=0)
    audio_s: float = Field(default=0.0, ge=0.0)
    infer_s: float = Field(default=0.0, ge=0.0)
    fps_actual: float = Field(default=0.0, ge=0.0)
    fps: int = Field(default=25, gt=0)


# ---------------------------------------------------------------------------
# vision.*
# ---------------------------------------------------------------------------


class VisionRequestPayload(_BasePayload):
    keyword: str
    request_id: str


class VisionResultPayload(_BasePayload):
    description: str
    objects: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# persona.*
# ---------------------------------------------------------------------------


class PersonaChangedPayload(_BasePayload):
    persona_id: str
    # 三件套同步切换标记
    llm_instructions_changed: bool = True
    tts_voice_changed: bool = True
    avatar_asset_changed: bool = True
    memory_namespace: str | None = None


# ---------------------------------------------------------------------------
# response.* （一轮回复的生命周期）
# ---------------------------------------------------------------------------


class ResponseStartedPayload(_BasePayload):
    run_id: str
    transcript: str = Field(description="本轮用户输入")


class ResponseDonePayload(_BasePayload):
    run_id: str
    full_text: str
    duration_ms: int = Field(ge=0)
    interrupted: bool = False


class ResponseInterruptedPayload(_BasePayload):
    run_id: str
    reason: Literal["user_speech", "cancel", "error", "session_closed"] = "user_speech"
    partial_text: str = ""


# ---------------------------------------------------------------------------
# block.*
# ---------------------------------------------------------------------------


class BlockSetupPayload(_BasePayload):
    block_id: str
    block_type: str


class BlockReadyPayload(_BasePayload):
    block_id: str
    warmup_ms: int = Field(ge=0)


class BlockErrorPayload(_BasePayload):
    block_id: str
    code: str
    message: str
    # 是否触发降级
    degraded: bool = False
    fallback_block_id: str | None = None


class BlockHealthPayload(_BasePayload):
    block_id: str
    status: Literal["healthy", "degraded", "unhealthy"]
    latency_ms: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# run.*
# ---------------------------------------------------------------------------


class RunStartedPayload(_BasePayload):
    run_id: str
    session_id: str
    profile_id: str
    persona_id: str | None = None
    runtime_config: dict[str, Any] = Field(default_factory=dict)


class RunMetricsPayload(_BasePayload):
    run_id: str
    first_text_ms: int | None = None
    first_audio_ms: int | None = None
    first_frame_ms: int | None = None
    total_duration_ms: int | None = None
    interruptions: int = 0
    degradations: int = 0
    errors: int = 0


class RunCompletedPayload(_BasePayload):
    run_id: str
    status: Literal["completed", "interrupted", "error", "cancelled"] = "completed"
    metrics: RunMetricsPayload


# ---------------------------------------------------------------------------
# artifact.*
# ---------------------------------------------------------------------------


class ArtifactPayload(_BasePayload):
    artifact_id: str
    run_id: str
    kind: Literal["audio", "video", "image", "text", "json", "config"]
    # 本地存储路径（相对于 artifacts root）
    path: str
    mime_type: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
