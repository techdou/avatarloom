"""OpenAI-compatible TTS Block。

实现 /audio/speech 接口（tts-1/tts-1-hd 兼容）。

策略：
- 收到 llm.text.delta 且 is_sentence_end=True 时，把累积的整句发去合成
- 流式返回音频 PCM（response_format=pcm）
- 重采样到 16kHz（OpenAI 返回 24kHz，需降采样）

v0.1 简化：整句合成（非 phoneme 级流式）。
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from avatarloom_protocol import (
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements

from blocks._audio import resample_float32_to_int16 as _resample_pcm
from blocks._http_retry import post_with_retry

TARGET_SR = 16000


class OpenAITtsBlock(Block):
    """OpenAI-compatible TTS（tts-1）。"""

    def __init__(self) -> None:
        super().__init__()
        self._base_url: str = "https://api.openai.com/v1"
        self._api_key: str = ""
        self._model: str = "tts-1"
        self._voice: str = "alloy"
        self._timeout: float = 30.0
        # 按句累积
        self._sentence_buffers: dict[int, str] = {}
        self._total_samples: int = 0
        # 按 run 隔离 + 打断协作（同 voxcpm2 模式，见 AL-P2-003 / AL-P1-006）
        self._run_id: str | None = None
        self._cancelled_run_ids: set[str] = set()

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="tts.openai-compatible",
            name="OpenAI-compatible TTS",
            category="tts",
            runtime_type="http_remote",
            capabilities=Capability(streaming=True, voice_cloning=False, interruption=True),
            inputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            outputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            resources=ResourceRequirements(),
            config_schema={
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string"},
                    "apiKeyEnv": {"type": "string", "default": "TTS_API_KEY"},
                    "model": {"type": "string", "default": "tts-1"},
                    "voice": {"type": "string", "default": "alloy"},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._base_url = str(cfg.get("baseUrl") or "https://api.openai.com/v1")
        api_key_env = str(cfg.get("apiKeyEnv") or "TTS_API_KEY")
        self._api_key = str(cfg.get("apiKey") or _read_env(api_key_env))
        self._model = str(cfg.get("model") or "tts-1")
        self._voice = str(cfg.get("voice") or "alloy")
        self._total_samples = 0
        self._sentence_buffers = {}
        # 按 run 隔离 + 打断协作——setup 重新初始化以支持同实例 re-setup
        self._run_id = None
        self._cancelled_run_ids = set()
        self._mark_ready()
        await ctx.logger.ainfo("tts.openai-compatible ready", voice=self._voice)

    def _sync_run_state(self, ctx: BlockContext) -> bool:
        """按 run 隔离状态；True = 本 run 已打断，调用方直接 return。"""
        if ctx.run_id != self._run_id:
            self._total_samples = 0
            self._sentence_buffers = {}
            self._run_id = ctx.run_id
        return ctx.run_id is not None and ctx.run_id in self._cancelled_run_ids

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if self._sync_run_state(ctx):
            return
        if event.type == LLM_TEXT_DELTA:
            text = event.payload.get("text", "")
            idx = event.payload.get("sentence_index", 0)
            is_end = event.payload.get("is_sentence_end", False)
            if text:
                self._sentence_buffers[idx] = self._sentence_buffers.get(idx, "") + text
            if is_end:
                sentence = self._sentence_buffers.pop(idx, "")
                if sentence.strip():
                    await self._synthesize(ctx, sentence)

        elif event.type == LLM_TEXT_DONE:
            # 句尾剩余合成（无句末标点时缓冲会被丢弃的真因修复）
            pending = sorted(self._sentence_buffers.items())
            self._sentence_buffers = {}
            for _idx, sentence in pending:
                if sentence.strip():
                    await self._synthesize(ctx, sentence)
            await ctx.emit(
                Event(
                    type=TTS_AUDIO_COMPLETED,
                    session_id=ctx.session_id,
                    source="tts.openai-compatible",
                    run_id=ctx.run_id,
                    payload={
                        "total_samples": self._total_samples,
                        "duration_ms": int(self._total_samples / TARGET_SR * 1000),
                    },
                )
            )

    async def _synthesize(self, ctx: BlockContext, text: str) -> None:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            ) as client:
                payload: dict[str, Any] = {
                    "model": self._model,
                    "voice": self._voice,
                    "input": text,
                    "response_format": "pcm",
                }
                resp = await post_with_retry(client, "/audio/speech", json=payload)
                # OpenAI PCM 是 24kHz float32 little-endian
                raw = resp.content
        except httpx.HTTPStatusError as e:
            await ctx.logger.aerror("TTS http error", status=e.response.status_code)
            return
        except Exception as e:
            await ctx.logger.aerror("TTS error", error=str(e))
            return

        # 24kHz float32 -> 16kHz int16
        pcm16 = _resample_pcm(raw, source_sr=24000, target_sr=TARGET_SR)
        if not pcm16:
            return

        # 分块流式输出（循环内检查打断标记——合成完成后被打断则丢弃）
        chunk_size = 1600  # 100ms @ 16kHz
        offset = 0
        while offset < len(pcm16):
            if ctx.run_id is not None and ctx.run_id in self._cancelled_run_ids:
                return
            chunk = pcm16[offset : offset + chunk_size]
            offset += chunk_size
            self._total_samples += len(chunk) // 2
            await ctx.emit(
                Event(
                    type=TTS_AUDIO_DELTA,
                    session_id=ctx.session_id,
                    source="tts.openai-compatible",
                    run_id=ctx.run_id,
                    payload={
                        "pcm_b64": base64.b64encode(chunk).decode("ascii"),
                        "sample_rate": TARGET_SR,
                        "samples": len(chunk) // 2,
                        "text": text,
                    },
                )
            )

    async def reset(self, session_id: str) -> None:
        if self._run_id is not None:
            self._cancelled_run_ids.add(self._run_id)
        self._total_samples = 0
        self._sentence_buffers = {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_env(name: str) -> str:
    import os

    return os.environ.get(name, "")
