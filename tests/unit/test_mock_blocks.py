"""Mock Blocks 单元测试。"""

from __future__ import annotations

import base64

import numpy as np
from avatarloom_protocol import (
    AUDIO_APPENDED,
    LLM_TEXT_DELTA,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import BlockContext

from blocks.avatar.mock import MockAvatarBlock
from blocks.llm.mock import MockLlmBlock
from blocks.stt.mock import MockSttBlock
from blocks.tts.mock import MockTtsBlock
from blocks.vad.mock import MockVadBlock


def _make_pcm(samples: int, amplitude: float = 1000.0) -> str:
    """生成 PCM16 base64（恒幅）。

    amplitude 是 0-1000 的相对值，乘以 32767/1000 得到真实振幅。
    amplitude=10 -> 振幅 ~328（接近阈值，不算静音）
    amplitude=0  -> 真正静音
    """
    real_amp = int(amplitude * 32767 / 1000)
    arr = np.full(samples, real_amp, dtype=np.int16)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def _make_silent_pcm(samples: int = 1600) -> str:
    """生成绝对静音 PCM。"""
    arr = np.zeros(samples, dtype=np.int16)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def _make_ctx() -> BlockContext:
    return BlockContext(session_id="s1", run_id="r1", workspace_root=".")


async def _setup_block(block, ctx: BlockContext) -> None:
    await block.setup(ctx)


async def _capture_emits(block, ctx, event) -> list[Event]:
    out: list[Event] = []

    async def cap(e: Event) -> None:
        out.append(e)

    ctx._emit_fn = cap  # type: ignore[attr-defined]
    ctx._logger = None  # type: ignore[attr-defined]
    await block.process(ctx, event)
    return out


# ---------------------------------------------------------------------------
# MockVadBlock
# ---------------------------------------------------------------------------


class TestMockVad:
    async def test_silence_does_not_trigger(self) -> None:
        block = MockVadBlock()
        ctx = _make_ctx()
        ctx.config = {"energy_threshold": 300.0, "min_speech_chunks": 2}
        await _setup_block(block, ctx)
        # 低能量音频
        event = Event(
            type=AUDIO_APPENDED,
            session_id="s1",
            source="t",
            payload={"pcm_b64": _make_pcm(1600, amplitude=10), "samples": 1600},
        )
        out = await _capture_emits(block, ctx, event)
        assert out == []

    async def test_loud_audio_triggers_speech_detected(self) -> None:
        block = MockVadBlock()
        ctx = _make_ctx()
        ctx.config = {"energy_threshold": 300.0, "min_speech_chunks": 2}
        await _setup_block(block, ctx)
        # 连续两个高能量 chunk 触发
        loud_event = Event(
            type=AUDIO_APPENDED,
            session_id="s1",
            source="t",
            payload={"pcm_b64": _make_pcm(1600, amplitude=800), "samples": 1600},
        )
        # 第一次（_speech_chunk_count=1，还没到 min=2）
        await _capture_emits(block, ctx, loud_event)
        # 第二次（_speech_chunk_count=2，触发）
        out = await _capture_emits(block, ctx, loud_event)
        assert any(e.type == SPEECH_DETECTED for e in out)

    async def test_silence_after_speech_triggers_ended(self) -> None:
        block = MockVadBlock()
        ctx = _make_ctx()
        ctx.config = {
            "energy_threshold": 300.0,
            "min_speech_chunks": 1,
            "silence_chunks_to_end": 2,
        }
        await _setup_block(block, ctx)
        loud = Event(
            type=AUDIO_APPENDED,
            session_id="s1",
            source="t",
            payload={"pcm_b64": _make_pcm(1600, amplitude=800), "samples": 1600},
        )
        silent = Event(
            type=AUDIO_APPENDED,
            session_id="s1",
            source="t",
            payload={"pcm_b64": _make_silent_pcm(1600), "samples": 1600},
        )
        await _capture_emits(block, ctx, loud)  # 触发 detected
        await _capture_emits(block, ctx, silent)  # silence count 1
        out = await _capture_emits(block, ctx, silent)  # silence count 2 -> ended
        assert any(e.type == SPEECH_ENDED for e in out)

    async def test_reset_clears_state(self) -> None:
        block = MockVadBlock()
        ctx = _make_ctx()
        await _setup_block(block, ctx)
        await block.reset("s1")
        assert block._is_speaking is False


# ---------------------------------------------------------------------------
# MockSttBlock
# ---------------------------------------------------------------------------


class TestMockStt:
    async def test_speech_ended_emits_transcript(self) -> None:
        block = MockSttBlock()
        ctx = _make_ctx()
        ctx.config = {"mode": "fixed", "fixed_text": "测试文本"}
        await _setup_block(block, ctx)
        event = Event(type=SPEECH_ENDED, session_id="s1", source="vad")
        out = await _capture_emits(block, ctx, event)
        assert len(out) == 1
        assert out[0].type == TRANSCRIPT_COMPLETED
        assert out[0].payload["text"] == "测试文本"

    async def test_random_mode_picks_from_utterances(self) -> None:
        block = MockSttBlock()
        ctx = _make_ctx()
        custom = ["A", "B", "C"]
        ctx.config = {"mode": "random", "utterances": custom}
        await _setup_block(block, ctx)
        event = Event(type=SPEECH_ENDED, session_id="s1", source="vad")
        out = await _capture_emits(block, ctx, event)
        assert out[0].payload["text"] in custom


# ---------------------------------------------------------------------------
# MockLlmBlock
# ---------------------------------------------------------------------------


class TestMockLlm:
    async def test_emits_text_delta_and_done(self) -> None:
        block = MockLlmBlock()
        ctx = _make_ctx()
        ctx.config = {"chunk_delay_ms": 0}  # 测试不等
        await _setup_block(block, ctx)
        event = Event(
            type=TRANSCRIPT_COMPLETED,
            session_id="s1",
            source="stt",
            payload={"text": "你好"},
        )
        out = await _capture_emits(block, ctx, event)
        types = [e.type for e in out]
        assert "llm.text.delta" in types
        assert "llm.text.done" in types
        # 最后一个是 done
        assert out[-1].type == "llm.text.done"
        # full_text 应非空
        assert out[-1].payload["full_text"]

    async def test_keyword_triggers_specific_reply(self) -> None:
        block = MockLlmBlock()
        ctx = _make_ctx()
        ctx.config = {"chunk_delay_ms": 0}
        await _setup_block(block, ctx)
        # "数字人" 关键词
        event = Event(
            type=TRANSCRIPT_COMPLETED,
            session_id="s1",
            source="stt",
            payload={"text": "请介绍数字人"},
        )
        out = await _capture_emits(block, ctx, event)
        done = next(e for e in out if e.type == "llm.text.done")
        assert "数字人" in done.payload["full_text"]


# ---------------------------------------------------------------------------
# MockTtsBlock
# ---------------------------------------------------------------------------


class TestMockTts:
    async def test_text_delta_produces_audio(self) -> None:
        block = MockTtsBlock()
        ctx = _make_ctx()
        ctx.config = {"ms_per_char": 30}  # 加快
        await _setup_block(block, ctx)
        delta_event = Event(
            type=LLM_TEXT_DELTA,
            session_id="s1",
            source="llm",
            payload={"text": "你好", "sentence_index": 0, "is_sentence_end": False},
        )
        out = await _capture_emits(block, ctx, delta_event)
        audio_deltas = [e for e in out if e.type == TTS_AUDIO_DELTA]
        assert len(audio_deltas) > 0
        # PCM base64 可解码
        b64 = audio_deltas[0].payload["pcm_b64"]
        raw = base64.b64decode(b64)
        assert len(raw) > 0
        assert audio_deltas[0].payload["sample_rate"] == 16000

    async def test_empty_text_does_not_emit(self) -> None:
        block = MockTtsBlock()
        ctx = _make_ctx()
        await _setup_block(block, ctx)
        event = Event(
            type=LLM_TEXT_DELTA,
            session_id="s1",
            source="llm",
            payload={"text": "", "is_sentence_end": True},
        )
        out = await _capture_emits(block, ctx, event)
        assert out == []


# ---------------------------------------------------------------------------
# MockAvatarBlock
# ---------------------------------------------------------------------------


class TestMockAvatar:
    async def test_tts_audio_delta_produces_speech_frame(self) -> None:
        block = MockAvatarBlock()
        ctx = _make_ctx()
        await _setup_block(block, ctx)
        event = Event(
            type=TTS_AUDIO_DELTA,
            session_id="s1",
            source="tts",
            payload={"pcm_b64": "AAAA", "samples": 100},
        )
        out = await _capture_emits(block, ctx, event)
        assert len(out) == 1
        assert out[0].type == "avatar.speech_frame"
        assert out[0].payload["is_speech"] is True

    async def test_frame_index_increments(self) -> None:
        block = MockAvatarBlock()
        ctx = _make_ctx()
        await _setup_block(block, ctx)
        event = Event(
            type=TTS_AUDIO_DELTA,
            session_id="s1",
            source="tts",
            payload={"pcm_b64": "AAAA", "samples": 100},
        )
        await _capture_emits(block, ctx, event)
        out2 = await _capture_emits(block, ctx, event)
        assert out2[0].payload["frame_index"] == 1
