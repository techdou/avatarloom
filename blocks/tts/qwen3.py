"""Qwen3-TTS Block。

基于 Qwen3-TTS 0.6B Base 的语音合成。CUDA。

重依赖：torch + transformers + soundfile（extras=qwen3-tts）。
GPU 实机未验证——单测覆盖重采样数学、流式切分逻辑。
"""

from __future__ import annotations

import asyncio
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

from blocks import release_gpu_objects
from blocks._audio import resample_float32_to_int16 as _resample_float32_to_int16

TARGET_SR = 16000

# 向后兼容别名——单测此前从此模块 import resample_pcm。
# 实现已统一到 blocks._audio.resample_float32_to_int16。


def resample_pcm(raw: bytes, source_sr: int, target_sr: int) -> bytes:
    """float32 PCM -> int16 PCM + 降采样（向后兼容包装）。"""
    return _resample_float32_to_int16(raw, source_sr, target_sr)


__all__ = ["Qwen3TtsBlock", "resample_pcm"]


class Qwen3TtsBlock(Block):
    """Qwen3-TTS——流式语音合成 + 音色克隆。"""

    def __init__(self) -> None:
        super().__init__()
        self._model: Any = None
        self._device: str = "cuda"
        self._model_name: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        self._source_sr: int = 24000
        self._default_ref_audio: str | None = None
        self._language: str = "Chinese"
        self._sentence_buffers: dict[int, str] = {}
        self._total_samples: int = 0
        # 按 run 隔离 + 打断协作（同 voxcpm2 模式，见 AL-P2-003 / AL-P1-006）
        self._run_id: str | None = None
        self._cancelled_run_ids: set[str] = set()
        # GPU 推理并发锁——PyTorch 模型非线程安全，asyncio.to_thread 并发推理
        # 会撞显存/状态（同 musetalk._worker_lock 模式）
        self._infer_lock = asyncio.Lock()

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="tts.qwen3",
            name="Qwen3 TTS",
            category="tts",
            runtime_type="python_inproc",
            # streaming=False：当前实现是整句 generate 后切块回放（非真流式）。
            # interruption=False：整句 generate 后才有打断检查，无法真正打断进行中的推理。
            # 诚实声明——此前标 True 但 _infer_stream 不是增量推理、不可中途打断，误导调用方。
            capabilities=Capability(
                streaming=False, voice_cloning=True, interruption=False
            ),
            inputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            outputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            resources=ResourceRequirements(
                accelerator=["cuda", "mlx"],
                estimated_vram_mb=3000,
                pip_extras=["qwen3-tts"],
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": "Qwen/Qwen3-TTS-12Hz-0.6B-Base"},
                    "device": {"type": "string", "default": "cuda"},
                    "quantization": {
                        "type": "string",
                        "enum": ["none", "int8", "int4"],
                        "default": "none",
                    },
                    "sampleRate": {"type": "integer", "default": 16000},
                    "refAudio": {
                        "type": "string",
                        "description": "默认参考音频路径（音色克隆），persona 未设置 voice_ref 时用此默认值",
                    },
                    "language": {
                        "type": "string",
                        "default": "Chinese",
                        "description": "合成语言（Chinese/English/Japanese...）",
                    },
                },
            },
            install_extras=["qwen3-tts"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._model_name = str(cfg.get("model", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"))
        self._device = str(cfg.get("device", "cuda"))
        self._default_ref_audio = str(cfg.get("refAudio", "")) or None
        self._language = str(cfg.get("language", "Chinese"))
        try:
            # 模型加载是重阻塞 IO+初始化——offload 线程，不卡事件循环
            self._model = await asyncio.to_thread(
                self._load_model, self._model_name, self._device
            )
        except ImportError as e:
            raise BlockSetupError(
                "tts.qwen3",
                f"qwen-tts/torch 未安装: {e}. 运行 `uv sync --extra qwen3-tts`",
            ) from e
        except Exception as e:
            raise BlockSetupError("tts.qwen3", f"加载模型失败: {e}") from e

        self._total_samples = 0
        self._sentence_buffers = {}
        self._run_id = None
        self._cancelled_run_ids = set()
        self._mark_ready()
        await ctx.logger.ainfo("tts.qwen3 ready", model=self._model_name, device=self._device)

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
                    source="tts.qwen3",
                    run_id=ctx.run_id,
                    payload={
                        "total_samples": self._total_samples,
                        "duration_ms": int(self._total_samples / TARGET_SR * 1000),
                    },
                )
            )

    async def _synthesize(self, ctx: BlockContext, text: str) -> None:
        try:
            # model.generate 是秒级 GPU/CPU 推理——offload 线程，不阻塞事件循环。
            # 加锁：PyTorch 模型非线程安全，并发 to_thread 推理会撞显存/状态。
            async with self._infer_lock:
                pcm_chunks = await asyncio.to_thread(
                    self._infer_stream, text, ctx.persona_voice_ref
                )
        except Exception as e:
            await ctx.logger.aerror("qwen3 synth error", error=str(e))
            return

        for pcm in pcm_chunks:
            # 打断检查（AL-P1-006）：丢弃已打断 run 的剩余输出
            if ctx.run_id is not None and ctx.run_id in self._cancelled_run_ids:
                return
            # Qwen3-TTS 输出 float32（采样率由模型返回，通常 24kHz），降到 16kHz int16
            source_sr = getattr(self, "_source_sr", 24000)
            pcm16 = _resample_float32_to_int16(pcm, source_sr=source_sr, target_sr=TARGET_SR)
            if not pcm16:
                continue
            chunk_size = 1600
            for i in range(0, len(pcm16), chunk_size * 2):
                chunk = pcm16[i : i + chunk_size * 2]
                self._total_samples += len(chunk) // 2
                await ctx.emit(
                    Event(
                        type=TTS_AUDIO_DELTA,
                        session_id=ctx.session_id,
                        source="tts.qwen3",
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

    async def shutdown(self) -> None:
        """释放模型与显存（HIGH-4 补齐：此前无 shutdown，页面刷新/重连后
        模型常驻显存，torch caching allocator 不归还，多次重连必然 OOM）。
        gc + empty_cache 是阻塞调用——offload 线程执行。"""
        model = self._model
        self._model = None
        self._sentence_buffers = {}
        self._total_samples = 0
        self._run_id = None
        self._cancelled_run_ids.clear()
        holder = [model]
        model = None
        await asyncio.to_thread(release_gpu_objects, holder)

    # ---- 重依赖 ----

    def _load_model(self, model_name: str, device: str) -> Any:
        """加载 Qwen3-TTS 模型（用官方 qwen-tts 包）。

        qwen-tts 自带模型架构注册，不需要 trust_remote_code。
        返回 Qwen3TTSModel 实例（自带 tokenizer/processor）。
        """
        import torch

        from qwen_tts import Qwen3TTSModel

        model = Qwen3TTSModel.from_pretrained(
            model_name,
            device_map=device,
            dtype=torch.bfloat16,
        )
        return model

    def _infer_stream(self, text: str, voice_ref: str | None) -> list[bytes]:
        """合成语音。返回 PCM chunk 列表（原始采样率 float32 numpy）。

        Qwen3-TTS 官方 API：generate_voice_clone(text, language, ref_audio, ref_text)
        返回 (wavs: list[np.ndarray], sr: int)，wavs 元素是 float32 1D 数组。
        """
        import numpy as np

        # ref_audio 优先用 persona voice_ref，其次用 config 的默认参考音频
        # Base 模型用 x_vector_only_mode=True：只需参考音频提取音色向量，不需要 ref_text
        ref_audio = voice_ref or self._default_ref_audio
        wavs, sr = self._model.generate_voice_clone(
            text=text,
            language=self._language,
            ref_audio=ref_audio,
            ref_text=None,
            x_vector_only_mode=True,
        )
        # wavs 是 list[np.ndarray]，取第一个（单说话人）
        if not wavs:
            return []
        audio = np.asarray(wavs[0], dtype=np.float32)
        self._source_sr = sr
        return [audio.tobytes()]
