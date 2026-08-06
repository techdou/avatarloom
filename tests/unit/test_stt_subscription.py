"""回归测试：STT 必须订阅 audio.appended + speech.ended。

真实 SenseVoice 需要 audio.appended 累积 PCM 缓冲——只订 speech.* 时
transcript 永不触发（此 bug 曾被 mock 测试掩盖）。
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
    Event,
)
from runtime.orchestrator.config import BlockRef, OrchestratorConfig
from runtime.orchestrator.orchestrator import Orchestrator


def _manifest(block_id: str) -> dict:
    return {"block_id": block_id, "category": "stt"}


class _SttSpy:
    """轻量 STT 替身：记录收到的音频缓冲，SPEECH_ENDED 时 emit transcript。"""

    def __init__(self) -> None:
        self.bufs: dict[str, bytearray] = {}
        self.transcribed: list[int] = []

    def manifest(self) -> dict:
        return _manifest("stt.spy")

    async def process(self, ctx, event) -> None:
        if event.type == AUDIO_APPENDED:
            pcm = base64.b64decode(event.payload.get("pcm_b64", ""))
            self.bufs.setdefault(ctx.session_id, bytearray()).extend(pcm)
        elif event.type == SPEECH_ENDED:
            buf = self.bufs.pop(ctx.session_id, bytearray())
            self.transcribed.append(len(buf))
            await ctx.emit(
                Event(
                    type=TRANSCRIPT_COMPLETED,
                    session_id=ctx.session_id,
                    source="stt.spy",
                    run_id=ctx.run_id,
                    payload={"text": f"len={len(buf)}", "language": "zh"},
                )
            )


class _VadSpy:
    """VAD 替身：首个音频块发 speech.detected，之后发 speech.ended。

    遵循真实状态机：idle --speech_started--> listening --speech_ended-->
    processing --transcript_ready--> ...（先 detected 再 ended）。
    """

    def __init__(self) -> None:
        self._detected = False

    def manifest(self) -> dict:
        return _manifest("vad.spy")

    async def process(self, ctx, event) -> None:
        if event.type == AUDIO_APPENDED:
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


class _Collector:
    def __init__(self) -> None:
        self.events: list = []

    async def __call__(self, event) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_stt_receives_audio_appended_and_transcribes() -> None:
    """STT 收到 audio.appended 累积音频，SPEECH_ENDED 触发转写。"""
    stt = _SttSpy()
    vad = _VadSpy()
    collector = _Collector()

    config = OrchestratorConfig(
        profile_id="test",
        blocks={
            "vad": BlockRef(id="vad.spy", deployment="local"),
            "stt": BlockRef(id="stt.spy", deployment="local"),
        },
    )
    # 手动装配替身（绕过 BLOCK_REGISTRY 的 entrypoint 加载）
    orch = Orchestrator(config, event_sink=collector)
    orch.blocks["vad"] = vad
    orch.blocks["stt"] = stt
    await orch._wire_event_bus()

    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")
    # 喂 2 个音频 chunk（各 512 样本 = 1024 字节 PCM16）
    for _ in range(2):
        pcm = b"\x00\x00" * 512
        await orch.ingest_audio(session, base64.b64encode(pcm).decode(), 512)
        await asyncio.sleep(0.02)

    # 等事件处理完成
    await asyncio.sleep(0.1)

    assert stt.bufs == {}  # 音频缓冲被消费
    assert stt.transcribed == [2048]  # 2 chunk × 1024 字节
    assert any(e.type == TRANSCRIPT_COMPLETED for e in collector.events)


@pytest.mark.asyncio
async def test_stt_subscription_includes_audio_appended() -> None:
    """STT 订阅列表必须含 AUDIO_APPENDED（回归防护）。"""
    stt = _SttSpy()
    vad = _VadSpy()

    config = OrchestratorConfig(
        profile_id="test",
        blocks={
            "vad": BlockRef(id="vad.spy", deployment="local"),
            "stt": BlockRef(id="stt.spy", deployment="local"),
        },
    )
    orch = Orchestrator(config)
    orch.blocks["vad"] = vad
    orch.blocks["stt"] = stt
    await orch._wire_event_bus()

    # EventBus 内部订阅表：验证 STT handler 同时挂在 audio.appended 和 speech.ended
    bus = orch.event_bus
    # 通过发布事件验证：发 audio.appended，STT 应收到（否则 bufs 空）
    session = await orch.start_session(persona_id="demo-assistant", workspace_root=".")
    pcm = b"\x01\x02" * 512
    await orch.ingest_audio(session, base64.b64encode(pcm).decode(), 512)
    await asyncio.sleep(0.05)
    assert any(len(v) == 1024 for v in stt.bufs.values()), (
        "STT 未收到 audio.appended——订阅缺失，transcript 永不触发"
    )
