"""Mock 全链路集成测试——阶段 2 核心验收。

验证主链路 VAD → STT → LLM → TTS → Avatar 端到端跑通：
1. 注入模拟音频流（高能量 PCM）
2. VAD 检测 speech.detected
3. VAD 持续静默 → speech.ended
4. STT emit transcript.completed
5. LLM emit llm.text.delta（多个）+ llm.text.done
6. TTS emit tts.audio.delta（多个）+ tts.audio.completed
7. Avatar emit avatar.speech_frame + avatar.idle_frame
8. Session 状态机正确推进：IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING → IDLE

这是 v0.1.0 验收标准第 3 条的核心证据。
"""

from __future__ import annotations

import asyncio
import base64

import numpy as np
import pytest
from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
    State,
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
                config={
                    "mode": "fixed",
                    "fixed_text": "你好数字人",
                },
            ),
            "llm": BlockRef(
                id="llm.mock",
                deployment="mock",
                config={
                    "chunk_delay_ms": 0,
                },
            ),
            "tts": BlockRef(
                id="tts.mock",
                deployment="mock",
                config={
                    "ms_per_char": 20,
                },
            ),
            "avatar": BlockRef(id="avatar.mock", deployment="mock"),
        },
    )


@pytest.mark.integration
class TestMockPipeline:
    async def test_full_pipeline_runs_to_completion(self) -> None:
        """主链路完整跑通：audio → VAD → STT → LLM → TTS → Avatar。"""
        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(_mock_config(), event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        # 灌入"说话"音频（多个高能量 chunk）
        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)

        # 灌入静音触发 speech.ended
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)

        # 等 LLM/TTS/Avatar 全部 emit（它们有内部 sleep）
        await asyncio.sleep(0.5)

        # 验证事件序列
        types = [e.type for e in emitted]
        assert SPEECH_DETECTED in types, "VAD 应检测到 speech_detected"
        assert SPEECH_ENDED in types, "VAD 应检测到 speech_ended"
        assert TRANSCRIPT_COMPLETED in types, "STT 应 emit transcript_completed"
        assert LLM_TEXT_DELTA in types, "LLM 应 emit text_delta"
        assert LLM_TEXT_DONE in types, "LLM 应 emit text_done"
        assert TTS_AUDIO_DELTA in types, "TTS 应 emit audio_delta"
        assert TTS_AUDIO_COMPLETED in types, "TTS 应 emit audio_completed"
        assert AVATAR_SPEECH_FRAME in types, "Avatar 应 emit speech_frame"
        assert AVATAR_IDLE_FRAME in types, "Avatar 应 emit idle_frame"

        await orch.shutdown()

    async def test_session_state_transitions_complete_cycle(self) -> None:
        """Session 状态机：IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING → IDLE。"""
        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(_mock_config(), event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        assert session.state == State.IDLE

        # 灌入音频让全链路跑通
        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)

        # 此时应在 LISTENING（VAD 已检测 speech）
        assert session.state in (State.LISTENING, State.TRANSCRIBING, State.THINKING)

        # 静音
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)

        await asyncio.sleep(0.5)

        # 最终应回到 IDLE
        assert session.state == State.IDLE, f"最终状态应是 IDLE，实际 {session.state}"

        await orch.shutdown()

    async def test_avatar_optional_degradation(self) -> None:
        """Avatar Block 缺席时，语音链路不阻断。"""
        cfg = _mock_config()
        # 移除 avatar
        cfg.blocks.pop("avatar", None)

        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(cfg, event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        # 链路应跑通（TTS 仍有输出）
        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)

        types = [e.type for e in emitted]
        assert TTS_AUDIO_DELTA in types, "TTS 应正常工作（avatar 缺席不影响）"
        assert AVATAR_SPEECH_FRAME not in types, "avatar 缺席不应 emit frame"

        await orch.shutdown()

    async def test_vision_block_does_not_block_pipeline(self) -> None:
        """Vision 是可选 Block——不订阅主链路事件，缺席/存在都不影响语音链路。"""
        cfg = _mock_config()
        cfg.blocks["vision"] = BlockRef(id="vision.mock", deployment="mock", optional=True)

        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(cfg, event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)

        types = [e.type for e in emitted]
        # 语音链路完整
        assert TTS_AUDIO_DELTA in types
        # Vision 不会自发 emit（无触发）
        assert "vision.result" not in types

        await orch.shutdown()

    async def test_interruption_during_speaking(self) -> None:
        """用户在 SPEAKING 时说话触发打断。"""
        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(_mock_config(), event_sink=sink)
        # 让 LLM 慢一些，给打断留窗口
        orch.config.blocks["llm"].config["chunk_delay_ms"] = 50
        await orch.setup()
        session = await orch.start_session()

        # 让助手进入 SPEAKING
        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)
        # 等 LLM 开始说话
        await asyncio.sleep(0.2)
        assert session.state == State.SPEAKING

        # 模拟用户打断：再次说话
        # VAD mock 已 reset，需要重新检测
        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)

        # 应进入 INTERRUPTING 然后回 IDLE/LISTENING
        await asyncio.sleep(0.1)
        assert session.state in (State.INTERRUPTING, State.IDLE, State.LISTENING)

        await orch.shutdown()


@pytest.mark.integration
class TestRunTranscriptReEmitted:
    """AL-P1-005：orchestrator 建新 run 后以新 run_id 重发 transcript.completed。

    STT 发出的原始事件携带旧 run_id（或 None），会被 Recorder 丢弃；
    重发副本（re_emitted=True）让 Recorder 落录本轮用户文本、前端正确归属。
    """

    async def test_transcript_re_emitted_with_new_run_id(self) -> None:
        emitted: list[Event] = []

        async def sink(e: Event) -> None:
            emitted.append(e)

        orch = Orchestrator(_mock_config(), event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        for _ in range(3):
            await orch.ingest_audio(session, _loud_pcm(), 1600)
            await asyncio.sleep(0.01)
        for _ in range(4):
            await orch.ingest_audio(session, _silent_pcm(), 1600)
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)

        transcripts = [e for e in emitted if e.type == TRANSCRIPT_COMPLETED]
        re_emitted = [e for e in transcripts if e.payload.get("re_emitted") is True]
        assert re_emitted, "应有 orchestrator 重发的 transcript.completed 副本"
        # 重发副本必须携带当前 run_id（非 None），供 Recorder 落录
        assert re_emitted[-1].run_id is not None
        assert re_emitted[-1].run_id == session.current_run_id
        # 原文保持不变
        assert re_emitted[-1].payload.get("text") == "你好数字人"

        await orch.shutdown()
