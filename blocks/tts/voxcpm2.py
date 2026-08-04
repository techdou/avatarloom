"""VoxCPM2 TTS Block。

基于 openbmb/VoxCPM2 的流式语音克隆合成。

重依赖：voxcpm + torch + transformers（extras=voxcpm2）。
GPU 实机未验证——单测覆盖语速补偿（rate 参数）和重采样。
"""

from __future__ import annotations

import base64
from typing import Any

from avatarloom_protocol import (
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import (
    Block,
    BlockContext,
    BlockManifest,
    BlockSetupError,
    Capability,
    ResourceRequirements,
)


class VoxCpm2TtsBlock(Block):
    """VoxCPM2——流式语音克隆。

    参考 VoxEMW tts_voxcpm.py：
    - 48kHz 输出 -> 重采样 16kHz
    - 语速补偿 rate=0.886（克隆固有提速 ~12%，用 ffmpeg atempo 抵消）
    - prompt cache 预编码 persona voice
    """

    _model: Any = None
    _device: str = "cuda"
    _rate: float = 0.886  # 语速补偿
    _voice_caches: dict[str, Any] = {}
    _sentence_buffers: dict[int, str] = {}
    _total_samples: int = 0

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="tts.voxcpm2",
            name="VoxCPM2 TTS",
            category="tts",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=True, voice_cloning=True, interruption=True),
            inputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            outputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            resources=ResourceRequirements(
                accelerator=["cuda"],
                estimated_vram_mb=4000,
                pip_extras=["voxcpm2"],
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": "openbmb/VoxCPM2"},
                    "device": {"type": "string", "default": "cuda"},
                    "rate": {"type": "number", "default": 0.886, "description": "语速补偿"},
                    "streaming": {"type": "boolean", "default": True},
                },
            },
            install_extras=["voxcpm2"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._device = str(cfg.get("device", "cuda"))
        self._rate = float(cfg.get("rate", 0.886))
        try:
            self._model = self._load_model(str(cfg.get("model", "openbmb/VoxCPM2")), self._device)
        except ImportError as e:
            raise BlockSetupError(
                "tts.voxcpm2",
                f"voxcpm 未安装: {e}. 运行 `uv sync --extra voxcpm2`",
            ) from e
        except Exception as e:
            raise BlockSetupError("tts.voxcpm2", f"加载失败: {e}") from e

        self._mark_ready()
        await ctx.logger.ainfo("tts.voxcpm2 ready", device=self._device, rate=self._rate)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type == LLM_TEXT_DELTA:
            idx = event.payload.get("sentence_index", 0)
            text = event.payload.get("text", "")
            is_end = event.payload.get("is_sentence_end", False)
            if text:
                self._sentence_buffers[idx] = self._sentence_buffers.get(idx, "") + text
            if is_end:
                sentence = self._sentence_buffers.pop(idx, "")
                if sentence.strip():
                    await self._synthesize(ctx, sentence, ctx.persona_voice_ref)
        elif event.type == LLM_TEXT_DONE:
            await ctx.emit(
                Event(
                    type=TTS_AUDIO_COMPLETED,
                    session_id=ctx.session_id,
                    source="tts.voxcpm2",
                    run_id=ctx.run_id,
                    payload={
                        "total_samples": self._total_samples,
                        "duration_ms": int(self._total_samples / 16000 * 1000),
                    },
                )
            )

    async def _synthesize(self, ctx: BlockContext, text: str, voice_ref: str | None) -> None:
        try:
            pcm48k = self._infer(text, voice_ref)
        except Exception as e:
            await ctx.logger.aerror("voxcpm2 synth error", error=str(e))
            return

        pcm16 = _resample_48k_to_16k(pcm48k)
        chunk_size = 1600
        for i in range(0, len(pcm16), chunk_size * 2):
            chunk = pcm16[i : i + chunk_size * 2]
            self._total_samples += len(chunk) // 2
            await ctx.emit(
                Event(
                    type=TTS_AUDIO_DELTA,
                    session_id=ctx.session_id,
                    source="tts.voxcpm2",
                    run_id=ctx.run_id,
                    payload={
                        "pcm_b64": base64.b64encode(chunk).decode("ascii"),
                        "sample_rate": 16000,
                        "samples": len(chunk) // 2,
                        "text": text,
                    },
                )
            )

    async def reset(self, session_id: str) -> None:
        self._total_samples = 0
        self._sentence_buffers = {}

    # ---- 重依赖 ----

    def _load_model(self, model_name: str, device: str) -> Any:
        from voxcpm import VoxCPM  # type: ignore

        return VoxCPM.from_pretrained(model_name).to(device)

    def _infer(self, text: str, voice_ref: str | None) -> bytes:
        """合成。voice_ref 是 ref.wav 路径。返回 48kHz float32 PCM。"""
        # 语速补偿通过 ffmpeg atempo（参考 VoxEMW tts_voxcpm.py）
        # 真实实现：self._model.generate(text, prompt_audio=voice_ref, rate=self._rate)
        return self._model.generate(text, prompt_audio=voice_ref, rate=self._rate)


def _resample_48k_to_16k(raw: bytes) -> bytes:
    """48kHz float32 -> 16kHz int16。"""
    import numpy as np

    if not raw:
        return b""
    try:
        arr = np.frombuffer(raw, dtype=np.float32)
        # 48k -> 16k = 每 3 个取 1 个
        arr = arr[::3]
        arr = np.clip(arr, -1.0, 1.0)
        return (arr * 32767).astype(np.int16).tobytes()
    except Exception:
        return b""
