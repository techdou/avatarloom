#!/bin/bash
# FlashHead 数字人环境搭建（AutoDL RTX 5090）：vendor 克隆 + py310 venv + 权重下载
# 参考 techdou/VoxEMW scripts/autodl_setup.sh；仅取 FlashHead 相关部分。
set -euo pipefail
cd /root/autodl-tmp/avatarloom

export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET=1
export HF_HOME=/root/autodl-tmp/hf

echo "==> [1/4] FlashHead 推理代码"
mkdir -p vendor
if [ ! -d vendor/SoulX-FlashHead/flash_head ]; then
  (source /etc/network_turbo > /dev/null 2>&1 || true; \
   git clone --depth 1 https://github.com/Soul-AILab/SoulX-FlashHead.git vendor/SoulX-FlashHead) || \
  git clone --depth 1 https://gh-proxy.com/https://github.com/Soul-AILab/SoulX-FlashHead.git vendor/SoulX-FlashHead
else
  echo "    已存在，跳过"
fi

echo "==> [2/4] py310 venv + 依赖"
export PATH="/root/miniconda3/bin:$PATH"
source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
if ! conda env list | grep -q "^py310 "; then
  conda create -y -n py310 python=3.10
fi
"$(conda info --base)/envs/py310/bin/python" -m venv /root/autodl-tmp/avatarloom-avatar-venv
source /root/autodl-tmp/avatarloom-avatar-venv/bin/activate
python -m pip install -U pip
if ! python -c "import torch; assert torch.__version__.startswith('2.7')" > /dev/null 2>&1; then
  pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
fi
grep -vE '^(gradio|flask|nvidia-)' vendor/SoulX-FlashHead/requirements.txt > /tmp/fh-req.txt || true
pip install --no-cache-dir -r /tmp/fh-req.txt || echo "WARN: fh requirements partial failure (continue)"
pip install --no-cache-dir websockets pyyaml modelscope opencv-python-headless

echo "==> [3/4] 权重下载（ModelScope 国内高速）"
mkdir -p /root/autodl-tmp/models
modelscope download --model Soul-AILab/SoulX-FlashHead-1_3B \
  --include "Model_Lite/*" "VAE_LTX/*" \
  --local_dir /root/autodl-tmp/models/SoulX-FlashHead-1_3B || echo "WARN: flashhead ms include may differ"
modelscope download --model AI-ModelScope/wav2vec2-base-960h \
  --local_dir /root/autodl-tmp/models/wav2vec2-base-960h

echo "==> [4/4] 完成"
echo FLASHHEAD_SETUP_DONE
