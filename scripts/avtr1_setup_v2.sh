#!/bin/bash
# AVTR-1 sm120 验证链 v2：pixi → install → 下权重 → 编译 TRT 引擎
# v2 变更：去掉 network_turbo（只加速 github/HF，会把 conda/pip 拖死）；
#         conda 走清华镜像（pixi.toml [mirrors]）；pypi 走清华镜像（UV_INDEX_URL）；
#         HF 走 hf-mirror.com（无需 turbo）。
# nohup 防 SSH 断；每步打标记，失败即停留下现场。
set -uo pipefail
exec > >(tee -a /root/autodl-tmp/avtr1_setup.log) 2>&1
echo "=== [0] $(date +%T) start v2 ==="
export AVTR1_LOCAL_STORAGE=/root/autodl-tmp/avtr1_storage
export HF_ENDPOINT=https://hf-mirror.com
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

echo "=== [1] pixi ==="
if ! command -v pixi >/dev/null 2>&1; then
  # pixi 安装包在 github releases——turbo 只在shell里临时开给这一行
  (source /etc/network_turbo 2>/dev/null; curl -fsSL https://pixi.sh/install.sh | sh) || { echo "FAIL_PIXI_INSTALL"; exit 1; }
fi
export PATH="$HOME/.pixi/bin:$PATH"
pixi --version || { echo "FAIL_PIXI"; exit 1; }

cd /root/autodl-tmp/avtr-1
echo "=== [2] env solve+install（renderer，清华镜像）==="
pixi install || { echo "FAIL_PIXI_PROJECT_INSTALL"; exit 1; }

echo "=== [3] download artifacts（hf-mirror 匿名直下，公共仓）==="
pixi run python scripts/download_artifacts.py || { echo "FAIL_DOWNLOAD"; exit 1; }

echo "=== [4] build TRT engines（sm120，最长步骤）==="
pixi run build-trt-engines || { echo "FAIL_BUILD"; exit 1; }
echo "=== [5] ALL_DONE ==="
