"""Block SDK 基类、Manifest、Context 契约测试。"""

from __future__ import annotations

import pytest
from avatarloom_protocol import (
    SPEECH_DETECTED,
    Event,
)
from avatarloom_sdk import (
    Block,
    BlockContext,
    BlockError,
    BlockManifest,
    BlockNotReadyError,
    BlockSetupError,
    Capability,
    create_block,
)

# ---------------------------------------------------------------------------
# 测试用 Block 实现
# ---------------------------------------------------------------------------


class _DummyVadBlock(Block):
    """测试用的最小 VAD Block 实现。"""

    received: list[Event] = []

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
        if not self.is_ready:
            raise BlockNotReadyError(self.manifest().block_id, "not ready")
        self.received.append(event)
        await ctx.emit(
            Event(
                type=SPEECH_DETECTED,
                session_id=ctx.session_id,
                source="vad.dummy",
                payload={"confidence": 0.9},
            )
        )


class _StreamingTestBlock(Block):
    """测试用流式 Block——用 process() 模拟流式（不再有 StreamingBlock 基类）。"""

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="tts.dummy",
            name="Dummy TTS",
            category="tts",
            capabilities=Capability(streaming=True),
            runtime_type="python_inproc",
        )

    async def setup(self, ctx: BlockContext) -> None:
        self._mark_ready()

    async def process(self, ctx: BlockContext, event: Event) -> None:
        pass


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class TestBlockManifest:
    def test_manifest_construction(self) -> None:
        m = _DummyVadBlock.manifest()
        assert m.block_id == "vad.dummy"
        assert m.category == "vad"
        assert m.capabilities.streaming is False
        assert "audio.appended" in m.inputs
        assert "speech.detected" in m.outputs

    def test_manifest_defaults(self) -> None:
        m = BlockManifest(block_id="x", name="X", category="vad")
        assert m.version == "0.1.0"
        assert m.runtime_type == "python_inproc"
        assert m.capabilities.streaming is False
        assert m.capabilities.languages == ["zh", "en"]

    def test_runtime_type_values(self) -> None:
        m = BlockManifest(
            block_id="x",
            name="X",
            category="vad",
            runtime_type="mock",
        )
        assert m.runtime_type == "mock"

    def test_resource_requirements_defaults(self) -> None:
        m = BlockManifest(block_id="x", name="X", category="vad")
        assert m.resources.accelerator == []
        assert m.resources.estimated_vram_mb == 0

    def test_capability_optional_flag(self) -> None:
        m = BlockManifest(
            block_id="vision.optional",
            name="Opt Vision",
            category="vision",
            capabilities=Capability(optional=True),
        )
        assert m.capabilities.optional is True


# ---------------------------------------------------------------------------
# Block 生命周期
# ---------------------------------------------------------------------------


class TestBlockLifecycle:
    async def test_setup_marks_ready(self) -> None:
        block = _DummyVadBlock()
        assert not block.is_ready
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        await block.setup(ctx)
        assert block.is_ready

    async def test_process_emits_event(self) -> None:
        block = _DummyVadBlock()
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        await block.setup(ctx)

        emitted: list[Event] = []

        async def capture(e: Event) -> None:
            emitted.append(e)

        ctx._emit_fn = capture  # type: ignore[attr-defined]
        # 清掉 logger cache 让新 emit_fn 生效
        ctx._logger = None  # type: ignore[attr-defined]

        await block.process(
            ctx,
            Event(type="audio.appended", session_id="s1", source="transport.ws"),
        )
        assert len(emitted) == 1
        assert emitted[0].type == "speech.detected"

    async def test_process_before_setup_raises(self) -> None:
        block = _DummyVadBlock()
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        with pytest.raises(BlockNotReadyError):
            await block.process(
                ctx,
                Event(type="audio.appended", session_id="s1", source="x"),
            )

    async def test_health_status(self) -> None:
        block = _DummyVadBlock()
        h = await block.health()
        assert h.status == "not_ready"
        assert h.block_id == "vad.dummy"

        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        await block.setup(ctx)
        h = await block.health()
        assert h.status == "healthy"

    async def test_reset_and_shutdown_default_implementations(self) -> None:
        """reset() 和 shutdown() 默认空实现不抛错。"""
        block = _DummyVadBlock()
        await block.reset("s1")
        await block.shutdown()

    async def test_warmup_default_is_noop(self) -> None:
        block = _DummyVadBlock()
        await block.warmup()  # 不抛错即可


