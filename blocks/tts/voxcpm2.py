"""VoxCPM2 TTS Block。

基于 openbmb/VoxCPM2 的流式语音克隆合成。

重依赖：voxcpm + torch + transformers（extras=voxcpm2）。
GPU 实机未验证——单测覆盖语速补偿（rate 参数）和重采样。
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

# 流式切块粒度：512 采样 = 32ms @16kHz（对齐 VoxEMW blocksize）
BLOCK_SIZE = 512
_GENERATOR_DONE = object()


def _next_generator_item(generator: Any) -> Any:
    """在线程中推进同步 generator，避免 StopIteration 穿过 Future。"""
    try:
        return next(generator)
    except StopIteration:
        return _GENERATOR_DONE


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
    _prompt_text: str = ""  # 参考音频对应的文本（与 voiceRef 成对，音色克隆锚点）
    def __init__(self) -> None:
        super().__init__()
        self._model: Any = None
        self._voice_caches: dict[str, Any] = {}
        self._sentence_buffers: dict[int, str] = {}
        self._total_samples = 0
        self._run_id: str | None = None
        self._cancelled_run_ids: set[str] = set()

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
        # 流式切块粒度（32ms @16k = 512），profile 可覆盖
        self._block_size = int(cfg.get("blocksize", BLOCK_SIZE))
        self._default_voice_ref = self._resolve_path(cfg.get("voiceRef"), ctx)
        # 参考音频对应的文本（VoxCPM2 要求 prompt_wav_path+prompt_text 成对）
        self._prompt_text = str(cfg.get("promptText") or cfg.get("stylePrefix") or "")
        try:
            self._model = await asyncio.to_thread(
                self._load_model,
                str(cfg.get("model", "openbmb/VoxCPM2")),
                self._device,
            )
        except ImportError as e:
            raise BlockSetupError(
                "tts.voxcpm2",
                f"voxcpm 未安装: {e}. 运行 `uv sync --extra voxcpm2`",
            ) from e
        except Exception as e:
            raise BlockSetupError("tts.voxcpm2", f"加载失败: {e}") from e

        self._mark_ready()
        # 按 run 隔离的可变状态（AL-P2-003）+ 打断协作标记（AL-P1-006）。
        self._run_id = None
        self._cancelled_run_ids.clear()
        self._sentence_buffers = {}
        self._total_samples = 0
        await ctx.logger.ainfo(
            "tts.voxcpm2 ready",
            device=self._device,
            rate=self._rate,
            streaming=self._streaming,
        )

    def _sync_run_state(self, ctx: BlockContext) -> bool:
        """按 run 隔离状态；返回 True 表示本 run 已被打断（调用方应直接 return）。

        - run_id 变化（新一轮）→ 清零 total_samples/sentence_buffers（AL-P2-003：
          此前只在 reset 清零，正常完成一轮后累计到下一轮）
        - run_id 在 cancelled 集合（打断后旧 run 的迟到事件）→ 丢弃（AL-P1-006）
        """
        if ctx.run_id != self._run_id:
            self._total_samples = 0
            self._sentence_buffers = {}
            self._run_id = ctx.run_id
        return ctx.run_id is not None and ctx.run_id in self._cancelled_run_ids

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if self._sync_run_state(ctx):
            return
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
            # 句尾剩余合成：回复没有句末标点时（is_sentence_end 始终 False），
            # 缓冲内容此前被直接丢弃——TTS 零产出（E2E 实测 tts_delta=False 的真因）
            pending = sorted(self._sentence_buffers.items())
            self._sentence_buffers = {}
            for _idx, sentence in pending:
                if sentence.strip():
                    await self._synthesize(ctx, sentence, ctx.persona_voice_ref)
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
        block = self._block_size  # 512 采样 = 32ms @16k（profile 可配）
        phase = 0  # 跨 chunk 降采样相位（防边界爆音）
        try:
            while True:
                # 每次推进同步 generator 都放到线程，GPU 推理不会卡住事件循环。
                wav48 = await asyncio.to_thread(_next_generator_item, gen)
                if wav48 is _GENERATOR_DONE:
                    break
                # 打断检查：当前 chunk 完成后立即丢弃后续输出。
                if ctx.run_id is not None and ctx.run_id in self._cancelled_run_ids:
                    return
                # 48k float32 -> 16k int16（线性插值，带 rate 语速补偿 + 相位连续）
                pcm16, phase = _resample_48k_to_16k(wav48, rate=self._rate, phase=phase)
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
        # 标记当前 run 已打断（AL-P1-006）——进行中的推理循环检查后丢弃输出
        if self._run_id is not None:
            self._cancelled_run_ids.add(self._run_id)
        self._total_samples = 0
        self._sentence_buffers = {}

    async def shutdown(self) -> None:
        """清空会话状态，并在线程中释放模型与 CUDA 缓存。"""
        model = self._model
        self._model = None
        self._voice_caches.clear()
        self._sentence_buffers.clear()
        self._cancelled_run_ids.clear()
        self._run_id = None
        self._total_samples = 0
        holder = [model]
        model = None
        await asyncio.to_thread(release_gpu_objects, holder)

    # ---- 重依赖 ----

    @staticmethod
    def _resolve_path(path_str: str | None, ctx: BlockContext) -> str | None:
        """把相对路径解析为绝对路径（相对 workspace_root）。

        文件不存在时记 warning 而非静默 None——缺失 voiceRef 会导致
        克隆无参考音，合成失败且难排查。
        """
        if not path_str:
            return None
        from pathlib import Path

        p = Path(path_str)
        if not p.is_absolute():
            p = Path(ctx.workspace_root) / p
        if not p.exists():
            import logging

            logging.getLogger("tts.voxcpm2").warning(
                "voiceRef 不存在: %s（音色克隆将退化为默认音色）", p
            )
            return None
        return str(p)

    def _load_model(self, model_name: str, device: str) -> Any:
        # voxcpm 1.0.5 API：VoxCPM(voxcpm_model_path, ..., optimize)——无 device 参数，
        # 设备由库内部自选（cuda 可用即上卡）。from_pretrained 的 **kwargs 直达
        # __init__，传 device 会 TypeError。device 参数保留作语义记录。
        import os

        from voxcpm import VoxCPM

        local_path = str(model_name)
        if os.path.isdir(local_path):
            # 本地目录（如 AutoDL 数据盘的 modelscope-voxcpm）直接加载，不走 HF 下载
            return VoxCPM.from_pretrained(local_path, local_files_only=True)
        return VoxCPM.from_pretrained(model_name)

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
            # VoxCPM2 要求 prompt_wav_path 与 prompt_text 成对（音色克隆语义锚点）
            kwargs["prompt_wav_path"] = voice_ref
            kwargs["prompt_text"] = self._prompt_text
        yield from self._model.generate_streaming(text, **kwargs)


def _resample_48k_to_16k(
    wav48: np.ndarray,
    rate: float = 1.0,
    phase: int = 0,
) -> tuple[np.ndarray, int]:
    """48kHz float32 -> 16kHz int16，带语速补偿与跨 chunk 相位连续。

    rate<1 降速（如 0.886 = 克隆固有提速 ~12% 的补偿），保持音调。
    用 np.interp 线性插值，避免裸抽点的混叠（对齐 VoxEMW atempo 语义，
    但纯 numpy 无 ffmpeg 进程依赖）。

    Args:
        wav48: 单个 48k chunk（float32 1D）。
        rate: 语速补偿系数。
        phase: 降采样相位（已消费 48k 样本数 mod 3）。流式时必须跨 chunk
            传递，否则每 chunk 独立从 0 取样，边界处相位跳变产生爆音
            （chunk 长度几乎必然不是 3 的倍数）。

    Returns:
        (pcm16, new_phase)：16k int16 数组 + 更新后的相位。
    """
    import numpy as np

    if wav48 is None or len(wav48) == 0:
        return np.empty(0, dtype=np.int16), phase
    try:
        arr = np.asarray(wav48, dtype=np.float32).reshape(-1)
        n48 = len(arr)
        # 48k -> 16k：从补足相位的偏移开始每 3 取 1，保证跨 chunk 连续。
        # phase = 已消费 48k 样本数 mod 3；本 chunk 需跳过 (3-phase)%3 个样本
        # 使取样网格对齐绝对时间轴（整段与分块等价）。
        skip = (3 - phase) % 3
        idx_16k = np.arange(skip, n48, 3, dtype=np.int64)
        arr16 = arr[idx_16k]
        new_phase = (phase + n48) % 3
        # rate 语速补偿：rate<1 拉长（插值出更多点），rate>1 压缩
        if rate != 1.0 and len(arr16) > 1:
            n_out = max(1, round(len(arr16) / rate))
            x_old = np.linspace(0.0, 1.0, len(arr16))
            x_new = np.linspace(0.0, 1.0, n_out)
            arr16 = np.interp(x_new, x_old, arr16).astype(np.float32)
        arr16 = np.clip(arr16, -1.0, 1.0)
        return (arr16 * 32767).astype(np.int16), new_phase
    except Exception:
        return np.empty(0, dtype=np.int16), phase
