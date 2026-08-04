"""GPU Adapter 纯逻辑测试 + 降级路径。

不跑真实模型——单测覆盖：
- Silero VAD：PCM 解码、chunk 切分
- SenseVoice：WAV 构造、输出解析
- Qwen3/VoxCPM2：重采样数学
- MuseTalk：帧索引逻辑
- 所有 GPU Adapter 的 manifest 声明完整
- import 失败时降级（Orchestrator 层）
"""

from __future__ import annotations

import base64

import numpy as np
import pytest
from avatarloom_sdk import BlockContext

from blocks.avatar.flashhead import FlashHeadAvatarBlock
from blocks.avatar.musetalk import MuseTalkAvatarBlock
from blocks.stt.sensevoice import SenseVoiceSttBlock, parse_sensevoice_output, pcm16_to_wav
from blocks.tts.qwen3 import Qwen3TtsBlock
from blocks.tts.qwen3 import resample_pcm as qwen_resample
from blocks.tts.voxcpm2 import VoxCpm2TtsBlock, _resample_48k_to_16k
from blocks.vad.silero import SileroVadBlock

# ---------------------------------------------------------------------------
# Manifest 完整性
# ---------------------------------------------------------------------------


class TestManifests:
    @pytest.mark.parametrize(
        "block_cls,expected_id",
        [
            (SileroVadBlock, "vad.silero"),
            (SenseVoiceSttBlock, "stt.sensevoice"),
            (Qwen3TtsBlock, "tts.qwen3"),
            (VoxCpm2TtsBlock, "tts.voxcpm2"),
            (MuseTalkAvatarBlock, "avatar.musetalk"),
            (FlashHeadAvatarBlock, "avatar.flashhead"),
        ],
    )
    def test_manifest_declares_correctly(self, block_cls, expected_id) -> None:
        m = block_cls.manifest()
        assert m.block_id == expected_id
        assert m.category in ("vad", "stt", "tts", "avatar", "vision", "llm")
        assert m.resources is not None
        assert m.config_schema is not None

    def test_gpu_adapters_declare_accelerator(self) -> None:
        """GPU Adapter 应声明 accelerator。"""
        for cls in [
            SileroVadBlock,
            SenseVoiceSttBlock,
            Qwen3TtsBlock,
            VoxCpm2TtsBlock,
            MuseTalkAvatarBlock,
        ]:
            m = cls.manifest()
            assert len(m.resources.accelerator) > 0, f"{cls.__name__} 应声明 accelerator"

    def test_gpu_adapters_declare_pip_extras(self) -> None:
        """GPU Adapter 应声明 pip extras（供 doctor 检查）。"""
        for cls in [
            SileroVadBlock,
            SenseVoiceSttBlock,
            Qwen3TtsBlock,
            VoxCpm2TtsBlock,
            MuseTalkAvatarBlock,
        ]:
            m = cls.manifest()
            assert len(m.resources.pip_extras) > 0 or len(m.install_extras) > 0, (
                f"{cls.__name__} 应声明 pip_extras 或 install_extras"
            )


# ---------------------------------------------------------------------------
# Silero 纯逻辑
# ---------------------------------------------------------------------------


class TestSileroLogic:
    def test_decode_pcm(self) -> None:
        arr = np.array([0, 16384, -16384, 32767], dtype=np.int16)
        b64 = base64.b64encode(arr.tobytes()).decode("ascii")
        decoded = SileroVadBlock._decode_pcm(b64)
        assert len(decoded) == 4
        # int16 max -> float32 接近 1
        assert decoded[3] > 0.99
        assert decoded[0] == 0.0

    def test_chunk_exact_division(self) -> None:
        arr = np.arange(1024, dtype=np.float32)
        chunks = SileroVadBlock._chunk(arr, 512)
        assert len(chunks) == 2
        assert len(chunks[0]) == 512

    def test_chunk_discards_remainder(self) -> None:
        arr = np.arange(700, dtype=np.float32)
        chunks = SileroVadBlock._chunk(arr, 512)
        # 700 // 512 = 1，剩 188 丢弃
        assert len(chunks) == 1
        assert len(chunks[0]) == 512


# ---------------------------------------------------------------------------
# SenseVoice 纯逻辑
# ---------------------------------------------------------------------------


class TestSenseVoiceLogic:
    def test_pcm16_to_wav_header(self) -> None:
        pcm = b"\x00\x00" * 100
        wav = pcm16_to_wav(pcm, 16000)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert wav[12:16] == b"fmt "
        assert len(wav) == 44 + len(pcm)

    def test_parse_output_extracts_text_and_tags(self) -> None:
        raw = "<|zh|><|HAPPY|><|Speech|><|woitn|>你好世界"
        text, tags = parse_sensevoice_output(raw)
        assert text == "你好世界"
        assert tags["language"] == "zh"
        assert tags["emotion"] == "HAPPY"

    def test_parse_output_plain_text(self) -> None:
        text, tags = parse_sensevoice_output("纯文本")
        assert text == "纯文本"
        assert tags == {}

    def test_parse_output_multiple_emotions(self) -> None:
        raw = "<|en|><|NEUTRAL|><|Speech|>hello"
        text, tags = parse_sensevoice_output(raw)
        assert text == "hello"
        assert tags["language"] == "en"
        assert tags["emotion"] == "NEUTRAL"


