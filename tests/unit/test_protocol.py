"""Protocol 事件信封和 payload 序列化测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from avatarloom_protocol import (
    AUDIO_APPENDED,
    LLM_TEXT_DELTA,
    SESSION_STARTED,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_DELTA,
    AvatarFramePayload,
    Event,
)
from avatarloom_protocol.envelope import event_category, make_event, make_state_event
from avatarloom_protocol.payloads import (
    AudioAppendedPayload,
    LlmTextDeltaPayload,
    LlmTextDonePayload,
    SpeechDetectedPayload,
    TtsAudioDeltaPayload,
)
from avatarloom_protocol.state import State
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Event Envelope
# ---------------------------------------------------------------------------


class TestEventEnvelope:
    def test_basic_event_construction(self) -> None:
        e = Event(
            type=SESSION_STARTED,
            session_id="ses_abc",
            source="session.manager",
            payload={"profile_id": "mock"},
        )
        assert e.type == "session.started"
        assert e.session_id == "ses_abc"
        assert e.source == "session.manager"
        assert e.id.startswith("evt_")
        assert e.timestamp > 0

    def test_event_ids_are_unique(self) -> None:
        ids = {Event(type="x", session_id="s", source="b").id for _ in range(100)}
        assert len(ids) == 100

    def test_make_event_helper(self) -> None:
        e = make_event(
            TRANSCRIPT_COMPLETED,
            session_id="ses_1",
            source="stt.mock",
            sequence=5,
            payload={"text": "你好"},
        )
        assert e.type == "transcript.completed"
        assert e.sequence == 5
        assert e.payload["text"] == "你好"

    def test_make_state_event(self) -> None:
        e = make_state_event("ses_1", State.IDLE, State.LISTENING, sequence=3)
        assert e.type == "session.state_changed"
        assert e.payload == {"from": "idle", "to": "listening"}
        assert e.source == "session.state_machine"

    def test_event_serializes_to_json(self) -> None:
        e = make_event(SPEECH_DETECTED, "ses_1", "vad.mock", payload={"confidence": 0.9})
        # Pydantic v2 默认 mode_json
        s = e.model_dump_json()
        d = json.loads(s)
        assert d["type"] == "speech.detected"
        assert d["payload"]["confidence"] == 0.9

    def test_event_roundtrip_json(self) -> None:
        """事件 JSON 序列化 → 反序列化保持等价。"""
        e1 = make_event(
            TRANSCRIPT_COMPLETED,
            "ses_1",
            "stt.sensevoice",
            payload={"text": "你好", "language": "zh", "tags": {"emotion": "happy"}},
        )
        s = e1.model_dump_json()
        e2 = Event.model_validate_json(s)
        assert e2.type == e1.type
        assert e2.payload == e1.payload
        assert e2.session_id == e1.session_id

    def test_envelope_forbids_extra_fields(self) -> None:
        """信封不允许未知字段，避免协议漂移。"""
        with pytest.raises(ValidationError):
            Event(
                type="x",
                session_id="s",
                source="b",
                payload={},
                unknown_field="boom",  # type: ignore[call-arg]
            )

    def test_event_category_extraction(self) -> None:
        assert event_category("transcript.completed") == "transcript"
        assert event_category("session.started") == "session"
        assert event_category("plain") == "plain"


# ---------------------------------------------------------------------------
# Payload 校验
# ---------------------------------------------------------------------------


class TestPayloads:
    def test_audio_appended_payload(self) -> None:
        p = AudioAppendedPayload(
            pcm_b64="AAAA",
            sample_rate=16000,
            channels=1,
            samples=100,
        )
        assert p.sample_rate == 16000

    def test_audio_appended_rejects_negative_samples(self) -> None:
        with pytest.raises(ValidationError):
            AudioAppendedPayload(pcm_b64="x", samples=-1)

    def test_llm_text_delta_payload(self) -> None:
        p = LlmTextDeltaPayload(text="你好", sentence_index=0, is_sentence_end=False)
        d = p.model_dump()
        assert d["text"] == "你好"
        assert d["is_sentence_end"] is False

    def test_llm_done_finish_reason_accepts_interrupted(self) -> None:
        """打断链路实际 emit "interrupted"——协议 Literal 必须覆盖（契约回归）。"""
        p = LlmTextDonePayload(full_text="部分文本", finish_reason="interrupted")
        assert p.finish_reason == "interrupted"
        with pytest.raises(ValidationError):
            LlmTextDonePayload(full_text="x", finish_reason="unknown")  # type: ignore[arg-type]

    def test_tts_audio_delta_requires_samples_ge_zero(self) -> None:
        p = TtsAudioDeltaPayload(pcm_b64="A", samples=0)
        assert p.samples == 0
        with pytest.raises(ValidationError):
            TtsAudioDeltaPayload(pcm_b64="A", samples=-5)

    def test_speech_detected_confidence_range(self) -> None:
        SpeechDetectedPayload(confidence=0.0)
        SpeechDetectedPayload(confidence=1.0)
        with pytest.raises(ValidationError):
            SpeechDetectedPayload(confidence=1.5)
        with pytest.raises(ValidationError):
            SpeechDetectedPayload(confidence=-0.1)

    def test_avatar_frame_payload_format_enum(self) -> None:
        p = AvatarFramePayload(frame_b64="x", frame_index=0, format="jpeg")
        assert p.format == "jpeg"
        with pytest.raises(ValidationError):
            AvatarFramePayload(frame_b64="x", frame_index=0, format="bmp")  # type: ignore[arg-type]

    def test_payload_allows_extra_fields(self) -> None:
        """第三方 Block 可加自定义字段（payload 基类 extra=allow）。"""
        p = AudioAppendedPayload(
            pcm_b64="A",
            samples=1,
            custom_field="允许扩展",  # type: ignore[call-arg]
        )
        assert p.model_dump()["custom_field"] == "允许扩展"  # type: ignore[index]


# ---------------------------------------------------------------------------
# 事件类型常量一致性
# ---------------------------------------------------------------------------


class TestEventTypeConstants:
    def test_all_constants_are_str(self) -> None:
        for const in [
            SESSION_STARTED,
            SPEECH_DETECTED,
            SPEECH_ENDED,
            TRANSCRIPT_COMPLETED,
            LLM_TEXT_DELTA,
            TTS_AUDIO_DELTA,
            AUDIO_APPENDED,
        ]:
            assert isinstance(const, str)
            assert "." in const

    def test_constants_match_documented_names(self) -> None:
        """对照 docs/02 协议文档的命名。"""
        assert SESSION_STARTED == "session.started"
        assert SPEECH_DETECTED == "speech.detected"
        assert SPEECH_ENDED == "speech.ended"
        assert TRANSCRIPT_COMPLETED == "transcript.completed"
        assert LLM_TEXT_DELTA == "llm.text.delta"
        assert TTS_AUDIO_DELTA == "tts.audio.delta"


def test_generated_protocol_is_in_sync() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "gen_protocol.py"), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        # 子进程 stdout 已强制 UTF-8；GBK 控制台下若不指定编码会解码失败
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
