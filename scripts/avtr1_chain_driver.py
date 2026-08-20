#!/usr/bin/env python3
"""AVTR-1 链修复驱动 v3：杀链 → pixi.toml 网络三修 → 重启链。

v3 修复内容：
- conda 渠道 → 清华镜像（已就位则跳过）
- torch 依赖去掉 index=（aliyun pytorch-wheels 是平铺文件列表非 PEP503 索引，
  作 index 会 "torch was not found"）
- 新增 [pypi-options]：index-url 清华 pypi（pypi.org 直连慢）+
  find-links 阿里云 cu128 平铺目录（uv 支持解析 href 列表）
单条短 ssh 可执行；结果写标记文件。
"""
import os
import subprocess
import time
from pathlib import Path

MARK = Path("/root/autodl-tmp/avtr1_driver_mark.txt")

try:
    os.system("pkill -f avtr1_setup_v2; pkill -f 'pixi install'")
    time.sleep(1)

    p = Path("/root/autodl-tmp/avtr-1/pixi.toml")
    t = p.read_text(encoding="utf-8")

    # 清掉历史错误 mirrors 表（若在）
    lines = []
    skip_next = False
    for ln in t.splitlines():
        if ln.strip() == "[mirrors]":
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            if ln.strip().startswith('"https://prefix.dev/conda-forge" ='):
                continue
        lines.append(ln)
    t = "\n".join(lines)

    msg = []
    old_ch = 'channels = ["https://prefix.dev/conda-forge"]'
    new_ch = 'channels = ["https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge"]'
    if old_ch in t:
        t = t.replace(old_ch, new_ch, 1)
        msg.append("CHANNEL")

    old_idx = 'torch = { version = ">=2.5.1,<2.8", index = "https://download.pytorch.org/whl/cu128" }'
    new_torch = 'torch = { version = ">=2.5.1,<2.8" }'
    if old_idx in t:
        t = t.replace(old_idx, new_torch, 1)
        msg.append("TORCH_NO_INDEX")
    elif 'index = "https://mirrors.aliyun.com/pytorch-wheels/cu128"' in t:
        t = t.replace('torch = { version = ">=2.5.1,<2.8", index = "https://mirrors.aliyun.com/pytorch-wheels/cu128" }', new_torch, 1)
        msg.append("TORCH_NO_INDEX")

    if "[pypi-options]" not in t:
        t = t.rstrip() + (
            "\n\n[pypi-options]\n"
            'index-url = "https://pypi.tuna.tsinghua.edu.cn/simple"\n'
            'find-links = [{ url = "https://mirrors.aliyun.com/pytorch-wheels/cu128/" }]\n'
        )
        msg.append("PYPI_OPTIONS")

    p.write_text(t.rstrip() + "\n", encoding="utf-8")

    subprocess.Popen(
        ["bash", "/root/autodl-tmp/avtr1_setup_v2.sh"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
        cwd="/root/autodl-tmp",
    )
    MARK.write_text(f"OK {' '.join(msg)} {time.strftime('%H:%M:%S')}\n", encoding="utf-8")
    print("DRIVER_OK", " ".join(msg))
except Exception as e:  # noqa: BLE001
    MARK.write_text(f"FAIL {e}\n", encoding="utf-8")
    print("DRIVER_FAIL", e)
    raise SystemExit(1)
