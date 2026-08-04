"""SenseVoice STT Block（FunASR）。

基于 FunASR SenseVoiceSmall 的语音识别。CPU/CUDA 双模式。

重依赖：funasr + torch + modelscope（extras=sensevoice）。
GPU 实机未验证——单测覆盖 WAV 构造、状态机分支。
"""

from __future__ import annotations

import base64
from typing import Any

from avatarloom_protocol import (
    AUDIO_APPENDED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
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


class SenseVoiceSttBlock(Block):
    """SenseVoice STT——FunASR 多语种 ASR。"""

    _model: Any = None
    _device: str = "cpu"
    _language: str = "zh"
    _audio_buffers: dict[str, bytearray] = {}

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="stt.sensevoice",
            name="SenseVoice STT",
            category="stt",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=False, languages=["zh", "en", "ja", "ko"]),
            inputs=[AUDIO_APPENDED, SPEECH_ENDED],
            outputs=[TRANSCRIPT_COMPLETED],
            resources=ResourceRequirements(
                accelerator=["cpu", "cuda"],
                estimated_vram_mb=1500,
                estimated_ram_mb=2000,
                pip_extras=["sensevoice"],
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": "iic/SenseVoiceSmall"},
                    "device": {"type": "string", "enum": ["cpu", "cuda"], "default": "cpu"},
                    "language": {"type": "string", "default": "zh"},
                },
            },
            install_extras=["sensevoice"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._device = str(cfg.get("device", "cpu"))
        self._language = str(cfg.get("language", "zh"))
        model_name = str(cfg.get("model", "iic/SenseVoiceSmall"))

        try:
            self._model = self._load_model(model_name, self._device)
        except ImportError as e:
            raise BlockSetupError(
                "stt.sensevoice",
                f"funasr 依赖未安装: {e}. 运行 `uv sync --extra sensevoice`",
            ) from e
        except Exception as e:
            raise BlockSetupError(
                "stt.sensevoice",
                f"加载模型失败: {e}. 首次需从 ModelScope/HF 下载",
            ) from e

        self._mark_ready()
        await ctx.logger.ainfo("stt.sensevoice ready", device=self._device, lang=self._language)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type == AUDIO_APPENDED:
            pcm_b64 = event.payload.get("pcm_b64", "")
            if pcm_b64:
                buf = self._audio_buffers.setdefault(event.session_id, bytearray())
                buf.extend(base64.b64decode(pcm_b64))
        elif event.type == SPEECH_ENDED:
            await self._transcribe(ctx, event)

    async def _transcribe(self, ctx: BlockContext, event: Event) -> None:
        buf = self._audio_buffers.pop(event.session_id, bytearray())
        if not buf:
            return
        wav_bytes = pcm16_to_wav(bytes(buf), 16000)
        try:
            text, tags = self._infer(wav_bytes)
        except Exception as e:
            await ctx.logger.aerror("sensevoice infer error", error=str(e))
            text, tags = "", {}

        await ctx.emit(
            Event(
                type=TRANSCRIPT_COMPLETED,
                session_id=ctx.session_id,
                source="stt.sensevoice",
                run_id=ctx.run_id,
                payload={"text": text, "language": self._language, "confidence": 1.0, "tags": tags},
            )
        )

    async def reset(self, session_id: str) -> None:
        self._audio_buffers.pop(session_id, None)

    # ---- 重依赖 ----

    def _load_model(self, model_name: str, device: str) -> Any:
        from funasr import AutoModel

        return AutoModel(
            model=model_name,
            trust_remote_code=True,
            device=device,
            disable_update=True,
        )

    def _infer(self, wav_bytes: bytes) -> tuple[str, dict[str, str]]:
        """推理。SenseVoice 返回 text + 情绪/语种标签。"""
        import os
        import tempfile

        # FunASR 接受文件路径
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            result = self._model.generate(
                input=tmp_path,
                language=self._language,
                use_itn=True,
            )
        finally:
            os.unlink(tmp_path)
        # SenseVoice 输出格式：<|zh|><|HAPPY|><|Speech|><|woitn|>实际文本
        raw = result[0]["text"] if result else ""
        text, tags = parse_sensevoice_output(raw)
        return text, tags


# ---------------------------------------------------------------------------
# helpers（纯逻辑，可单测）
# ---------------------------------------------------------------------------


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """PCM16 raw -> WAV 容器。"""
    import struct

    bits = 16
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


def parse_sensevoice_output(raw: str) -> tuple[str, dict[str, str]]:
    """解析 SenseVoice 输出：'<|zh|><|HAPPY|><|Speech|><|woitn|>你好' -> ('你好', {'lang': 'zh', 'emotion': 'HAPPY'})。

    纯逻辑——可单测。
    """
    import re

    tags: dict[str, str] = {}
    text = raw
    # 提取所有 <|tag|>
    for m in re.finditer(r"<\|([^|]+)\|>", text):
        tag = m.group(1)
        # 分类：语种（zh/en/ja/ko/...）、情绪（HAPPY/SAD/ANGRY/NEUTRAL）、类型（Speech）
        if tag.lower() in ("zh", "en", "ja", "ko", "auto"):
            tags["language"] = tag.lower()
        elif tag.upper() in ("HAPPY", "SAD", "ANGRY", "NEUTRAL"):
            tags["emotion"] = tag.upper()
        else:
            tags[tag.lower()] = tag
    # 去掉所有标签
    text = re.sub(r"<\|[^|]+\|>", "", text).strip()
    return text, tags
