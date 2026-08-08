"""Silero VAD Block。

基于 silero-vad（torch hub）的语音活动检测。

重依赖：torch（extras=silero）。本机无 GPU/CPU torch 时 import 失败，
Orchestrator 会降级到 vad.mock 或标记此 Block 缺席。

GPU 实机未验证——单测覆盖纯逻辑分支（chunk 边界、置信度阈值、状态机）。
真实推理需 `uv sync --extra silero` + 模型文件。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from avatarloom_protocol import (
    AUDIO_APPENDED,
    SPEECH_DETECTED,
    SPEECH_ENDED,
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

# Silero VAD 默认参数（来自官方 get_number_of_samples）
_DEFAULT_THRESHOLD = 0.5
_DEFAULT_MIN_SILENCE_MS = 500
_SAMPLE_RATE = 16000


class SileroVadBlock(Block):
    """Silero VAD——基于神经网络的语音活动检测。"""

    _threshold: float = _DEFAULT_THRESHOLD
    _min_silence_samples: int = 0
    _model: Any = None  # torch.jit.ScriptModule，运行时加载
    _h: Any = None  # LSTM hidden state
    _forward_has_state: bool = True  # 探测 forward 签名（见 _load_model）
    _is_speaking: bool = False
    _silence_count: int = 0

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="vad.silero",
            name="Silero VAD",
            category="vad",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=False),
            inputs=[AUDIO_APPENDED],
            outputs=[SPEECH_DETECTED, SPEECH_ENDED],
            resources=ResourceRequirements(
                accelerator=["cpu", "cuda"],
                estimated_ram_mb=200,
                pip_extras=["silero"],
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "threshold": {"type": "number", "default": 0.5},
                    "minSilenceMs": {"type": "integer", "default": 500},
                    "device": {"type": "string", "enum": ["cpu", "cuda"], "default": "cpu"},
                },
            },
            install_extras=["silero"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._threshold = float(cfg.get("threshold", _DEFAULT_THRESHOLD))
        silence_ms = int(cfg.get("minSilenceMs", _DEFAULT_MIN_SILENCE_MS))
        self._min_silence_samples = int(_SAMPLE_RATE * silence_ms / 1000)

        device = str(cfg.get("device", "cpu"))
        try:
            self._model, _utils = self._load_model(device)
            self._h = None
        except ImportError as e:
            raise BlockSetupError(
                "vad.silero",
                f"silero-vad 依赖未安装: {e}. "
                f"运行 `uv sync --extra silero` 安装，或用 vad.mock 替代",
            ) from e
        except Exception as e:
            raise BlockSetupError(
                "vad.silero",
                f"加载 silero 模型失败: {e}. 检查网络（首次需从 torch.hub 下载）",
            ) from e

        self._is_speaking = False
        self._silence_count = 0
        self._mark_ready()
        await ctx.logger.ainfo("vad.silero ready", device=device, threshold=self._threshold)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type != AUDIO_APPENDED:
            return

        pcm_b64 = event.payload.get("pcm_b64", "")
        if not pcm_b64:
            return

        pcm = self._decode_pcm(pcm_b64)
        # Silero 要求 512 samples（16kHz）为一个 chunk
        for chunk in self._chunk(pcm, 512):
            prob, self._h = self._infer(chunk, self._h)
            await self._update_state(ctx, prob)

    async def _update_state(self, ctx: BlockContext, prob: float) -> None:
        if not self._is_speaking:
            if prob >= self._threshold:
                self._is_speaking = True
                self._silence_count = 0
                await ctx.emit(
                    Event(
                        type=SPEECH_DETECTED,
                        session_id=ctx.session_id,
                        source="vad.silero",
                        run_id=ctx.run_id,
                        payload={"confidence": prob},
                    )
                )
        else:
            if prob < self._threshold:
                self._silence_count += 512
                if self._silence_count >= self._min_silence_samples:
                    self._is_speaking = False
                    self._silence_count = 0
                    await ctx.emit(
                        Event(
                            type=SPEECH_ENDED,
                            session_id=ctx.session_id,
                            source="vad.silero",
                            run_id=ctx.run_id,
                            payload={"duration_ms": 0},
                        )
                    )
            else:
                self._silence_count = 0

    async def reset(self, session_id: str) -> None:
        self._is_speaking = False
        self._silence_count = 0
        self._h = None

    # ---- 纯逻辑 helpers（可单测，不依赖 torch）----

    @staticmethod
    def _decode_pcm(pcm_b64: str) -> np.ndarray:
        """base64 PCM16 -> float32 numpy [-1, 1]。"""
        import base64

        raw = base64.b64decode(pcm_b64)
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return arr

    @staticmethod
    def _chunk(arr: np.ndarray, size: int) -> list[np.ndarray]:
        """按 size 切分（末尾不足 size 的丢弃——Silero 要求固定长度）。"""
        n = len(arr) // size
        return [arr[i * size : (i + 1) * size] for i in range(n)]

    # ---- 重依赖方法（运行时 import torch）----

    def _load_model(self, device: str) -> tuple[Any, Any]:
        """加载 silero 模型。运行时 import torch。

        优先本地 hub 缓存（source="local"，零网络校验）：AutoDL 到 GitHub 不稳定，
        在线 torch.hub.load 会做版本校验而挂起（Remote end closed / timeout）。
        缓存目录约定：$TORCH_HOME/hub/snakers4_silero-vad_master/（预置 repo + jit）。
        """
        import logging
        import os

        import torch

        # torch.hub.get_dir() 同时尊重 TORCH_HOME 与 XDG_CACHE_HOME，与 torch 实际
        # 缓存语义一致（不要手写 ~/.cache/torch 回退——设了 XDG 时探针会错位）。
        hub_cache = os.path.join(torch.hub.get_dir(), "hub", "snakers4_silero-vad_master")
        if os.path.isdir(hub_cache):
            logging.getLogger("vad.silero").info("silero 模型从本地 hub 缓存加载: %s", hub_cache)
            model, utils = torch.hub.load(
                repo_or_dir=hub_cache,
                model="silero_vad",
                source="local",
                trust_repo=True,
                onnx=False,
            )
        else:
            # 在线模式（本地无缓存时从 GitHub 下载）
            logging.getLogger("vad.silero").warning(
                "silero 本地缓存缺失（%s），走在线 torch.hub 下载——AutoDL 上可能挂起", hub_cache
            )
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
                onnx=False,
            )
        model.to(device)
        # 试跑探测 forward 签名：JIT 模型 inspect 拿不到真实签名（返回含 self 的
        # 占位参数），只能用静音 chunk 试调用判断是 (x, sr) 还是 (x, sr, h)。
        # 用 try/except TypeError 区分——JIT 版本缺参/多参都会抛 RuntimeError。
        import torch as _t

        probe = _t.zeros(1, 512)
        try:
            with _t.no_grad():
                model(probe, _SAMPLE_RATE)  # 2 参：新版 JIT（状态内部管理）
            self._forward_has_state = False
        except Exception:
            self._forward_has_state = True  # 3 参：旧版（返回 (out, h)）
        return model, utils

    def _infer(self, chunk: np.ndarray, h: Any) -> tuple[float, Any]:
        """单次推理。返回 (prob, new_hidden_state)。

        Silero VAD 的 forward 签名随版本而异：
        - 旧版/官方 torch 版：forward(x, sr, h) → (out, h)
        - 新版（JIT merge）：forward(x, sr) → out（状态内部管理）
        加载时探测签名，按版本调用。
        """
        import torch

        t = torch.from_numpy(chunk).unsqueeze(0)
        with torch.no_grad():
            if self._forward_has_state:
                out, h = self._model(t, _SAMPLE_RATE, h)
            else:
                out = self._model(t, _SAMPLE_RATE)
                h = None  # 状态由模型内部管理，外部无需维护
        return float(out.item()), h
