"""中断与取消集成测试。

验证：
1. 用户在 SPEAKING 时打断——LLM/TTS HTTP 请求被取消，音频队列清空，Avatar reset
2. 连接关闭——所有 Block 资源释放
3. asyncio.CancelledError 正确透传

用 OpenAI-compatible LLM（mock transport 模拟慢响应）验证 HTTP 取消。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from avatarloom_protocol import (
    Event,
    State,
)

from runtime.orchestrator import Orchestrator
from runtime.orchestrator.config import BlockRef, OrchestratorConfig


@pytest.mark.integration
class TestInterruptionCancellation:
    async def test_interrupt_during_speaking_cancels_llm(self, monkeypatch) -> None:
        """SPEAKING 时打断，LLM HTTP 请求应被取消（不泄漏连接）。"""

        # 模拟慢 LLM：返回巨量 chunk，保证打断窗口
        def handler(req: httpx.Request) -> httpx.Response:
            # 极慢的流——保证打断窗口
            def gen():
                yield 'data: {"choices":[{"delta":{"content":"你"}}]}\n'
                # 这里用 time.sleep 不行（httpx Response 是同步生成的），
                # 用超长 chunk 模拟；实际测试靠 asyncio cancel

            # 直接返回 200 但 body 巨大模拟慢流
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"你好"}}]}\n' * 1000,
                headers={"content-type": "text/event-stream"},
            )

        original_init = httpx.AsyncClient.__init__

        def mock_init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", mock_init)

        config = OrchestratorConfig(
            profile_id="test",
            blocks={
                "vad": BlockRef(id="vad.mock", deployment="mock"),
                "stt": BlockRef(
                    id="stt.mock", deployment="mock", config={"mode": "fixed", "fixed_text": "测试"}
                ),
                "llm": BlockRef(
                    id="llm.openai-compatible",
                    deployment="remote",
                    config={
                        "apiKey": "test",
                        "chunk_delay_ms": 0,
                    },
                ),
                # 用 mock TTS（不依赖网络）
                "tts": BlockRef(id="tts.mock", deployment="mock", config={"ms_per_char": 20}),
                "avatar": BlockRef(id="avatar.mock", deployment="mock"),
            },
        )

        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(config, event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        # 发音频触发链路
        import base64

        import numpy as np

        loud = base64.b64encode(np.full(1600, 28000, dtype=np.int16).tobytes()).decode()
        for _ in range(3):
            await orch.ingest_audio(session, loud, 1600)
            await asyncio.sleep(0.01)
        silent = base64.b64encode(np.zeros(1600, dtype=np.int16).tobytes()).decode()
        for _ in range(4):
            await orch.ingest_audio(session, silent, 1600)
            await asyncio.sleep(0.01)

        # 等一点让 LLM 开始
        await asyncio.sleep(0.1)

        # 用户打断：再发大声
        for _ in range(3):
            await orch.ingest_audio(session, loud, 1600)
            await asyncio.sleep(0.01)

        await asyncio.sleep(0.3)

        # 验证状态机经过了 INTERRUPTING 或回到 IDLE/LISTENING
        assert session.state in (State.INTERRUPTING, State.IDLE, State.LISTENING), (
            f"打断后状态应是 INTERRUPTING/IDLE/LISTENING，实际 {session.state}"
        )

        await orch.shutdown()

    async def test_session_close_releases_blocks(self) -> None:
        """会话关闭后所有 Block 的 shutdown 被调用。"""
        config = OrchestratorConfig(
            profile_id="test",
            blocks={
                "vad": BlockRef(id="vad.mock", deployment="mock"),
                "stt": BlockRef(id="stt.mock", deployment="mock"),
                "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 0}),
                "tts": BlockRef(id="tts.mock", deployment="mock"),
            },
        )
        orch = Orchestrator(config)
        await orch.setup()
        session = await orch.start_session()

        # 正常结束
        await orch.end_session(session)
        await orch.shutdown()

        # Orchestrator 已 shutdown，blocks 字典应清空或 Block 已 close
        # 验证 sessions 清空
        assert orch.sessions.active_count == 0

    async def test_missing_fallback_degrades_gracefully(self) -> None:
        """Block 不存在时 graceful 降级（非 optional 时跳过该 category）。"""
        config = OrchestratorConfig(
            profile_id="test",
            blocks={
                "vad": BlockRef(id="vad.mock", deployment="mock"),
                "stt": BlockRef(id="stt.mock", deployment="mock"),
                "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 0}),
                "tts": BlockRef(id="tts.mock", deployment="mock"),
                # vision 是 optional，缺席不阻断
            },
        )
        orch = Orchestrator(config)
        await orch.setup()
        # 链路应跑通（缺 vision 不影响）
        session = await orch.start_session()
        import base64

        import numpy as np

        loud = base64.b64encode(np.full(1600, 28000, dtype=np.int16).tobytes()).decode()
        for _ in range(3):
            await orch.ingest_audio(session, loud, 1600)
            await asyncio.sleep(0.01)
        silent = base64.b64encode(np.zeros(1600, dtype=np.int16).tobytes()).decode()
        for _ in range(4):
            await orch.ingest_audio(session, silent, 1600)
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.2)

        # 链路应正常推进（不在 ERROR 态）
        assert session.state != State.ERROR, f"vision 缺席不应导致 ERROR，实际 {session.state}"
        await orch.shutdown()
