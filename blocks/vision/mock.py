"""Mock Vision Block。

可缺席——不订阅时不阻断主链路。

被触发时（如收到 vision.request 或显式调用）emit vision.result，
返回 Mock 视觉描述。

v0.1 Mock Vision 演示"可选模块"协议：
- 不在主链路（不订阅 audio/transcript/llm/tts/avatar 任何事件）
- 通过 Control API 显式触发（截帧打分场景）
"""

from __future__ import annotations

from avatarloom_protocol import VISION_RESULT, Event
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability


class MockVisionBlock(Block):
    """Mock 视觉感知。"""

    _descriptions: list[str] = [
        "我看到了一个模糊的画面。",
        "画面里似乎有人。",
        "光线条件一般。",
    ]

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="vision.mock",
            name="Mock Vision",
            category="vision",
            runtime_type="mock",
            capabilities=Capability(optional=True),
            inputs=[],  # 不订阅主链路事件
            outputs=[VISION_RESULT],
            config_schema={"type": "object"},
        )

    async def setup(self, ctx: BlockContext) -> None:
        self._mark_ready()
        await ctx.logger.ainfo("vision.mock ready (optional block)")

    async def process(self, ctx: BlockContext, event: Event) -> None:
        # v0.1 不订阅主链路事件；这里处理外部触发
        # 实际触发通过 Orchestrator 显式调用 describe_frame()
        pass

    async def describe_frame(self, ctx: BlockContext) -> Event:
        """显式触发：返回 Mock 视觉描述。"""
        import random

        desc = random.choice(self._descriptions)
        event = Event(
            type=VISION_RESULT,
            session_id=ctx.session_id,
            source="vision.mock",
            run_id=ctx.run_id,
            payload={"description": desc, "objects": [], "confidence": 0.5},
        )
        await ctx.emit(event)
        return event
