"""Fixture Block 模块，专门给 create_block() 工厂测试用。

不放在 test_*.py 里，因为 create_block() 通过 importlib 加载，
需要稳定的模块路径。放在可 import 的 fixtures.blocks 包内。
"""

from __future__ import annotations

from avatarloom_protocol import SPEECH_DETECTED, Event
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability


class DummyVadBlock(Block):
    """可被 create_block() 加载的 VAD fixture。"""

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="vad.dummy",
            name="Dummy VAD",
            category="vad",
            capabilities=Capability(streaming=False),
            inputs=["audio.appended"],
            outputs=["speech.detected", "speech.ended"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        self._mark_ready()

    async def process(self, ctx: BlockContext, event: Event) -> None:
        await ctx.emit(
            Event(
                type=SPEECH_DETECTED,
                session_id=ctx.session_id,
                source="vad.dummy",
                payload={"confidence": 0.9},
            )
        )