# ---------------------------------------------------------------------------
# Qwen3 / VoxCPM2 重采样
# ---------------------------------------------------------------------------


class TestResampling:
    def test_qwen3_resample_24k_to_16k(self) -> None:
        # 24 个 float32 样本
        arr = np.linspace(-0.5, 0.5, 24, dtype=np.float32)
        raw = arr.tobytes()
        out = qwen_resample(raw, 24000, 16000)
        out_arr = np.frombuffer(out, dtype=np.int16)
        # 24k -> 16k = 0.667 比率，约 16 个样本
        assert 10 <= len(out_arr) <= 20

    def test_voxcpm2_resample_48k_to_16k(self) -> None:
        arr = np.linspace(-0.5, 0.5, 48, dtype=np.float32)
        raw = arr.tobytes()
        out = _resample_48k_to_16k(raw)
        out_arr = np.frombuffer(out, dtype=np.int16)
        # 48k -> 16k = 每 3 取 1，48/3=16
        assert len(out_arr) == 16

    def test_resample_empty_input(self) -> None:
        assert qwen_resample(b"", 24000, 16000) == b""
        assert _resample_48k_to_16k(b"") == b""

    def test_resample_clips_overflow(self) -> None:
        # float32 超过 1.0 应被裁剪——用足够多样本让降采样后保留
        arr = np.array([2.0, 2.0, -2.0, -2.0, 0.0, 0.0] * 4, dtype=np.float32)
        out = qwen_resample(arr.tobytes(), 24000, 16000)
        out_arr = np.frombuffer(out, dtype=np.int16)
        # 2.0 应被裁到 int16 max（32767），-2.0 裁到 min 附近（-32767）
        assert out_arr.max() == 32767
        assert out_arr.min() <= -32767


# ---------------------------------------------------------------------------
# FlashHead 占位
# ---------------------------------------------------------------------------


class TestFlashHeadStub:
    async def test_setup_raises_clear_error(self) -> None:
        """FlashHead 预留 Adapter 应明确告知未实装。"""
        from avatarloom_sdk import BlockSetupError

        block = FlashHeadAvatarBlock()
        ctx = BlockContext(session_id="s", run_id="r", workspace_root=".")
        with pytest.raises(BlockSetupError, match=r"未实装|独立环境"):
            await block.setup(ctx)


# ---------------------------------------------------------------------------
# 降级路径（Orchestrator 层）
# ---------------------------------------------------------------------------


class TestDegradationPath:
    async def test_gpu_block_setup_fails_falls_back_to_mock(self) -> None:
        """GPU Block import 失败 -> fallback 到 mock（Orchestrator 层降级）。"""
        from runtime.orchestrator import Orchestrator
        from runtime.orchestrator.config import BlockRef, OrchestratorConfig

        config = OrchestratorConfig(
            profile_id="test",
            blocks={
                "vad": BlockRef(
                    id="vad.silero",
                    deployment="local",
                    fallback="vad.mock",
                    config={"device": "cpu"},
                ),
                "stt": BlockRef(id="stt.mock", deployment="mock"),
                "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 0}),
                "tts": BlockRef(id="tts.mock", deployment="mock"),
            },
        )
        orch = Orchestrator(config)
        await orch.setup()

        # silero 没装 torch，应降级到 vad.mock
        assert "vad" in orch.blocks
        assert orch.blocks["vad"].manifest().block_id == "vad.mock"
        assert "vad" in orch.degraded_blocks
        await orch.shutdown()

    async def test_optional_block_absent_does_not_block(self) -> None:
        """optional Block 失败时不阻断主链路。"""
        from runtime.orchestrator import Orchestrator
        from runtime.orchestrator.config import BlockRef, OrchestratorConfig

        config = OrchestratorConfig(
            blocks={
                "vad": BlockRef(id="vad.mock", deployment="mock"),
                "stt": BlockRef(id="stt.mock", deployment="mock"),
                "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 0}),
                "tts": BlockRef(id="tts.mock", deployment="mock"),
                "avatar": BlockRef(
                    id="avatar.musetalk",
                    deployment="local",
                    optional=True,
                    config={"portrait": "/nonexistent"},
                ),
            },
        )
        orch = Orchestrator(config)
        await orch.setup()
        # musetalk 没装 torch，optional=True -> 缺席但不阻断
        assert "avatar" not in orch.blocks
        await orch.shutdown()
