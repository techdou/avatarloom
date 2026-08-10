"""运行时生命周期与 GPU 资源管理测试。

覆盖：
1. FlashHead/MuseTalk shutdown 自取消 reader/task 不再误抛 CancelledError；
   外部取消（loop teardown）仍正确透传
2. Orchestrator.shutdown 逐 block 隔离异常/超时/自取消泄漏，后续资源继续清理
3. ws_handler 单会话锁：check+占位原子化、shutdown 完成后才释放、setup 失败回收
4. qwen3/silero/sensevoice shutdown 释放模型（无 torch 环境安全降级）
5. SenseVoice/MuseTalk 实例级状态隔离
6. 模型推理 offload 到线程（不阻塞事件循环）
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from contextlib import suppress

import numpy as np
import pytest
from avatarloom_protocol import (
    AUDIO_APPENDED,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest

import runtime.orchestrator.orchestrator as orch_mod
from runtime.orchestrator.config import OrchestratorConfig
from runtime.orchestrator.orchestrator import Orchestrator


def _ctx(session_id: str = "s1", run_id: str | None = "r1") -> BlockContext:
    return BlockContext(session_id=session_id, run_id=run_id, workspace_root=".")


def _capture(ctx: BlockContext, sink: list[Event]) -> BlockContext:
    async def cap(e: Event) -> None:
        sink.append(e)

    ctx._emit_fn = cap  # type: ignore[attr-defined]
    return ctx


async def _sleep_task() -> None:
    await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# 1. Avatar block 自取消 shutdown
# ---------------------------------------------------------------------------


class TestAvatarSelfCancelShutdown:
    async def test_flashhead_shutdown_swallows_self_cancel(self) -> None:
        """reader task 是 block 自己 cancel 的——shutdown 不应向外抛 CancelledError。"""
        from blocks.avatar.flashhead import FlashHeadAvatarBlock

        block = FlashHeadAvatarBlock()
        block._reader_task = asyncio.create_task(_sleep_task())
        block._ws = None
        block._proc = None

        # 修复前：await reader 的 CancelledError 被透传，ws cleanup/orchestrator 全被炸断
        await asyncio.wait_for(block.shutdown(), timeout=2)
        assert block._reader_task is None

    async def test_flashhead_external_cancel_still_propagates(self) -> None:
        """shutdown 任务自身被外部取消时仍须透传——否则 asyncio.run teardown 挂起。"""

        async def stubborn() -> None:
            # 吞掉第一次取消（模拟顽固 reader），给外部取消留窗口。
            with suppress(asyncio.CancelledError):
                await asyncio.sleep(60)
            await asyncio.sleep(60)  # 第二次取消正常抛出

        from blocks.avatar.flashhead import FlashHeadAvatarBlock

        block = FlashHeadAvatarBlock()
        reader = asyncio.create_task(stubborn())
        block._reader_task = reader
        block._ws = None
        block._proc = None

        shutdown_task = asyncio.create_task(block.shutdown())
        await asyncio.sleep(0.1)  # shutdown 已 cancel reader 并卡在 await（reader 顽固续睡）
        shutdown_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shutdown_task
        assert shutdown_task.cancelled()

        # 收尾：第二次 cancel 让顽固 reader 正常消亡
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader

    async def test_musetalk_shutdown_swallows_self_cancel_and_clears_state(self) -> None:
        """MuseTalk：自取消 task 列表不炸 shutdown，且会话态全部清空。"""
        from blocks.avatar.musetalk import MuseTalkAvatarBlock

        block = MuseTalkAvatarBlock()
        t1 = asyncio.create_task(_sleep_task())
        t2 = asyncio.create_task(_sleep_task())
        block._tasks.extend([t1, t2])
        block._render_tasks["s1"] = t1
        block._bufs["s1"] = bytearray(b"\x00\x01")
        block._last_activity["s1"] = 1.0
        block._frame_indexes["s1"] = 7
        block._worker_lines.append("{}")
        block._worker_proc = None

        await asyncio.wait_for(block.shutdown(), timeout=2)
        assert t1.done() and t2.done()
        assert block._tasks == []
        assert block._render_tasks == {}
        assert block._bufs == {}
        assert block._last_activity == {}
        assert block._frame_indexes == {}
        assert len(block._worker_lines) == 0


# ---------------------------------------------------------------------------
# 2. Orchestrator.shutdown 逐 block 隔离
# ---------------------------------------------------------------------------


class _StubBlock(Block):
    """行为可控的假 Block。"""

    _behavior = "ok"

    def __init__(self) -> None:
        super().__init__()
        self.shutdown_called = False

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id=f"fake.{cls._behavior}", name="fake", category="vad"
        )

    async def setup(self, ctx: BlockContext) -> None:
        pass

    async def process(self, ctx: BlockContext, event: Event) -> None:
        pass

    async def shutdown(self) -> None:
        self.shutdown_called = True
        if self._behavior == "raise":
            raise RuntimeError("boom")
        if self._behavior == "slow":
            await asyncio.sleep(60)
        if self._behavior == "spurious_cancel":
            # 内部任务自取消未吞，泄漏到 shutdown（回归防御：不得扩散）
            raise asyncio.CancelledError()


class _RaiseBlock(_StubBlock):
    _behavior = "raise"


class _SlowBlock(_StubBlock):
    _behavior = "slow"


class _SpuriousCancelBlock(_StubBlock):
    _behavior = "spurious_cancel"


class _OkBlock(_StubBlock):
    _behavior = "ok"


class TestOrchestratorShutdownIsolation:
    async def test_block_failures_do_not_stop_remaining_cleanup(
        self, monkeypatch
    ) -> None:
        """异常/超时/自取消泄漏全隔离——健康 block 与 EventBus 照常清理。"""
        monkeypatch.setattr(orch_mod, "_BLOCK_SHUTDOWN_TIMEOUT_S", 0.3)
        orch = Orchestrator(OrchestratorConfig(profile_id="t"))
        bad, slow, bug, good = (
            _RaiseBlock(),
            _SlowBlock(),
            _SpuriousCancelBlock(),
            _OkBlock(),
        )
        orch.blocks = {"a": bad, "b": slow, "c": bug, "d": good}

        t0 = time.monotonic()
        await asyncio.wait_for(orch.shutdown(), timeout=10)
        elapsed = time.monotonic() - t0

        assert bad.shutdown_called
        assert slow.shutdown_called  # 已启动但被 0.3s 超时截断
        assert bug.shutdown_called
        assert good.shutdown_called, "前序 block 失败不得跳过健康 block 的清理"
        assert elapsed < 5, f"slow block 未被超时截断，耗时 {elapsed:.1f}s"

    async def test_external_cancel_during_shutdown_propagates(self, monkeypatch) -> None:
        """shutdown 任务自身被取消（loop teardown）——透传，不吞。"""
        monkeypatch.setattr(orch_mod, "_BLOCK_SHUTDOWN_TIMEOUT_S", 30.0)
        orch = Orchestrator(OrchestratorConfig(profile_id="t"))
        orch.blocks = {"slow": _SlowBlock()}

        shutdown_task = asyncio.create_task(orch.shutdown())
        await asyncio.sleep(0.1)  # 卡在 slow block 的 wait_for 里
        shutdown_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shutdown_task


# ---------------------------------------------------------------------------
# 3. ws_handler 单会话锁
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_ws_session_globals():
    """每个用例前后复位进程级单会话锁状态。"""
    import avatarloom_runtime_gateway.ws_handler as wh

    wh._active_orchestrator = None
    wh._orchestrator_starting = False
    yield
    wh._active_orchestrator = None
    wh._orchestrator_starting = False


def _make_ws_session(tmp_path):
    from avatarloom_runtime_gateway.config import Settings
    from avatarloom_runtime_gateway.ws_handler import WebSocketSession

    settings = Settings(
        workspace_root=str(tmp_path),
        artifacts_root=str(tmp_path / "artifacts"),
        runs_root=str(tmp_path / "runs"),
        default_profile="mock",
    )
    return WebSocketSession(ws=None, settings=settings)  # type: ignore[arg-type]


def _drain_control(ws_session) -> list[dict]:
    msgs = []
    while True:
        try:
            msgs.append(ws_session.bridge._control_queue.get_nowait())
        except asyncio.QueueEmpty:
            return msgs


class TestSingleSessionLock:
    async def test_concurrent_start_only_one_wins(self, tmp_path) -> None:
        """并发 session.start：占位原子化——只能活一个，另一个收到拒绝。"""
        import avatarloom_runtime_gateway.ws_handler as wh

        s1 = _make_ws_session(tmp_path)
        s2 = _make_ws_session(tmp_path)

        t1 = asyncio.create_task(s1._start_session({"profile_id": "mock"}))
        await asyncio.sleep(0.05)  # s1 占位并进入 setup
        await s2._start_session({"profile_id": "mock"})
        await t1

        winners = [s for s in (s1, s2) if s.session is not None]
        losers = [s for s in (s1, s2) if s.session is None]
        assert len(winners) == 1 and len(losers) == 1
        loser_msgs = _drain_control(losers[0])
        assert any(m["type"] == "error" for m in loser_msgs), loser_msgs
        assert wh._active_orchestrator is winners[0].orchestrator

        await winners[0].cleanup()
        assert wh._active_orchestrator is None

    async def test_setup_failure_recovers_lock_and_retry_succeeds(
        self, tmp_path, monkeypatch
    ) -> None:
        """setup 失败：回收占位 + 部分装配资源，锁可重入，重试成功。"""
        import avatarloom_runtime_gateway.ws_handler as wh

        calls = {"fail": True}
        original_setup = Orchestrator.setup

        async def maybe_fail(self: Orchestrator) -> None:
            if calls["fail"]:
                raise RuntimeError("simulated setup boom")
            return await original_setup(self)

        monkeypatch.setattr(Orchestrator, "setup", maybe_fail)

        s1 = _make_ws_session(tmp_path)
        await s1._start_session({"profile_id": "mock"})
        assert s1.session is None
        assert any(m["type"] == "error" for m in _drain_control(s1))
        # 失败回收：占位与活跃锁都已释放
        assert wh._active_orchestrator is None
        assert wh._orchestrator_starting is False

        # 重试成功（锁未被失败卡死）
        calls["fail"] = False
        s2 = _make_ws_session(tmp_path)
        await s2._start_session({"profile_id": "mock"})
        assert s2.session is not None
        assert wh._active_orchestrator is s2.orchestrator
        await s2.cleanup()

    async def test_lock_released_only_after_shutdown_completes(
        self, tmp_path, monkeypatch
    ) -> None:
        """单会话锁在 orchestrator.shutdown 完成后才释放（防 VRAM 未清并发加载）。"""
        import avatarloom_runtime_gateway.ws_handler as wh

        s1 = _make_ws_session(tmp_path)
        await s1._start_session({"profile_id": "mock"})
        orch = s1.orchestrator
        assert wh._active_orchestrator is orch

        gate = asyncio.Event()
        original_shutdown = orch.shutdown

        async def gated_shutdown() -> None:
            await gate.wait()
            await original_shutdown()

        monkeypatch.setattr(orch, "shutdown", gated_shutdown)

        cleanup_task = asyncio.create_task(s1.cleanup())
        await asyncio.sleep(0.1)
        # shutdown 被 gate 卡住期间，锁必须仍持有
        assert wh._active_orchestrator is orch
        assert not cleanup_task.done()

        gate.set()
        await asyncio.wait_for(cleanup_task, timeout=5)
        assert wh._active_orchestrator is None


# ---------------------------------------------------------------------------
# 4/5/6. Block shutdown、实例状态隔离、推理 offload
# ---------------------------------------------------------------------------


class TestBlockShutdown:
    async def test_qwen3_shutdown_releases_model_without_torch(self) -> None:
        """qwen3 shutdown：清模型/缓存/运行态；无 torch 环境不抛 ImportError。"""
        from blocks.tts.qwen3 import Qwen3TtsBlock

        block = Qwen3TtsBlock()
        block._model = object()
        block._tokenizer = object()
        block._sentence_buffers = {0: "残留"}
        block._cancelled_run_ids.add("r0")

        await asyncio.wait_for(block.shutdown(), timeout=5)
        assert block._model is None
        assert block._tokenizer is None
        assert block._sentence_buffers == {}
        assert block._cancelled_run_ids == set()

    async def test_silero_shutdown_releases_model_without_torch(self) -> None:
        """silero shutdown：清模型/hidden state；无 torch 环境不抛。"""
        from blocks.vad.silero import SileroVadBlock

        block = SileroVadBlock()
        block._model = object()
        block._h = object()
        block._is_speaking = True

        await asyncio.wait_for(block.shutdown(), timeout=5)
        assert block._model is None
        assert block._h is None
        assert block._is_speaking is False

    async def test_sensevoice_shutdown_clears_model_and_buffers(self) -> None:
        """sensevoice shutdown：清模型 + 会话音频缓冲；无 torch 环境不抛。"""
        from blocks.stt.sensevoice import SenseVoiceSttBlock

        block = SenseVoiceSttBlock()
        block._model = object()
        block._audio_buffers["s1"] = bytearray(b"\x00" * 64)

        await asyncio.wait_for(block.shutdown(), timeout=5)
        assert block._model is None
        assert block._audio_buffers == {}

    async def test_shutdown_idempotent(self) -> None:
        """二次 shutdown 安全（ws cleanup 与 fallback 重建可能重复触发）。"""
        from blocks.stt.sensevoice import SenseVoiceSttBlock
        from blocks.tts.qwen3 import Qwen3TtsBlock
        from blocks.vad.silero import SileroVadBlock

        for cls in (SenseVoiceSttBlock, Qwen3TtsBlock, SileroVadBlock):
            block = cls()
            await block.shutdown()
            await block.shutdown()


class TestInstanceStateIsolation:
    def test_sensevoice_buffers_are_instance_level(self) -> None:
        from blocks.stt.sensevoice import SenseVoiceSttBlock

        b1, b2 = SenseVoiceSttBlock(), SenseVoiceSttBlock()
        assert b1._audio_buffers is not b2._audio_buffers
        b1._audio_buffers["s1"] = bytearray(b"x")
        assert b2._audio_buffers == {}

    def test_musetalk_state_is_instance_level(self) -> None:
        from blocks.avatar.musetalk import MuseTalkAvatarBlock

        b1, b2 = MuseTalkAvatarBlock(), MuseTalkAvatarBlock()
        assert b1._tasks is not b2._tasks
        assert b1._bufs is not b2._bufs
        assert b1._render_tasks is not b2._render_tasks
        assert b1._worker_lines is not b2._worker_lines

    def test_qwen3_sentence_buffers_is_instance_level(self) -> None:
        """qwen3 的可变状态是实例级，不跨实例共享（防类属性串扰回归）。"""
        from blocks.tts.qwen3 import Qwen3TtsBlock

        b1, b2 = Qwen3TtsBlock(), Qwen3TtsBlock()
        assert b1._sentence_buffers is not b2._sentence_buffers


class TestInferenceOffload:
    """模型推理必须跑在 worker 线程（asyncio.to_thread），不阻塞事件循环。"""

    async def test_sensevoice_transcribe_offloads_infer(self, monkeypatch) -> None:
        from blocks.stt.sensevoice import SenseVoiceSttBlock

        block = SenseVoiceSttBlock()
        block._audio_buffers["s1"] = bytearray(b"\x00\x00" * 160)
        main_ident = threading.get_ident()
        seen: dict[str, int] = {}

        def fake_infer(wav_bytes: bytes):
            seen["ident"] = threading.get_ident()
            return ("你好", {"language": "zh"})

        monkeypatch.setattr(block, "_infer", fake_infer)

        emitted: list[Event] = []
        ctx = _capture(_ctx(), emitted)
        await block._transcribe(
            ctx,
            Event(type=SPEECH_ENDED, session_id="s1", source="test", run_id="r1", payload={}),
        )
        assert seen["ident"] != main_ident, "推理仍在事件循环线程上跑"
        assert any(
            e.type == TRANSCRIPT_COMPLETED and e.payload["text"] == "你好"
            for e in emitted
        )

    async def test_qwen3_synthesize_offloads_infer(self, monkeypatch) -> None:
        from blocks.tts.qwen3 import Qwen3TtsBlock

        block = Qwen3TtsBlock()
        main_ident = threading.get_ident()
        seen: dict[str, int] = {}

        def fake_infer_stream(text: str, voice_ref):
            seen["ident"] = threading.get_ident()
            return [np.zeros(2400, dtype=np.float32).tobytes()]

        monkeypatch.setattr(block, "_infer_stream", fake_infer_stream)

        emitted: list[Event] = []
        ctx = _capture(_ctx(), emitted)
        await block._synthesize(ctx, "你好")
        assert seen["ident"] != main_ident, "TTS 推理仍在事件循环线程上跑"
        assert any(e.type == TTS_AUDIO_DELTA for e in emitted)

    async def test_silero_process_offloads_infer(self, monkeypatch) -> None:
        from blocks.vad.silero import SileroVadBlock

        block = SileroVadBlock()
        block._threshold = 0.5
        block._min_silence_samples = 8000
        main_ident = threading.get_ident()
        seen: dict[str, int] = {}

        def fake_infer(chunk, h):
            seen["ident"] = threading.get_ident()
            return (0.9, None)

        monkeypatch.setattr(block, "_infer", fake_infer)

        pcm = np.zeros(512, dtype=np.int16).tobytes()  # 恰好 1 个 chunk
        emitted: list[Event] = []
        ctx = _capture(_ctx(), emitted)
        await block.process(
            ctx,
            Event(
                type=AUDIO_APPENDED,
                session_id="s1",
                source="test",
                run_id="r1",
                payload={"pcm_b64": base64.b64encode(pcm).decode("ascii")},
            ),
        )
        assert seen["ident"] != main_ident, "VAD 推理仍在事件循环线程上跑"
        assert any(e.type == SPEECH_DETECTED for e in emitted)
