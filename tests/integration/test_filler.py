"""Filler 垫音集成测试（VoxEMW 移植机制）。

验证：
1. 转写完成后垫音经伪 tts.audio.delta 发出（payload.filler=True, source=orchestrator.filler）
2. 真 TTS 首块到达后垫音停发余量（抢先语义）
3. 垫音不打断主链路（LLM/TTS/Avatar 正常推进）
"""

from __future__ import annotations

import asyncio
import base64

import numpy as np
import pytest
from avatarloom_protocol import (
    LLM_TEXT_DONE,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)

from runtime.orchestrator import Orchestrator
from runtime.orchestrator.config import BlockRef, OrchestratorConfig


def _loud_pcm(samples: int = 1600, amp: float = 800) -> str:
    arr = (np.ones(samples, dtype=np.float32) * amp * 32767 / 1000).astype(np.int16)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def _silent_pcm(samples: int = 1600) -> str:
    arr = np.zeros(samples, dtype=np.int16)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def _mock_config() -> OrchestratorConfig:
    return OrchestratorConfig(
        profile_id="mock",
        blocks={
            "vad": BlockRef(
                id="vad.mock",
                deployment="mock",
                config={
                    "energy_threshold": 300.0,
                    "min_speech_chunks": 2,
                    "silence_chunks_to_end": 3,
                },
            ),
            "stt": BlockRef(
                id="stt.mock",
                deployment="mock",
                config={"mode": "fixed", "fixed_text": "你好数字人"},
            ),
            "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 30}),
            "tts": BlockRef(id="tts.mock", deployment="mock", config={"ms_per_char": 30}),
            "avatar": BlockRef(id="avatar.mock", deployment="mock"),
        },
    )


@pytest.mark.integration
class TestFillerMurmur:
    async def test_filler_emitted_then_preempted_by_real_tts(self) -> None:
        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(_mock_config(), event_sink=sink)
        await orch.setup()
        session = await orch.start_session(
            persona_id="demo-assistant", workspace_root="."
        )

        # 触发一轮 transcript
        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)

        # 等链路推进（filler 0.4s/块 + LLM/TTS 完成）
        await asyncio.sleep(1.5)

        tts_deltas = [e for e in emitted if e.type == TTS_AUDIO_DELTA]
        filler_deltas = [e for e in tts_deltas if e.payload.get("filler")]
        real_deltas = [
            e for e in tts_deltas
            if not e.payload.get("filler") and e.source != "orchestrator.filler"
        ]

        # 1. 垫音确实发出（盖 LLM 首句空白）
        assert filler_deltas, "转写完成后应有 filler 垫音 delta"
        assert all(e.source == "orchestrator.filler" for e in filler_deltas)
        # 2. 主链路正常：真 TTS 也出现
        assert real_deltas, "真 TTS delta 应正常发出"
        assert any(e.type == LLM_TEXT_DONE for e in emitted)
        assert any(e.type == TTS_AUDIO_COMPLETED for e in emitted)
        # 3. 抢先语义：真 TTS 开始后 filler 不再发（filler 的最后一块
        #    不晚于真 TTS 第一块之后 0.45s）
        first_real_ts = min(e.timestamp for e in real_deltas)
        late_filler = [
            e for e in filler_deltas if e.timestamp > first_real_ts + 450
        ]
        assert not late_filler, "真 TTS 开始后 filler 应停发余量"
        # 4. filler task 已清理
        assert session.session_id not in orch._filler_tasks

        await orch.shutdown()

    async def test_filler_disabled_config(self) -> None:
        config = _mock_config()
        config.filler_enabled = False
        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(config, event_sink=sink)
        await orch.setup()
        session = await orch.start_session(
            persona_id="demo-assistant", workspace_root="."
        )
        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.0)

        assert not any(
            e.payload.get("filler")
            for e in emitted
            if e.type == TTS_AUDIO_DELTA
        ), "filler_enabled=False 时不应发垫音"

        await orch.shutdown()
