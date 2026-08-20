#!/usr/bin/env python3
"""实测 VoxCPM2 在 timesteps=10 下的 TTFA/RTF（2026-08-21 对齐 VoxEMW 推荐值后）。

用法（服务器）：/root/autodl-tmp/avatarloom/.venv/bin/python /root/autodl-tmp/measure_tts_rtf.py
"""
import sys
import time

import numpy as np

sys.path.insert(0, "/root/autodl-tmp/avatarloom")

from voxcpm import VoxCPM  # noqa: E402

TEXT = "你好呀，我是小灵。今天想聊点什么？这个问题还挺有意思的，让我认真想一下再回答你。"

model = VoxCPM.from_pretrained("/root/autodl-tmp/modelscope-voxcpm", local_files_only=True)

t0 = time.perf_counter()
first = None
total = 0
for wav in model.generate_streaming(
    TEXT,
    prompt_wav_path="/root/autodl-tmp/avatarloom/personas/demo-assistant/voice/ref.wav",
    prompt_text="你好，很高兴认识你。今天过得怎么样？",
    cfg_value=2.0,
    inference_timesteps=10,
    normalize=True,
    denoise=False,
):
    arr = wav.squeeze(0).cpu().numpy() if hasattr(wav, "cpu") else wav
    n = len(np.atleast_1d(arr))
    if n and first is None:
        first = time.perf_counter() - t0
    total += n

gen = time.perf_counter() - t0
audio = total / 48000.0
print(f"RESULT TTFA={first:.2f}s audio={audio:.2f}s gen={gen:.2f}s RTF={gen/audio:.2f}")
