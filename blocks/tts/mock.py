"""Mock TTS Block。

收到 llm.text.delta（按句）后生成正弦波 PCM16 音频流。

策略：
- 每个中文字符生成固定时长的"嘟"声（可配频率/时长）
- 流式输出 PCM chunk
- 句末 emit audio.completed

这样浏览器能真实听到 Mock 合成的"语音"，
配合 Mock LLM 的逐句流，完整演示 LLM→TTS 流式管线。
"""

from __future__ import annotations

import asyncio
import base64
import math

import numpy as np
from avatarloom_protocol import (
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability

SAMPLE_RATE = 16000


class MockTtsBlock(Block):
    """Mock TTS — 正弦波合成。"""

    _freq: float = 440.0
    _ms_per_char: int = 120
    _chunk_samples: int = 1600  # 100ms @ 16kHz
    _total_samples: int = 0
    _first_audio_emitted: bool = False
    _sentence_buffers: dict[int, str] = {}  # sentence_index -> 累积文本

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="tts.mock",
            name="Mock TTS (Sine wave)",
            category="tts",
            runtime_type="mock",
            capabilities=Capability(streaming=True, interruption=True),
            inputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            outputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            config_schema={
                "type": "object",
                "properties": {
                    "frequency": {"type": "number", "default": 440.0},
                    "ms_per_char": {"type": "integer", "default": 120},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._freq = float(cfg.get("frequency", 440.0))
        self._ms_per_char = int(cfg.get("ms_per_char", 120))
        self._total_samples = 0
        self._first_audio_emitted = False
        self._sentence_buffers = {}
        self._mark_ready()
        await ctx.logger.ainfo("tts.mock ready", freq=self._freq)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type == LLM_TEXT_DELTA:
            idx = event.payload.get("sentence_index", 0)
            text: str = event.payload.get("text", "")
            is_end = event.payload.get("is_sentence_end", False)

            if text:
                # 累积文本（按句索引）
                self._sentence_buffers[idx] = self._sentence_buffers.get(idx, "") + text
                # 为文本生成音频
                await self._synthesize_text(ctx, text)

            if is_end:
                # 句末——flush 当前句的尾部
                pass

        elif event.type == LLM_TEXT_DONE:
            await ctx.emit(
                Event(
                    type=TTS_AUDIO_COMPLETED,
                    session_id=ctx.session_id,
                    source="tts.mock",
                    run_id=ctx.run_id,
                    payload={
                        "total_samples": self._total_samples,
                        "duration_ms": int(self._total_samples / SAMPLE_RATE * 1000),
                    },
                )
            )

    async def _synthesize_text(self, ctx: BlockContext, text: str) -> None:
        """为一段文本生成正弦波音频并流式输出。"""
        # 每字符时长
        samples_per_char = int(SAMPLE_RATE * self._ms_per_char / 1000)
        total_samples_needed = samples_per_char * max(len(text), 1)

        # 生成连续正弦波（中文字符数 x ms_per_char）
        t = np.arange(total_samples_needed) / SAMPLE_RATE
        # 加点包络让声音不那么刺耳（ADSR 简化版）
        envelope = np.ones_like(t)
        attack = int(0.01 * SAMPLE_RATE)
        if attack > 0:
            envelope[:attack] = np.linspace(0, 1, attack)
        release = int(0.02 * SAMPLE_RATE)
        if release > 0:
            envelope[-release:] = np.linspace(1, 0, release)

        wave = 0.3 * envelope * np.sin(2 * math.pi * self._freq * t)
        pcm = (wave * 32767).astype(np.int16)

        # 按 chunk 切分流式输出
        offset = 0
        while offset < len(pcm):
            chunk = pcm[offset : offset + self._chunk_samples]
            offset += self._chunk_samples

            pcm_b64 = base64.b64encode(chunk.tobytes()).decode("ascii")
            self._total_samples += len(chunk)

            await ctx.emit(
                Event(
                    type=TTS_AUDIO_DELTA,
                    session_id=ctx.session_id,
                    source="tts.mock",
                    run_id=ctx.run_id,
                    payload={
                        "pcm_b64": pcm_b64,
                        "sample_rate": SAMPLE_RATE,
                        "samples": len(chunk),
                        "text": text,
                    },
                )
            )
            if not self._first_audio_emitted:
                self._first_audio_emitted = True
            # 让出事件循环（流式节奏）
            await asyncio.sleep(0)

    async def reset(self, session_id: str) -> None:
        """打断时清空。"""
        self._total_samples = 0
        self._first_audio_emitted = False
        self._sentence_buffers = {}
