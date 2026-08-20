#!/usr/bin/env python3
"""pixi.toml 网络修复：conda 渠道换清华镜像 + torch 索引换阿里云 pytorch-wheels。

pixi 0.77 项目清单不收 [mirrors] 表（只认全局 config），渠道 URL 直换最稳。
download.pytorch.org 实测 68KB/s 不可行；阿里云 pytorch-wheels/cu128 实测 ~1.2MB/s。
"""
from pathlib import Path

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
    msg.append("CHANNEL_SWAPPED")

old_idx = 'index = "https://download.pytorch.org/whl/cu128"'
new_idx = 'index = "https://mirrors.aliyun.com/pytorch-wheels/cu128"'
if old_idx in t:
    t = t.replace(old_idx, new_idx, 1)
    msg.append("TORCH_INDEX_SWAPPED")

p.write_text(t.rstrip() + "\n", encoding="utf-8")
print(" ".join(msg) or "NOOP")
