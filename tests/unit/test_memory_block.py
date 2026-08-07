"""Mem0 记忆 Block 单元测试（降级路径为主——真实抽取需 API key + bge-m3 模型，AutoDL 验）。"""

from __future__ import annotations

import pytest
from avatarloom_sdk import BlockContext


def _ctx(config: dict | None = None) -> BlockContext:
    ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
    ctx.config = config or {}
    return ctx


class TestBuildMemoryBlock:
    def test_empty_returns_empty(self) -> None:
        from blocks.memory.mem0_local import build_memory_block

        assert build_memory_block([]) == ""

    def test_formats_with_header_and_truncation(self) -> None:
        from blocks.memory.mem0_local import MAX_MEMORY_CHARS, build_memory_block

        block = build_memory_block(["喜欢喝美式咖啡", "x" * 200])
        assert block.startswith("# 关于用户的记忆")
        assert "- 喜欢喝美式咖啡" in block
        # 超长条目截到 MAX_MEMORY_CHARS
        assert ("x" * (MAX_MEMORY_CHARS + 1)) not in block
        assert ("x" * MAX_MEMORY_CHARS) in block


class TestMemoryBlockDegradation:
    async def test_disabled_by_default(self) -> None:
        from blocks.memory.mem0_local import Mem0MemoryBlock

        block = Mem0MemoryBlock()
        await block.setup(_ctx({}))
        assert block.active is False
        # recall/memorize 静默 no-op
        assert await block.recall("demo-assistant") == ""
        await block.memorize("你好", "你好呀", "demo-assistant")

    async def test_enabled_without_key_degrades(self, monkeypatch) -> None:
        from blocks.memory.mem0_local import Mem0MemoryBlock

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        block = Mem0MemoryBlock()
        await block.setup(_ctx({"enabled": True, "apiKeyEnv": "DEEPSEEK_API_KEY"}))
        assert block.active is False
        assert await block.recall("demo-assistant") == ""

    async def test_enabled_with_key_but_mem0_missing_degrades(self, monkeypatch) -> None:
        from blocks.memory.mem0_local import Mem0MemoryBlock

        monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-test")
        block = Mem0MemoryBlock()
        # 本环境未安装 mem0ai——ImportError 应降级为 active=False，不阻断
        await block.setup(_ctx({"enabled": True, "apiKeyEnv": "DEEPSEEK_API_KEY"}))
        assert block.active is False
        assert await block.recall("demo-assistant") == ""
        await block.memorize("你好", "你好呀", "demo-assistant")


class TestOrchestratorMemoryHooks:
    """orchestrator 挂钩：无 memory block 时 recall/memorize 静默；有替身时正确调用。"""

    async def test_hooks_noop_without_block(self) -> None:
        from runtime.orchestrator import Orchestrator
        from runtime.orchestrator.config import OrchestratorConfig

        orch = Orchestrator(OrchestratorConfig(profile_id="test", blocks={}))
        session = orch.sessions.create_session(profile_id="test")
        assert await orch._recall_memory(session) == ""
        await orch._memorize_turn("u", "a", "agent")  # 不抛

    async def test_recall_appends_to_instructions(self) -> None:
        from avatarloom_sdk import BlockContext
        from runtime.orchestrator import Orchestrator
        from runtime.orchestrator.config import OrchestratorConfig

        class _MemorySpy:
            active = True

            async def recall(self, agent_id: str) -> str:
                return f"# 记忆块({agent_id})"

            async def memorize(self, u: str, a: str, agent_id: str) -> None:
                self.last = (u, a, agent_id)

        orch = Orchestrator(OrchestratorConfig(profile_id="test", blocks={}))
        spy = _MemorySpy()
        orch.blocks["memory"] = spy  # type: ignore[assignment]
        session = orch.sessions.create_session(profile_id="test", persona_id="demo-assistant")
        session.set_emit_fn(orch._on_event)
        await session.start()
        orch._persona_contexts[session.session_id] = {"instructions": "你是小灵。"}

        block = await orch._recall_memory(session)
        assert block == "# 记忆块(demo-assistant)"
        # 模拟 start_session 的追加逻辑
        persona_ctx = orch._persona_contexts[session.session_id]
        persona_ctx["instructions"] += "\n\n" + block
        assert "你是小灵。" in persona_ctx["instructions"]
        assert "# 记忆块" in persona_ctx["instructions"]

        # memorize 凑对写入
        await orch._memorize_turn("你好", "你好呀", "demo-assistant")
        assert spy.last == ("你好", "你好呀", "demo-assistant")  # type: ignore[attr-defined]

    async def test_interrupted_run_not_memorized(self) -> None:
        from avatarloom_protocol import Event, LLM_TEXT_DONE
        from runtime.orchestrator import Orchestrator
        from runtime.orchestrator.config import OrchestratorConfig

        calls: list = []

        class _MemorySpy:
            active = True

            async def memorize(self, u, a, agent_id):
                calls.append((u, a))

        orch = Orchestrator(OrchestratorConfig(profile_id="test", blocks={}))
        orch.blocks["memory"] = _MemorySpy()  # type: ignore[assignment]
        session = orch.sessions.create_session(profile_id="test", persona_id="p1")
        orch._memory_pending_users[session.session_id] = "你好"

        await orch._on_llm_done_memory(
            Event(
                type=LLM_TEXT_DONE,
                session_id=session.session_id,
                source="llm",
                run_id="r1",
                payload={"full_text": "半截回复", "finish_reason": "interrupted"},
            )
        )
        assert calls == [], "被打断的回复不应写入记忆"
        # pending user 已清理
        assert session.session_id not in orch._memory_pending_users
