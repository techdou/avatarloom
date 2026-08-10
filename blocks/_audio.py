"""音频工具——PCM/WAV 封装与重采样。

此前 PCM16→WAV 容器封装在三处重复（musetalk / sensevoice / stt.openai_compatible），
float32→int16 降采样也各写一遍（qwen3 / tts.openai_compatible / voxcpm2）。
本模块统一这些纯逻辑工具，调用点 import 使用。

全部为纯 numpy/struct 计算，无外部依赖，可单测。
"""

from __future__ import annotations

import struct

import numpy as np

__all__ = [
    "pcm16_to_wav",
    "resample_float32_to_int16",
    "resample_48k_to_16k",
]


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """PCM16 raw -> WAV 容器（单声道默认）。

    纯 struct 打包，无外部依赖。返回的 bytes 可直接喂 Whisper / FunASR 等接受
    wav 文件的推理接口。空 PCM 也产出合法的空数据段 WAV 头。
    """
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm)
    # RIFF header：注意 "WAVEfmt " 是 "WAVE" + "fmt " 的紧凑写法（字节相同）
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVEfmt "
        + struct.pack(
            "<IHHIIHH",
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
        )
        + b"data"
        + struct.pack("<I", data_size)
        + pcm
    )


def resample_float32_to_int16(raw: bytes, source_sr: int, target_sr: int) -> bytes:
    """float32 PCM bytes -> int16 PCM bytes + 整数倍降采样。

    用于把 24kHz float32（OpenAI TTS / Qwen3-TTS 输出）降到 16kHz int16。
    升采样（source_sr < target_sr）按原样返回 int16（不插值，调用方不依赖此路径）。
    异常或空输入返回 b""。
    """
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


def resample_48k_to_16k(
    wav48: np.ndarray,
    rate: float = 1.0,
    phase: int = 0,
) -> tuple[np.ndarray, int]:
    """48kHz float32 -> 16kHz int16，带语速补偿与跨 chunk 相位连续。

    VoxCPM2 专用（48k 输出 + 克隆固有提速 ~12% 需 rate<1 补偿）。流式切块时
    phase 必须跨 chunk 传递，否则每 chunk 独立从 0 取样，3 的倍数边界处相位
    跳变产生爆音（chunk 长度几乎必然不是 3 的倍数）。

    Args:
        wav48: 单个 48k chunk（float32 1D）。
        rate: 语速补偿系数（<1 拉长，>1 压缩）。
        phase: 降采样相位（已消费 48k 样本数 mod 3）。

    Returns:
        (pcm16, new_phase)：16k int16 数组 + 更新后的相位。
    """
    if wav48 is None or len(wav48) == 0:
        return np.empty(0, dtype=np.int16), phase
    try:
        arr = np.asarray(wav48, dtype=np.float32).reshape(-1)
        n48 = len(arr)
        # 48k -> 16k：从补足相位的偏移开始每 3 取 1，保证跨 chunk 连续。
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
