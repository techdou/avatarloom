"""Qwen3-TTS Block。

基于 Qwen3-TTS 0.6B Base 的语音合成。CUDA。

重依赖：torch + transformers + soundfile（extras=qwen3-tts）。
GPU 实机未验证——单测覆盖重采样数学、流式切分逻辑。
"""

from __future__ import annotations

import asyncio
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

from blocks import release_gpu_objects

TARGET_SR = 16000


class Qwen3TtsBlock(Block):
    """Qwen3-TTS——流式语音合成 + 音色克隆。"""

    def __init__(self) -> None:
        super().__init__()
        # 实例级状态——_voice_cache 此前挂类属性，多实例/重建时共享串扰
        self._model: Any = None
        self._tokenizer: Any = None
        self._device: str = "cuda"
        self._model_name: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        self._voice_cache: dict[str, Any] = {}  # persona_id -> 预编码 voice prompt
        self._sentence_buffers: dict[int, str] = {}
        self._total_samples: int = 0
        # 按 run 隔离 + 打断协作（同 voxcpm2 模式，见 AL-P2-003 / AL-P1-006）
        self._run_id: str | None = None
        self._cancelled_run_ids: set[str] = set()

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="tts.qwen3",
            name="Qwen3 TTS",
            category="tts",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=True, voice_cloning=True, interruption=True),
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
                },
            },
            install_extras=["qwen3-tts"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._model_name = str(cfg.get("model", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"))
        self._device = str(cfg.get("device", "cuda"))
        try:
            # 模型加载是重阻塞 IO+初始化——offload 线程，不卡事件循环
            self._tokenizer, self._model = await asyncio.to_thread(
                self._load_model, self._model_name, self._device
            )
        except ImportError as e:
            raise BlockSetupError(
                "tts.qwen3",
                f"transformers/torch 未安装: {e}. 运行 `uv sync --extra qwen3-tts`",
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
            # model.generate 是秒级 GPU/CPU 推理——offload 线程，不阻塞事件循环
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
            # Qwen3-TTS 输出 24kHz，降到 16kHz
            pcm16 = resample_pcm(pcm, source_sr=24000, target_sr=TARGET_SR)
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
        tokenizer = self._tokenizer
        self._model = None
        self._tokenizer = None
        self._voice_cache.clear()
        self._sentence_buffers = {}
        self._total_samples = 0
        self._run_id = None
        self._cancelled_run_ids.clear()
        holder = [model, tokenizer]
        model = None
        tokenizer = None
        await asyncio.to_thread(release_gpu_objects, holder)

    # ---- 重依赖 ----

    def _load_model(self, model_name: str, device: str) -> tuple[Any, Any]:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_name, trust_remote_code=True, torch_dtype=torch.bfloat16
        ).to(device)
        model.eval()
        return tokenizer, model

    def _infer_stream(self, text: str, voice_ref: str | None) -> list[bytes]:
        """流式合成。返回 PCM chunk 列表（24kHz float32）。"""
        import torch

        # 简化版——真实实现参考 Qwen3-TTS 官方 demo
        inputs = self._tokenizer(text, return_tensors="pt").to(self._device)
        with torch.no_grad():
            audio = self._model.generate(**inputs, voice=voice_ref)
        return [audio.cpu().numpy().tobytes()]


# ---------------------------------------------------------------------------
# helpers（纯逻辑，可单测）
# ---------------------------------------------------------------------------


def resample_pcm(raw: bytes, source_sr: int, target_sr: int) -> bytes:
    """float32 PCM -> int16 PCM + 降采样（同 openai_compatible 的实现，独立便于单测）。"""
    if not raw or len(raw) < 4:
        return b""
    try:
        arr = np.frombuffer(raw, dtype=np.float32)
        ratio = source_sr / target_sr
        if ratio > 1:
            n_out = int(len(arr) / ratio)
            indices = np.linspace(0, len(arr) - 1, n_out).astype(int)
            arr = arr[indices]
        arr = np.clip(arr, -1.0, 1.0)
        return (arr * 32767).astype(np.int16).tobytes()
    except Exception:
        return b""
