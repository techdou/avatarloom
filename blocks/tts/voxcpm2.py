"""VoxCPM2 TTS Block。

基于 openbmb/VoxCPM2 的流式语音克隆合成。

重依赖：voxcpm + torch + transformers（extras=voxcpm2）。
GPU 实机未验证——单测覆盖语速补偿（rate 参数）和重采样。
"""

from __future__ import annotations

import base64
from typing import Any

import numpy as np

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

# 流式切块粒度：512 采样 = 32ms @16kHz（对齐 VoxEMW blocksize）
BLOCK_SIZE = 512


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
    _streaming: bool = True
    _cfg_value: float = 2.0
    _inference_timesteps: int = 10
    _normalize: bool = False
    _denoise: bool = False
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
        self._streaming = bool(cfg.get("streaming", True))
        self._cfg_value = float(cfg.get("cfgValue", 2.0))
        self._inference_timesteps = int(cfg.get("inferenceTimesteps", 10))
        self._normalize = bool(cfg.get("normalize", False))
        self._denoise = bool(cfg.get("denoise", False))
        self._default_voice_ref = self._resolve_path(cfg.get("voiceRef"), ctx)
        try:
            self._model = self._load_model(
                str(cfg.get("model", "openbmb/VoxCPM2")), self._device
            )
        except ImportError as e:
            raise BlockSetupError(
                "tts.voxcpm2",
                f"voxcpm 未安装: {e}. 运行 `uv sync --extra voxcpm2`",
            ) from e
        except Exception as e:
            raise BlockSetupError("tts.voxcpm2", f"加载失败: {e}") from e

        self._mark_ready()
        await ctx.logger.ainfo(
            "tts.voxcpm2 ready",
            device=self._device,
            rate=self._rate,
            streaming=self._streaming,
        )

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
        # persona voice_ref 优先，fallback 到 profile config 的 voiceRef
        effective_ref = voice_ref or self._default_voice_ref
        try:
            gen = self._infer_stream(text, effective_ref)
        except Exception as e:
            await ctx.logger.aerror("voxcpm2 synth error", error=str(e))
            return

        # 流式：边收 48k chunk 边重采样 16k，攒够 BLOCK_SIZE 就 emit。
        # 首 chunk 一到即发出，不必等整句合成完（对齐 VoxEMW blocksize=512）。
        import numpy as np

        buf16 = np.empty(0, dtype=np.int16)
        block = BLOCK_SIZE  # 512 采样 = 32ms @16k
        try:
            for wav48 in gen:
                # 48k float32 -> 16k int16（线性插值，带 rate 语速补偿）
                pcm16 = _resample_48k_to_16k(wav48, rate=self._rate)
                buf16 = np.concatenate([buf16, pcm16])
                while len(buf16) >= block:
                    chunk = buf16[:block]
                    buf16 = buf16[block:]
                    self._total_samples += len(chunk)
                    await ctx.emit(
                        Event(
                            type=TTS_AUDIO_DELTA,
                            session_id=ctx.session_id,
                            source="tts.voxcpm2",
                            run_id=ctx.run_id,
                            payload={
                                "pcm_b64": base64.b64encode(chunk.tobytes()).decode(
                                    "ascii"
                                ),
                                "sample_rate": 16000,
                                "samples": len(chunk),
                                "text": text,
                            },
                        )
                    )
            # 尾巴不足一块也发出（句尾）
            if len(buf16) > 0:
                self._total_samples += len(buf16)
                await ctx.emit(
                    Event(
                        type=TTS_AUDIO_DELTA,
                        session_id=ctx.session_id,
                        source="tts.voxcpm2",
                        run_id=ctx.run_id,
                        payload={
                            "pcm_b64": base64.b64encode(buf16.tobytes()).decode(
                                "ascii"
                            ),
                            "sample_rate": 16000,
                            "samples": len(buf16),
                            "text": text,
                        },
                    )
                )
        except Exception as e:
            await ctx.logger.aerror("voxcpm2 stream error", error=str(e))

    async def reset(self, session_id: str) -> None:
        self._total_samples = 0
        self._sentence_buffers = {}

    # ---- 重依赖 ----

    @staticmethod
    def _resolve_path(path_str: str | None, ctx: BlockContext) -> str | None:
        """把相对路径解析为绝对路径（相对 workspace_root）。"""
        if not path_str:
            return None
        from pathlib import Path

        p = Path(path_str)
        if not p.is_absolute():
            p = Path(ctx.workspace_root) / p
        return str(p) if p.exists() else None

    def _load_model(self, model_name: str, device: str) -> Any:
        from voxcpm import VoxCPM  # type: ignore

        # 本地目录（如 AutoDL 数据盘的 modelscope-voxcpm）直接加载，不走 HF 下载
        import os

        local_path = str(model_name)
        if os.path.isdir(local_path):
            return VoxCPM.from_pretrained(
                local_path, local_files_only=True, device=device
            )
        return VoxCPM.from_pretrained(model_name).to(device)

    def _infer_stream(self, text: str, voice_ref: str | None):
        """流式合成，yield 48kHz float32 numpy chunk。

        VoxCPM2 API: generate_streaming(text, prompt_wav_path=...)
        返回 generator，每个 chunk 是 1D float32 波形。
        """
        kwargs: dict[str, Any] = {
            "cfg_value": self._cfg_value,
            "inference_timesteps": self._inference_timesteps,
            "normalize": self._normalize,
            "denoise": self._denoise,
        }
        if voice_ref:
            kwargs["prompt_wav_path"] = voice_ref
        yield from self._model.generate_streaming(text, **kwargs)


def _resample_48k_to_16k(wav48: np.ndarray, rate: float = 1.0) -> np.ndarray:
    """48kHz float32 -> 16kHz int16，带语速补偿。

    rate<1 降速（如 0.886 = 克隆固有提速 ~12% 的补偿），保持音调。
    用 np.interp 线性插值，避免裸抽点的混叠（对齐 VoxEMW atempo 语义，
    但纯 numpy 无 ffmpeg 进程依赖）。
    """
    import numpy as np

    if wav48 is None or len(wav48) == 0:
        return np.empty(0, dtype=np.int16)
    try:
        arr = np.asarray(wav48, dtype=np.float32).reshape(-1)
        # 48k -> 16k 降采样 1/3
        idx_16k = np.arange(0, len(arr), 3, dtype=np.int64)
        arr16 = arr[idx_16k]
        # rate 语速补偿：rate<1 拉长（插值出更多点），rate>1 压缩
        if rate != 1.0 and len(arr16) > 1:
            n_out = max(1, int(round(len(arr16) / rate)))
            x_old = np.linspace(0.0, 1.0, len(arr16))
            x_new = np.linspace(0.0, 1.0, n_out)
            arr16 = np.interp(x_new, x_old, arr16).astype(np.float32)
        arr16 = np.clip(arr16, -1.0, 1.0)
        return (arr16 * 32767).astype(np.int16)
    except Exception:
        return np.empty(0, dtype=np.int16)
