"""协作式打断（AL-P1-006 / AL-P2-003）单元测试。

验证：
1. LLM process 进行中 reset() → HTTP 流停止、发 finish_reason=interrupted 的 done、
   旧 run 的迟到 request 被丢弃（不再产生新 delta）
2. TTS _sync_run_state：run 变化清零计数；cancelled run 的事件被丢弃、不 emit completed
3. TTS 正常完成一轮后，下一轮 total_samples 从零开始（不跨 run 累计）
"""

from __future__ import annotations

import asyncio
import json

import httpx
from avatarloom_protocol import (
    LLM_REQUEST,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TTS_AUDIO_COMPLETED,
    Event,
)
from avatarloom_sdk import BlockContext


def _ctx(run_id: str | None, session_id: str = "s1") -> BlockContext:
    return BlockContext(session_id=session_id, run_id=run_id, workspace_root=".")


def _patch_httpx(monkeypatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def mock_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", mock_init)


class _SlowSseStream(httpx.AsyncByteStream):
    """可控慢速 SSE 字节流——每行真挂起，给 reset() 留出打断窗口。"""

    def __init__(self, lines: int, delay_s: float = 0.001) -> None:
        self._lines = lines
        self._delay = delay_s

    async def __aiter__(self):
        for _ in range(self._lines):
            yield b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
            await asyncio.sleep(self._delay)

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# LLM 协作式取消（AL-P1-006）
# ---------------------------------------------------------------------------


class TestLlmCooperativeCancel:
    async def test_reset_stops_stream_and_marks_interrupted(self, monkeypatch) -> None:
        from blocks.llm.openai_compatible import OpenAILlmBlock

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                stream=_SlowSseStream(lines=1000, delay_s=0.001),
                headers={"content-type": "text/event-stream"},
            )

        _patch_httpx(monkeypatch, handler)

        block = OpenAILlmBlock()
        ctx = _ctx("r1")
        ctx.config = {"apiKey": "test", "timeoutS": 30}
        await block.setup(ctx)

        emitted: list[Event] = []

        async def cap(e: Event) -> None:
            emitted.append(e)

        ctx._emit_fn = cap  # type: ignore[attr-defined]

        event = Event(
            type=LLM_REQUEST,
            session_id="s1",
            source="test",
            run_id="r1",
            payload={"text": "你好"},
        )
        task = asyncio.create_task(block.process(ctx, event))
        # 等流开始（1000 行 × 1ms = 1s 全长，50ms 处打断约消费几十行）
        await asyncio.sleep(0.05)
        await block.reset("s1")
        await asyncio.wait_for(task, timeout=5)

        deltas = [e for e in emitted if e.type == LLM_TEXT_DELTA]
        dones = [e for e in emitted if e.type == LLM_TEXT_DONE]
        # 流被截断：远少于全量 1000 行
        assert 0 < len(deltas) < 500, f"打断后仍产出 {len(deltas)} 个 delta"
        assert dones, "应有收尾 done"
        assert dones[-1].payload.get("finish_reason") == "interrupted"

        # 打断后旧 run 的迟到 request 被直接丢弃
        emitted.clear()
        await block.process(ctx, event)
        assert emitted == [], "旧 run 的迟到 request 不应产生任何事件"

    async def test_new_run_after_interrupt_works(self, monkeypatch) -> None:
        """打断旧 run 后，新 run（不同 run_id）不受影响，正常生成。"""
        from blocks.llm.openai_compatible import OpenAILlmBlock

        chunks = [
            {"choices": [{"delta": {"content": "好"}}]},
        ]
        lines = [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text="\n".join(lines), headers={"content-type": "text/event-stream"}
            )

        _patch_httpx(monkeypatch, handler)

        block = OpenAILlmBlock()
        ctx_old = _ctx("r1")
        ctx_old.config = {"apiKey": "test", "timeoutS": 30}
        await block.setup(ctx_old)
        # 打断 r1（无活跃流——只标记）
        block._active_run_id = "r1"
        await block.reset("s1")

        emitted: list[Event] = []
        ctx_new = _ctx("r2")
        ctx_new.config = {"apiKey": "test", "timeoutS": 30}

        async def cap(e: Event) -> None:
            emitted.append(e)

        ctx_new._emit_fn = cap  # type: ignore[attr-defined]
        await block.process(
            ctx_new,
            Event(
                type=LLM_REQUEST,
                session_id="s1",
                source="test",
                run_id="r2",
                payload={"text": "继续"},
            ),
        )
        dones = [e for e in emitted if e.type == LLM_TEXT_DONE]
        assert dones and dones[-1].payload.get("finish_reason") == "stop"


# ---------------------------------------------------------------------------
# TTS 按 run 隔离与打断丢弃（AL-P2-003 / AL-P1-006）
# ---------------------------------------------------------------------------


class TestTtsRunStateIsolation:
    async def test_run_change_resets_counters(self) -> None:
        from blocks.tts.openai_compatible import OpenAITtsBlock

        block = OpenAITtsBlock()
        ctx = _ctx("r1")
        ctx.config = {"apiKey": "test"}
        await block.setup(ctx)

        block._total_samples = 12345
        block._sentence_buffers = {0: "残留"}

        # 新 run → 计数与缓冲清零，且不视为已打断
        ctx2 = _ctx("r2")
        assert block._sync_run_state(ctx2) is False
        assert block._total_samples == 0
        assert block._sentence_buffers == {}

    async def test_cancelled_run_events_dropped(self) -> None:
        from blocks.tts.openai_compatible import OpenAITtsBlock

        block = OpenAITtsBlock()
        ctx = _ctx("r1")
        ctx.config = {"apiKey": "test"}
        await block.setup(ctx)
        block._sync_run_state(ctx)  # 登记 r1
        await block.reset("s1")  # 打断 r1

        emitted: list[Event] = []

        async def cap(e: Event) -> None:
            emitted.append(e)

        ctx._emit_fn = cap  # type: ignore[attr-defined]
        # 被打断 run 的 LLM_TEXT_DONE 不应 emit TTS_AUDIO_COMPLETED
        await block.process(
            ctx,
            Event(
                type=LLM_TEXT_DONE,
                session_id="s1",
                source="test",
                run_id="r1",
                payload={"full_text": "旧回复"},
            ),
        )
        assert not any(e.type == TTS_AUDIO_COMPLETED for e in emitted)

        # 新 run 不受影响
        ctx3 = _ctx("r3")
        ctx3._emit_fn = cap  # type: ignore[attr-defined]
        await block.process(
            ctx3,
            Event(
                type=LLM_TEXT_DONE,
                session_id="s1",
                source="test",
                run_id="r3",
                payload={"full_text": "新回复"},
            ),
        )
        assert any(e.type == TTS_AUDIO_COMPLETED and e.run_id == "r3" for e in emitted)
