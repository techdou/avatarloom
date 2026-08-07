"""Vision 链路测试（AL-P1-002 同轮编排后）：

覆盖：
1. 触发词（"看看我"）命中 → VISION_REQUEST（带 request_id）
2. 普通对话 → 直接 llm.request，不触发 Vision
3. 同轮闭环：触发词 → 截帧上行 → LLM 同轮即拿到 vision_description
4. Vision 超时 → 降级：llm.request 仍发出，无视觉注入
5. 浏览器截帧失败（handle_vision_frame_error）→ 立即降级
6. 单次消费：视觉描述注入一次后，再下一轮不再注入
"""

from __future__ import annotations

import asyncio
import base64

import pytest
from avatarloom_protocol import (
    AUDIO_APPENDED,
    LLM_REQUEST,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    VISION_REQUEST,
    Event,
)

from runtime.orchestrator.config import BlockRef, OrchestratorConfig
from runtime.orchestrator.orchestrator import Orchestrator


class _VadSpy:
    """VAD 替身：首个音频块发 speech.detected，之后发 speech.ended。"""

    def __init__(self) -> None:
        self._detected = False

    def manifest(self) -> dict:
        return {"block_id": "vad.spy", "category": "vad"}

    async def process(self, ctx, event) -> None:
        if event.type != AUDIO_APPENDED:
            return
        if not self._detected:
            self._detected = True
            await ctx.emit(
                Event(
                    type=SPEECH_DETECTED,
                    session_id=ctx.session_id,
                    source="vad.spy",
                    run_id=ctx.run_id,
                    payload={"confidence": 0.9},
                )
            )
        else:
            await ctx.emit(
                Event(
                    type=SPEECH_ENDED,
                    session_id=ctx.session_id,
                    source="vad.spy",
                    run_id=ctx.run_id,
                    payload={},
                )
            )


