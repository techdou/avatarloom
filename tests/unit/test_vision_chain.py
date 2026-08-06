"""Vision 链路测试：触发词 → VISION_REQUEST；截帧 → describe_frame → LLM 注入。

覆盖：
1. 触发词（"看看我"）命中 → orchestrator emit VISION_REQUEST
2. 普通对话不误触发
3. ingest_vision_frame → vision block.describe_frame 被调，描述存上下文
4. 下一轮 LLM 收到 ctx.vision_description（注入生效）
"""

from __future__ import annotations

import asyncio
import base64

import pytest
from avatarloom_protocol import (
    AUDIO_APPENDED,
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
    """LLM 替身：记录收到的 vision_description。"""

    def __init__(self) -> None:
        self.vision_seen: str | None = None

    def manifest(self) -> dict:
        return {"block_id": "llm.spy", "category": "llm"}

    async def process(self, ctx, event) -> None:
        if event.type == TRANSCRIPT_COMPLETED:
            self.vision_seen = ctx.vision_description


class _VisionSpy:
    """Vision 替身：describe_frame 返回固定描述。"""

    def __init__(self) -> None:
        self.described = 0
        self.last_image: str | None = None

    def manifest(self) -> dict:
        return {"block_id": "vision.spy", "category": "vision"}

    async def describe_frame(
        self, ctx, image_b64: str, prompt: str = "描述这张图片"
    ) -> Event:
        self.described += 1
        self.last_image = image_b64
        return Event(
            type="vision.result",
            session_id=ctx.session_id,
            source="vision.spy",
            run_id=ctx.run_id,
            payload={
                "description": "一个人坐在桌前，穿着黑色T恤，表情自然",
                "objects": [],
                "confidence": 0.9,
            },
        )


class _Collector:
    def __init__(self) -> None:
        self.events: list = []

    async def __call__(self, event) -> None:
        self.events.append(event)


def _build(text: str) -> tuple[Orchestrator, _SttSpy, _LlmSpy, _VisionSpy, _Collector]:
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


@pytest.mark.asyncio
async def test_trigger_word_emits_vision_request() -> None:
    """说"你看看我" → VISION_REQUEST 事件发出。"""
    orch, *_ , collector = _build("你看看我")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")
    await _say(orch, session)

    assert any(e.type == VISION_REQUEST for e in collector.events)


@pytest.mark.asyncio
async def test_normal_chat_does_not_trigger_vision() -> None:
    """普通对话（"今天天气怎么样"）→ 不触发 VISION_REQUEST。"""
    orch, *_ , collector = _build("今天天气怎么样")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")
    await _say(orch, session)

    assert not any(e.type == VISION_REQUEST for e in collector.events)


@pytest.mark.asyncio
async def test_ingest_vision_frame_describes_and_injects_llm() -> None:
    """截帧上行 → describe_frame 被调；下一轮 LLM 收到 vision_description。"""
    orch, _, llm, vision, _ = _build("今天天气怎么样")
    await orch._wire_event_bus()
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")

    # 第一轮普通对话（LLM 此时无视觉上下文）
    await _say(orch, session)
    assert llm.vision_seen is None

    # 浏览器截帧上行（0x02 + JPEG 模拟）
    jpeg = base64.b64encode(b"\xff\xd8\xff\xe0fakejpeg").decode()
    await orch.ingest_vision_frame(session, jpeg)

    assert vision.described == 1
    assert vision.last_image == jpeg

    # 第二轮对话 → LLM 应看到视觉描述
    await _say(orch, session)
    assert llm.vision_seen == "一个人坐在桌前，穿着黑色T恤，表情自然"
