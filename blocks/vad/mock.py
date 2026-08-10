"""Mock VAD Block。

模拟语音活动检测——收到音频 chunk 后，按配置的概率/策略 emit speech.detected/speech.ended。

策略：
- 检测音频能量（PCM16 的绝对值平均），超阈值视为"开始说话"
- 持续 N 个低能量 chunk 视为"说完"

这样即使是 Mock 也能基于真实音频数据做合理判断，
让浏览器对麦克风说话 → Mock VAD → Mock STT 链路真实可演示。
"""

from __future__ import annotations

import base64
import struct

import numpy as np
from avatarloom_protocol import (
    AUDIO_APPENDED,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability


class MockVadBlock(Block):
    """能量阈值 VAD。"""

    def __init__(self) -> None:
        super().__init__()
        # 状态字段（实例级，每个 Session 独立——v0.1 单 Session 简化）
        self._energy_threshold: float = 300.0
        self._silence_chunks_to_end: int = 8
        self._current_silence_count: int = 0
        self._is_speaking: bool = False
        self._min_speech_chunks: int = 2
        self._speech_chunk_count: int = 0

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="vad.mock",
            name="Mock VAD (Energy-based)",
            category="vad",
            runtime_type="mock",
            capabilities=Capability(streaming=False, languages=["zh", "en"]),
            inputs=[AUDIO_APPENDED],
            outputs=[SPEECH_DETECTED, SPEECH_ENDED],
            config_schema={
                "type": "object",
                "properties": {
                    "energy_threshold": {"type": "number", "default": 300.0},
                    "silence_chunks_to_end": {"type": "integer", "default": 8},
                    "min_speech_chunks": {"type": "integer", "default": 2},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._energy_threshold = float(cfg.get("energy_threshold", 300.0))
        self._silence_chunks_to_end = int(cfg.get("silence_chunks_to_end", 8))
        self._min_speech_chunks = int(cfg.get("min_speech_chunks", 2))
        self._is_speaking = False
        self._current_silence_count = 0
        self._speech_chunk_count = 0
        self._mark_ready()
        await ctx.logger.ainfo(
            "vad.mock ready",
            threshold=self._energy_threshold,
            silence_to_end=self._silence_chunks_to_end,
        )

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type != AUDIO_APPENDED:
            return

        pcm_b64 = event.payload.get("pcm_b64", "")
        samples = event.payload.get("samples", 0)
        energy = self._compute_energy(pcm_b64, samples)

        if self._is_speaking:
            if energy < self._energy_threshold:
                self._current_silence_count += 1
                if self._current_silence_count >= self._silence_chunks_to_end:
                    await self._emit_speech_ended(ctx)
            else:
                self._current_silence_count = 0
                self._speech_chunk_count += 1
        else:
            if energy >= self._energy_threshold:
                self._speech_chunk_count += 1
                if self._speech_chunk_count >= self._min_speech_chunks:
                    await self._emit_speech_detected(ctx, energy)
            else:
                self._speech_chunk_count = 0

    async def reset(self, session_id: str) -> None:
        """用户打断时重置 VAD 状态。"""
        self._is_speaking = False
        self._current_silence_count = 0
        self._speech_chunk_count = 0

    # ---- helpers ----

    @staticmethod
    def _compute_energy(pcm_b64: str, samples: int) -> float:
        """计算 PCM16 chunk 的 RMS 能量。

        纯 numpy 计算，无外部依赖。空数据返回 0。
        """
        if not pcm_b64 or samples <= 0:
            return 0.0
        try:
            raw = base64.b64decode(pcm_b64)
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            if arr.size == 0:
                return 0.0
            return float(np.sqrt(np.mean(arr**2)))
        except (ValueError, struct.error):
            return 0.0

    async def _emit_speech_detected(self, ctx: BlockContext, energy: float) -> None:
        self._is_speaking = True
        self._current_silence_count = 0
        await ctx.emit(
            Event(
                type=SPEECH_DETECTED,
                session_id=ctx.session_id,
                source="vad.mock",
                run_id=ctx.run_id,
                payload={"confidence": min(1.0, energy / 1000.0)},
            )
        )

    async def _emit_speech_ended(self, ctx: BlockContext) -> None:
        self._is_speaking = False
        self._current_silence_count = 0
        self._speech_chunk_count = 0
        await ctx.emit(
            Event(
                type=SPEECH_ENDED,
                session_id=ctx.session_id,
                source="vad.mock",
                run_id=ctx.run_id,
                payload={"duration_ms": 0},
            )
        )
