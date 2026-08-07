"""Orchestrator 装配防护：fallback 链自指/成环必须快速失败（而非无限递归）。"""

from __future__ import annotations

import pytest
from avatarloom_sdk import BlockSetupError

from runtime.orchestrator import Orchestrator
from runtime.orchestrator.config import BlockRef, OrchestratorConfig


class TestFallbackCycleGuard:
    async def test_self_referencing_fallback_fails_fast(self) -> None:
        """id 不在注册表且 fallback 指向自己——BlockSetupError 成环，不递归爆栈。"""
        config = OrchestratorConfig(
            profile_id="test",
            blocks={
                "avatar": BlockRef(
                    id="avatar.nonexistent",
                    deployment="local",
                    fallback="avatar.nonexistent",
                ),
            },
        )
        orch = Orchestrator(config)
        with pytest.raises(BlockSetupError, match="成环"):
            await orch.setup()

    async def test_fallback_chain_cycle_fails_fast(self) -> None:
        """a -> b -> a 互指成环——同样快速失败。"""
        config = OrchestratorConfig(
            profile_id="test",
            blocks={
                "avatar": BlockRef(
                    id="avatar.missing-a",
                    deployment="local",
                    fallback="avatar.missing-b",
                ),
            },
        )
        # 手动构造互指：先让 a 的 fallback 是 b；b 不在注册表，其 block_ref 沿用 a 的
        # （同一 block_ref.fallback 会再指回 b —— 模拟 profile 误配场景）
        orch = Orchestrator(config)
        with pytest.raises(BlockSetupError):
            await orch.setup()

    async def test_normal_fallback_still_works(self) -> None:
        """正常 fallback 不受防护影响：不存在 → 降级到 avatar.mock。"""
        config = OrchestratorConfig(
            profile_id="test",
            blocks={
                "avatar": BlockRef(
                    id="avatar.nonexistent",
                    deployment="local",
                    fallback="avatar.mock",
                ),
            },
        )
        orch = Orchestrator(config)
        await orch.setup()
        assert orch.degraded_blocks.get("avatar") == "avatar.mock"
        assert "avatar" in orch.blocks
        await orch.shutdown()
