"""OpenAI-compatible Adapter 单元测试。

用 httpx.MockTransport 模拟 OpenAI 响应，不依赖真实 API Key。
"""

from __future__ import annotations

import base64
import json

import httpx
import numpy as np
import pytest
from avatarloom_protocol import (
    AUDIO_APPENDED,
    LLM_REQUEST,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import BlockContext


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


def _patch_httpx(monkeypatch, handler):
    """把 httpx.AsyncClient 的 transport 替换为 MockTransport。"""
    original_init = httpx.AsyncClient.__init__

    def mock_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", mock_init)


# ---------------------------------------------------------------------------
# OpenAI LLM
# ---------------------------------------------------------------------------


class TestOpenAILlm:
    async def test_streaming_emits_delta_and_done(self, monkeypatch) -> None:
        from blocks.llm.openai_compatible import OpenAILlmBlock

        def handler(req: httpx.Request) -> httpx.Response:
            # 模拟 SSE 流
            chunks = [
                {"choices": [{"delta": {"content": "你好"}}]},
                {"choices": [{"delta": {"content": "，我是"}}]},
                {"choices": [{"delta": {"content": "助手。"}}]},
            ]
            lines = [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]
            return httpx.Response(
                200, text="\n".join(lines), headers={"content-type": "text/event-stream"}
            )

        _patch_httpx(monkeypatch, handler)

        block = OpenAILlmBlock()
        ctx = _make_ctx()
        ctx.config = {"apiKey": "test-key"}
        await _setup_block(block, ctx)

        event = Event(
            type=LLM_REQUEST, session_id="s1", source="orchestrator", payload={"text": "你好"}
        )
        out = await _capture_emits(block, ctx, event)

        types = [e.type for e in out]
        assert LLM_TEXT_DELTA in types
        assert LLM_TEXT_DONE in types
        done = next((e for e in out if e.type == LLM_TEXT_DONE), None)
        assert done is not None
        assert "你好" in done.payload["full_text"]
        assert "助手" in done.payload["full_text"]

    async def test_http_error_handled(self, monkeypatch) -> None:
        from blocks.llm.openai_compatible import OpenAILlmBlock

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text='{"error": "invalid api key"}')

        _patch_httpx(monkeypatch, handler)

        block = OpenAILlmBlock()
        ctx = _make_ctx()
        ctx.config = {"apiKey": "bad-key"}
        await _setup_block(block, ctx)

        event = Event(
            type=LLM_REQUEST, session_id="s1", source="orchestrator", payload={"text": "hi"}
        )
        with pytest.raises(RuntimeError, match=r"HTTP error 401"):
            await _capture_emits(block, ctx, event)

    async def test_empty_user_text_skipped(self, monkeypatch) -> None:
        from blocks.llm.openai_compatible import OpenAILlmBlock

        called = [False]

        def handler(req: httpx.Request) -> httpx.Response:
            called[0] = True
            return httpx.Response(200, text="data: [DONE]")

        _patch_httpx(monkeypatch, handler)
        block = OpenAILlmBlock()
        ctx = _make_ctx()
        ctx.config = {"apiKey": "x"}
        await _setup_block(block, ctx)

        event = Event(
            type=LLM_REQUEST, session_id="s1", source="orchestrator", payload={"text": ""}
        )
        out = await _capture_emits(block, ctx, event)
        assert out == []
        assert called[0] is False


# ---------------------------------------------------------------------------
# OpenAI STT
# ---------------------------------------------------------------------------


class TestOpenAIStt:
    async def test_speech_ended_triggers_transcription(self, monkeypatch) -> None:
        from blocks.stt.openai_compatible import OpenAISttBlock

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"text": "你好世界"})

        _patch_httpx(monkeypatch, handler)

        block = OpenAISttBlock()
        ctx = _make_ctx()
        ctx.config = {"apiKey": "x"}
        await _setup_block(block, ctx)

        # 先喂音频
        audio_event = Event(
            type=AUDIO_APPENDED,
            session_id="s1",
            source="ws",
            payload={"pcm_b64": base64.b64encode(b"\x00\x00" * 100).decode(), "samples": 100},
        )
        await _capture_emits(block, ctx, audio_event)
        # 再触发 speech.ended
        end_event = Event(type=SPEECH_ENDED, session_id="s1", source="vad")
        out = await _capture_emits(block, ctx, end_event)

        assert len(out) == 1
        assert out[0].type == TRANSCRIPT_COMPLETED
        assert out[0].payload["text"] == "你好世界"

    async def test_reset_clears_audio_buffer(self, monkeypatch) -> None:
        from blocks.stt.openai_compatible import OpenAISttBlock

        block = OpenAISttBlock()
        ctx = _make_ctx()
        ctx.config = {"apiKey": "x"}
        await _setup_block(block, ctx)
        block._audio_buffers["s1"] = bytearray(b"abc")
        await block.reset("s1")
        assert "s1" not in block._audio_buffers


# ---------------------------------------------------------------------------
# OpenAI TTS
# ---------------------------------------------------------------------------


class TestOpenAITts:
    async def test_sentence_end_triggers_synthesis(self, monkeypatch) -> None:
        from blocks.tts.openai_compatible import OpenAITtsBlock

        # 造 24kHz float32 PCM
        samples = (np.sin(np.linspace(0, 10, 2400)) * 0.5).astype(np.float32)
        pcm = samples.tobytes()

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=pcm)

        _patch_httpx(monkeypatch, handler)

        block = OpenAITtsBlock()
        ctx = _make_ctx()
        ctx.config = {"apiKey": "x"}
        await _setup_block(block, ctx)

        # 喂一个句末 delta
        event = Event(
            type=LLM_TEXT_DELTA,
            session_id="s1",
            source="llm",
            payload={"text": "你好", "sentence_index": 0, "is_sentence_end": True},
        )
        out = await _capture_emits(block, ctx, event)

        # 应产生 audio delta（可能多个 chunk）
        audio_deltas = [e for e in out if e.type == TTS_AUDIO_DELTA]
        assert len(audio_deltas) > 0
        # PCM 可解码
        raw = base64.b64decode(audio_deltas[0].payload["pcm_b64"])
        assert len(raw) > 0
        assert audio_deltas[0].payload["sample_rate"] == 16000

    async def test_no_sentence_end_no_audio(self, monkeypatch) -> None:
        from blocks.tts.openai_compatible import OpenAITtsBlock

        block = OpenAITtsBlock()
        ctx = _make_ctx()
        ctx.config = {"apiKey": "x"}
        await _setup_block(block, ctx)

        event = Event(
            type=LLM_TEXT_DELTA,
            session_id="s1",
            source="llm",
            payload={"text": "你", "is_sentence_end": False},
        )
        out = await _capture_emits(block, ctx, event)
        assert out == []
