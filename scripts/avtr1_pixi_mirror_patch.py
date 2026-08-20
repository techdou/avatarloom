#!/usr/bin/env python3
"""给 avtr-1 的 pixi.toml 加清华 conda 镜像（prefix.dev 直连被重置）。"""
from pathlib import Path

p = Path("/root/autodl-tmp/avtr-1/pixi.toml")
t = p.read_text(encoding="utf-8")
if "[mirrors]" in t:
    print("MIRROR_EXISTS")
else:
    old = 'channels = ["https://prefix.dev/conda-forge"]'
    new = (
        'channels = ["https://prefix.dev/conda-forge"]\n\n'
        "[mirrors]\n"
        '"https://prefix.dev/conda-forge" = '
        '["https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge"]'
    )
    if old not in t:
        print("CHANNEL_LINE_NOT_FOUND")
        raise SystemExit(1)
    p.write_text(t.replace(old, new, 1), encoding="utf-8")
    print("MIRROR_ADDED")
