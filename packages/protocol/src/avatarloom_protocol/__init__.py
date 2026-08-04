"""AvatarLoom event protocol — single source of truth.

All cross-service, cross-block and frontend/backend shared event schemas live here.
TypeScript types are generated from these Pydantic models via JSON Schema.
"""

from avatarloom_protocol.envelope import (
    # artifact.*
    ARTIFACT_CREATED,
    # audio.*
    AUDIO_APPENDED,
    AUDIO_INTERRUPTED,
    AVATAR_DEGRADED,
    AVATAR_IDLE_FRAME,
    AVATAR_RESET,
    # avatar.*
    AVATAR_SPEECH_FRAME,
    BLOCK_ERROR,
    BLOCK_HEALTH,
    BLOCK_READY,
    # block.*
    BLOCK_SETUP,
    LLM_ERROR,
    # llm.*
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    # persona.*
    PERSONA_CHANGED,
    RESPONSE_DONE,
    RESPONSE_INTERRUPTED,
    # response.*
    RESPONSE_STARTED,
    RUN_COMPLETED,
    RUN_METRICS,
    # run.*
    RUN_STARTED,
    SESSION_CLOSED,
    SESSION_ERROR,
    # session.*
    SESSION_STARTED,
    SESSION_STATE_CHANGED,
    # speech.*
    SPEECH_DETECTED,
    SPEECH_ENDED,
    # transcript.*
    TRANSCRIPT_COMPLETED,
    TRANSCRIPT_PARTIAL,
    TTS_AUDIO_COMPLETED,
    # tts.*
    TTS_AUDIO_DELTA,
    TTS_ERROR,
    # vision.*
    VISION_RESULT,
    Event,
    EventEnvelope,
    EventType,
    event_category,
    make_event,
    make_state_event,
)
from avatarloom_protocol.payloads import (
    ArtifactPayload,
    AudioAppendedPayload,
    AvatarFramePayload,
    BlockErrorPayload,
    BlockHealthPayload,
    BlockReadyPayload,
    BlockSetupPayload,
    LlmTextDeltaPayload,
    LlmTextDonePayload,
    PersonaChangedPayload,
    ResponseDonePayload,
    ResponseInterruptedPayload,
    ResponseStartedPayload,
    RunCompletedPayload,
    RunMetricsPayload,
    RunStartedPayload,
    SessionClosedPayload,
    SessionStartedPayload,
    SpeechDetectedPayload,
    SpeechEndedPayload,
    TranscriptCompletedPayload,
    TtsAudioCompletedPayload,
    TtsAudioDeltaPayload,
    VisionResultPayload,
)
from avatarloom_protocol.state import (
    IllegalTransitionError,
    State,
    TransitionResult,
    can_transition,
    legal_triggers,
    transition,
)

__all__ = [
    # Envelope
    "Event",
    "EventEnvelope",
    "EventType",
    "make_event",
    "make_state_event",
    "event_category",
    # Event type constants
    "SESSION_STARTED",
    "SESSION_CLOSED",
    "SESSION_STATE_CHANGED",
    "SESSION_ERROR",
    "AUDIO_APPENDED",
    "AUDIO_INTERRUPTED",
    "SPEECH_DETECTED",
    "SPEECH_ENDED",
    "TRANSCRIPT_COMPLETED",
    "TRANSCRIPT_PARTIAL",
    "LLM_TEXT_DELTA",
    "LLM_TEXT_DONE",
    "LLM_ERROR",
    "TTS_AUDIO_DELTA",
    "TTS_AUDIO_COMPLETED",
    "TTS_ERROR",
    "AVATAR_SPEECH_FRAME",
    "AVATAR_IDLE_FRAME",
    "AVATAR_RESET",
    "AVATAR_DEGRADED",
    "VISION_RESULT",
    "PERSONA_CHANGED",
    "RESPONSE_STARTED",
    "RESPONSE_DONE",
    "RESPONSE_INTERRUPTED",
    "BLOCK_SETUP",
    "BLOCK_READY",
    "BLOCK_ERROR",
    "BLOCK_HEALTH",
    "RUN_STARTED",
    "RUN_METRICS",
    "RUN_COMPLETED",
    "ARTIFACT_CREATED",
    # Payloads
    "ArtifactPayload",
    "AudioAppendedPayload",
    "AvatarFramePayload",
    "BlockErrorPayload",
    "BlockHealthPayload",
    "BlockReadyPayload",
    "BlockSetupPayload",
    "LlmTextDeltaPayload",
    "LlmTextDonePayload",
    "PersonaChangedPayload",
    "ResponseDonePayload",
    "ResponseInterruptedPayload",
    "ResponseStartedPayload",
    "RunCompletedPayload",
    "RunMetricsPayload",
    "RunStartedPayload",
    "SessionClosedPayload",
    "SessionStartedPayload",
    "SpeechDetectedPayload",
    "SpeechEndedPayload",
    "TranscriptCompletedPayload",
    "TtsAudioCompletedPayload",
    "TtsAudioDeltaPayload",
    "VisionResultPayload",
    # State machine
    "State",
    "TransitionResult",
    "IllegalTransitionError",
    "can_transition",
    "transition",
    "legal_triggers",
]

__version__ = "0.1.0"