class _SttSpy:
    """STT 替身：SPEECH_ENDED 时按预设文本 emit transcript。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.transcribed = 0

    def manifest(self) -> dict:
        return {"block_id": "stt.spy", "category": "stt"}

    async def process(self, ctx, event) -> None:
        if event.type != SPEECH_ENDED:
            return
        self.transcribed += 1
        await ctx.emit(
            Event(
                type=TRANSCRIPT_COMPLETED,
                session_id=ctx.session_id,
                source="stt.spy",
                run_id=ctx.run_id,
                payload={"text": self.text, "language": "zh"},
            )
        )


class _LlmSpy:
    """LLM 替身：记录 llm.request 到达时的 vision_description。"""

    def __init__(self) -> None:
        self.calls = 0
        self.vision_seen: str | None = None
        self.last_text: str | None = None

    def manifest(self) -> dict:
        return {"block_id": "llm.spy", "category": "llm"}

    async def process(self, ctx, event) -> None:
        if event.type == LLM_REQUEST:
            self.calls += 1
            self.vision_seen = ctx.vision_description
            self.last_text = event.payload.get("text")


class _VisionSpy:
    """Vision 替身：describe_frame 返回固定描述。"""

    DESCRIPTION = "一个人坐在桌前，穿着黑色T恤，表情自然"

    def __init__(self) -> None:
        self.described = 0
        self.last_image: str | None = None
        self.last_request_id: str | None = None

    def manifest(self) -> dict:
        return {"block_id": "vision.spy", "category": "vision"}

    async def describe_frame(
        self,
        ctx,
        image_b64: str | None = None,
        prompt: str = "描述这张图片",
        request_id: str | None = None,
    ) -> Event:
        self.described += 1
        self.last_image = image_b64
        self.last_request_id = request_id
        return Event(
            type="vision.result",
            session_id=ctx.session_id,
            source="vision.spy",
            run_id=ctx.run_id,
            payload={
                "description": self.DESCRIPTION,
                "objects": [],
                "confidence": 0.9,
                "request_id": request_id,
            },
        )


class _Collector:
    def __init__(self) -> None:
        self.events: list = []

    async def __call__(self, event) -> None:
        self.events.append(event)


def _build(
    text: str,
    *,
    vision_timeout: float = 1.0,
) -> tuple[Orchestrator, _SttSpy, _LlmSpy, _VisionSpy, _Collector]:
    stt = _SttSpy(text)
    llm = _LlmSpy()
    vision = _VisionSpy()
    collector = _Collector()
    config = OrchestratorConfig(
        profile_id="test",
        blocks={
            "vad": BlockRef(id="vad.spy", deployment="local"),
            "stt": BlockRef(id="stt.spy", deployment="local"),
            "llm": BlockRef(id="llm.spy", deployment="local"),
            "vision": BlockRef(id="vision.spy", deployment="local"),
        },
        vision_timeout_s=vision_timeout,
    )
    orch = Orchestrator(config, event_sink=collector)
    orch.blocks["vad"] = _VadSpy()
    orch.blocks["stt"] = stt
    orch.blocks["llm"] = llm
    orch.blocks["vision"] = vision
    return orch, stt, llm, vision, collector


async def _say(orch: Orchestrator, session, n_chunks: int = 2) -> None:
    """喂音频触发一轮 VAD → STT。默认 2 chunk：第 1 个发 detected，第 2 个发 ended。"""
    for _ in range(n_chunks):
        pcm = b"\x00\x00" * 512
        await orch.ingest_audio(session, base64.b64encode(pcm).decode(), 512)
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)


async def _wait_for(cond, timeout: float = 3.0) -> bool:
    """轮询条件成立，避免硬 sleep 导致的 flaky。"""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


_FAKE_JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0fakejpeg").decode()


@pytest.mark.asyncio
async def test_trigger_word_emits_vision_request() -> None:
    """说"你看看我" → VISION_REQUEST 事件发出（带 request_id）。"""
    orch, *_ , collector = _build("你看看我")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")
    await _say(orch, session)

    vreq = [e for e in collector.events if e.type == VISION_REQUEST]
    assert vreq, "未发出 VISION_REQUEST"
    assert vreq[0].payload.get("request_id")
    assert vreq[0].payload.get("keyword")


@pytest.mark.asyncio
async def test_normal_chat_goes_straight_to_llm() -> None:
    """普通对话 → 不发 VISION_REQUEST，直接 llm.request。"""
    orch, _, llm, _, collector = _build("今天天气怎么样")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")
    await _say(orch, session)
    await _wait_for(lambda: llm.calls > 0)

    assert not any(e.type == VISION_REQUEST for e in collector.events)
    assert llm.last_text == "今天天气怎么样"
    assert llm.vision_seen is None


@pytest.mark.asyncio
async def test_same_turn_vision_waits_then_injects() -> None:
    """同轮闭环：触发词 → LLM 暂停 → 截帧上行 → 同轮 LLM 即拿到视觉描述。"""
    orch, _, llm, vision, collector = _build("你看看我")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")

    say_task = asyncio.create_task(_say(orch, session))
    # 等 VISION_REQUEST 发出；此时 LLM 必须还未被调用（同轮等待生效）
    assert await _wait_for(lambda: any(e.type == VISION_REQUEST for e in collector.events))
    assert llm.calls == 0, "LLM 在 vision.result 前被调用——同轮编排失效"

    # 浏览器截帧上行（0x02 + JPEG 模拟）
    await orch.ingest_vision_frame(session, _FAKE_JPEG_B64)
    await say_task
    assert await _wait_for(lambda: llm.calls > 0)

    assert vision.described == 1
    assert vision.last_image == _FAKE_JPEG_B64
    assert vision.last_request_id is not None
    assert llm.vision_seen == _VisionSpy.DESCRIPTION

    # 事件顺序：VISION_REQUEST 先于 LLM_REQUEST
    types = [e.type for e in collector.events]
    assert types.index(VISION_REQUEST) < types.index(LLM_REQUEST)


@pytest.mark.asyncio
async def test_vision_timeout_degrades_to_plain_answer() -> None:
    """触发词命中但截帧未到 → 超时后仍发 llm.request（无视觉注入）。"""
    orch, _, llm, vision, _ = _build("你看看我", vision_timeout=0.3)
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")
    await _say(orch, session)

    assert await _wait_for(lambda: llm.calls > 0, timeout=3.0)
    assert vision.described == 0
    assert llm.vision_seen is None
    assert llm.last_text == "你看看我"


@pytest.mark.asyncio
async def test_vision_frame_error_degrades_immediately() -> None:
    """浏览器摄像头拒绝 → handle_vision_frame_error 立即降级，不等超时。"""
    orch, _, llm, vision, collector = _build("你看看我", vision_timeout=5.0)
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")

    say_task = asyncio.create_task(_say(orch, session))
    assert await _wait_for(lambda: any(e.type == VISION_REQUEST for e in collector.events))

    await orch.handle_vision_frame_error(session, "NotAllowedError: Permission denied")
    await say_task
    # 5s 超时配置下若走完整个超时测试会明显变慢——这里应立即返回
    assert await _wait_for(lambda: llm.calls > 0, timeout=2.0)
    assert vision.described == 0
    assert llm.vision_seen is None


@pytest.mark.asyncio
async def test_vision_context_single_consume() -> None:
    """视觉描述只注入一次：下一轮 LLM 用完即清，再下一轮不再注入。"""
    orch, _, llm, vision, _ = _build("今天天气怎么样")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")

    # 用户主动截帧（非触发词场景，如点"看看我"按钮）
    await orch.ingest_vision_frame(session, _FAKE_JPEG_B64)
    assert vision.described == 1

    # 第一轮：注入
    await _say(orch, session)
    assert await _wait_for(lambda: llm.calls > 0)
    assert llm.vision_seen == _VisionSpy.DESCRIPTION

    # 第二轮：已消费，不再注入
    await _say(orch, session)
    assert await _wait_for(lambda: llm.calls > 1)
    assert llm.vision_seen is None


class _SlowVision:
    """挂起的 Vision 替身——describe_frame 阻塞直到 release，用于并发锁测试。"""

    def __init__(self) -> None:
        self.started = 0
        self.release = asyncio.Event()

    def manifest(self) -> dict:
        return {"block_id": "vision.slow", "category": "vision"}

    async def describe_frame(
        self,
        ctx,
        image_b64: str | None = None,
        prompt: str = "描述",
        request_id: str | None = None,
    ) -> Event:
        self.started += 1
        await self.release.wait()
        return Event(
            type="vision.result",
            session_id=ctx.session_id,
            source="vision.slow",
            run_id=ctx.run_id,
            payload={"description": "慢描述", "request_id": request_id},
        )


@pytest.mark.asyncio
async def test_vision_manual_frame_throttled() -> None:
    """AL-P1-011：无同轮 pending 的手动帧受 2s 最小间隔节流。"""
    orch, _, _, vision, _ = _build("今天天气怎么样")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")

    # 第一帧正常分析
    await orch.ingest_vision_frame(session, _FAKE_JPEG_B64)
    assert vision.described == 1
    # 间隔内第二帧（无 pending）被节流丢弃
    await orch.ingest_vision_frame(session, _FAKE_JPEG_B64)
    assert vision.described == 1


@pytest.mark.asyncio
async def test_vision_concurrent_frame_dropped_when_locked() -> None:
    """AL-P1-011：同 session 已有调用进行中（锁占用）→ 重复帧丢弃，不再调远程 API。"""
    stt = _SttSpy("你看看我")
    llm = _LlmSpy()
    slow = _SlowVision()
    collector = _Collector()
    config = OrchestratorConfig(
        profile_id="test",
        blocks={
            "vad": BlockRef(id="vad.spy", deployment="local"),
            "stt": BlockRef(id="stt.spy", deployment="local"),
            "llm": BlockRef(id="llm.spy", deployment="local"),
            "vision": BlockRef(id="vision.slow", deployment="local"),
        },
        vision_timeout_s=5.0,
    )
    orch = Orchestrator(config, event_sink=collector)
    orch.blocks["vad"] = _VadSpy()
    orch.blocks["stt"] = stt
    orch.blocks["llm"] = llm
    orch.blocks["vision"] = slow
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")

    # 制造 pending（有 pending 的帧跳过节流直达锁判定）
    loop = asyncio.get_running_loop()
    orch._vision_pending[session.session_id] = ("req1", loop.create_future())
    first = asyncio.create_task(orch.ingest_vision_frame(session, _FAKE_JPEG_B64))
    await asyncio.sleep(0.05)  # 第一帧占锁挂起
    assert slow.started == 1

    # 第二帧带 pending 进来——锁被占，直接丢弃（不排队不调 API）
    orch._vision_pending[session.session_id] = ("req2", loop.create_future())
    await orch.ingest_vision_frame(session, _FAKE_JPEG_B64)
    assert slow.started == 1

    slow.release.set()
    await asyncio.wait_for(first, timeout=2)