# ---------------------------------------------------------------------------
# 流式 Block（用 Block + process() 模拟流式，无单独基类）
# ---------------------------------------------------------------------------


class TestStreamingBlock:
    async def test_streaming_block_process_after_setup(self) -> None:
        """流式 Block 继承 Block，通过 process() 处理流式事件。"""
        block = _StreamingTestBlock()
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        await block.setup(ctx)
        assert block.is_ready
        # process() 能处理流式 delta 事件不抛错即可
        await block.process(
            ctx,
            Event(type="llm.text.delta", session_id="s1", source="llm.x"),
        )

    def test_streaming_block_is_subclass_of_block(self) -> None:
        assert issubclass(_StreamingTestBlock, Block)


# ---------------------------------------------------------------------------
# Block factory
# ---------------------------------------------------------------------------


class TestCreateBlock:
    def test_create_block_by_entrypoint(self) -> None:
        block = create_block("tests.fixtures.blocks.dummy_vad:DummyVadBlock")
        assert isinstance(block, Block)
        assert block.manifest().block_id == "vad.dummy"

    def test_create_block_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid entrypoint"):
            create_block("no_colon_here")

    def test_create_block_missing_module_raises_setup_error(self) -> None:
        with pytest.raises(BlockSetupError, match="Failed to import"):
            create_block("nonexistent.module.xyz:Block")

    def test_create_block_missing_class_raises_setup_error(self) -> None:
        with pytest.raises(BlockSetupError, match="has no attribute"):
            create_block("tests.fixtures.blocks.dummy_vad:NonexistentClass")

    def test_create_block_non_block_class_raises(self) -> None:
        """entrypoint 指向非 Block 子类应被拒。"""
        # avatarloom_sdk.BlockManifest 不是 Block 子类
        with pytest.raises(BlockSetupError, match="not a Block subclass"):
            create_block("avatarloom_sdk:BlockManifest")


# ---------------------------------------------------------------------------
# BlockContext
# ---------------------------------------------------------------------------


class TestBlockContext:
    async def test_emit_without_emit_fn_raises(self) -> None:
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        with pytest.raises(RuntimeError, match="before Runtime wired"):
            await ctx.emit(Event(type="x", session_id="s1", source="b"))

    def test_logger_lazy_init(self) -> None:
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        log1 = ctx.logger
        log2 = ctx.logger
        assert log1 is log2  # 缓存复用

    def test_bind_logger(self) -> None:
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        ctx.bind_logger(custom="value")
        # 绑定后新 logger 有 context（间接验证：再次访问得到带 context 的 logger）
        assert ctx.logger is not None


# ---------------------------------------------------------------------------
# 异常体系
# ---------------------------------------------------------------------------


class TestBlockErrors:
    def test_block_error_carries_degradation_info(self) -> None:
        e = BlockError(
            "avatar.musetalk",
            "GPU OOM",
            degraded=True,
            fallback_block_id="avatar.static",
        )
        assert e.degraded is True
        assert e.fallback_block_id == "avatar.static"
        assert "avatar.musetalk" in str(e)

    def test_setup_error_is_block_error(self) -> None:
        assert issubclass(BlockSetupError, BlockError)

    def test_not_ready_error_is_block_error(self) -> None:
        assert issubclass(BlockNotReadyError, BlockError)
