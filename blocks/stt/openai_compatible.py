"""OpenAI-compatible STT Block。

实现 /audio/transcriptions 接口（Whisper 兼容）。

v0.1 简化：收到 speech.ended 后，把累积的音频一次性发去识别（非流式）。
真实场景 Whisper 流式用 chunked 上传，这里先做整段。
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from avatarloom_protocol import (
    AUDIO_APPENDED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements


class OpenAISttBlock(Block):
    """OpenAI-compatible STT（Whisper）。"""

    _base_url: str = "https://api.openai.com/v1"
    _api_key: str = ""
    _model: str = "whisper-1"
    _language: str | None = None
    _timeout: float = 30.0
    # 累积用户音频 PCM（按 session_id）——实例属性，非类属性。
    # 此前挂类属性导致多实例/多会话共享同一 dict，音频互相串扰（sensevoice 已修过同款 bug）。
    _audio_buffers: dict[str, bytearray] | None = None

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="stt.openai-compatible",
            name="OpenAI-compatible STT",
            category="stt",
            runtime_type="http_remote",
            capabilities=Capability(streaming=False),
            inputs=[AUDIO_APPENDED, SPEECH_ENDED],
            outputs=[TRANSCRIPT_COMPLETED],
            resources=ResourceRequirements(),
            config_schema={
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string"},
                    "apiKeyEnv": {"type": "string", "default": "STT_API_KEY"},
                    "model": {"type": "string", "default": "whisper-1"},
                    "language": {"type": "string"},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._base_url = str(cfg.get("baseUrl") or "https://api.openai.com/v1")
        api_key_env = str(cfg.get("apiKeyEnv") or "STT_API_KEY")
        self._api_key = str(cfg.get("apiKey") or _read_env(api_key_env))
        self._model = str(cfg.get("model") or "whisper-1")
        self._language = cfg.get("language") or None
        # 实例级 buffer——fallback 重建/多实例时各自独立，不串扰
        self._audio_buffers = {}
        self._mark_ready()
        await ctx.logger.ainfo("stt.openai-compatible ready", model=self._model)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if self._audio_buffers is None:
            self._audio_buffers = {}
        if event.type == AUDIO_APPENDED:
            # 累积 PCM（base64 -> bytes）
            pcm_b64 = event.payload.get("pcm_b64", "")
            if pcm_b64:
                buf = self._audio_buffers.setdefault(event.session_id, bytearray())
                buf.extend(base64.b64decode(pcm_b64))
        elif event.type == SPEECH_ENDED:
            await self._transcribe(ctx, event)

    async def _transcribe(self, ctx: BlockContext, event: Event) -> None:
        if self._audio_buffers is None:
            return
        buf = self._audio_buffers.pop(event.session_id, bytearray())
        if not buf:
            return

        # PCM16 -> WAV（Whisper 接受 wav/mp3 等格式）
        wav_bytes = _pcm16_to_wav(bytes(buf), 16000)

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            ) as client:
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                data: dict[str, Any] = {"model": self._model, "response_format": "json"}
                if self._language:
                    data["language"] = self._language

                resp = await client.post("/audio/transcriptions", files=files, data=data)
                resp.raise_for_status()
                result = resp.json()
                text = result.get("text", "")
        except httpx.HTTPStatusError as e:
            await ctx.logger.aerror("STT http error", status=e.response.status_code)
            text = ""
        except Exception as e:
            await ctx.logger.aerror("STT error", error=str(e))
            text = ""

        await ctx.emit(
            Event(
                type=TRANSCRIPT_COMPLETED,
                session_id=ctx.session_id,
                source="stt.openai-compatible",
                run_id=ctx.run_id,
                payload={"text": text, "language": self._language, "confidence": 1.0},
            )
        )

    async def reset(self, session_id: str) -> None:
        if self._audio_buffers is not None:
            self._audio_buffers.pop(session_id, None)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_env(name: str) -> str:
    import os

    return os.environ.get(name, "")


def _pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """PCM16 raw -> WAV 容器。"""
    import struct

    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm)
    # RIFF header
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack(
            "<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample
        )
        + b"data"
        + struct.pack("<I", data_size)
        + pcm
    )
