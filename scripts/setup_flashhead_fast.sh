#!/bin/bash
# FlashHead 精简安装（基于 musetalk-venv，跳过 torch 下载）
# 策略：复用 musetalk-venv 的 torch 2.8.0+cu128，只装 FlashHead 缺的包 + 下权重
# 无卡模式下可安全运行（不碰 CUDA）
set -uo pipefail
cd /root/autodl-tmp/avatarloom

VENV=/root/autodl-tmp/musetalk-venv
PIP="$VENV/bin/pip"
PYTHON="$VENV/bin/python"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
export PIP_RETRIES=20
export PIP_TIMEOUT=120
export PIP_PROGRESS_BAR=off

LOG=/tmp/flashhead_fast_setup.log
echo "==> FlashHead 精简安装 $(date)" | tee "$LOG"

# [1/4] 确认 vendor 代码
if [ ! -d vendor/SoulX-FlashHead/flash_head ]; then
  echo "==> [1/4] 克隆 FlashHead vendor" | tee -a "$LOG"
  mkdir -p vendor
  git clone --depth 1 https://github.com/Soul-AILab/SoulX-FlashHead.git vendor/SoulX-FlashHead >>"$LOG" 2>&1 \
    || git clone --depth 1 https://gh-proxy.com/https://github.com/Soul-AILab/SoulX-FlashHead.git vendor/SoulX-FlashHead >>"$LOG" 2>&1
fi
echo "    vendor OK" | tee -a "$LOG"

# [2/4] 确认 torch 可用（复用 musetalk-venv，不下载）
echo "==> [2/4] torch 状态" | tee -a "$LOG"
$PYTHON -c "import torch; print(f'    torch {torch.__version__} cuda {torch.version.cuda}')" 2>&1 | tee -a "$LOG"

# [3/4] 装 FlashHead 缺的包（阿里云镜像，不装 gradio/flask/nvidia-）
echo "==> [3/4] 安装 FlashHead 缺包（阿里云镜像）" | tee -a "$LOG"
$PIP install --no-cache-dir \
  xformers==0.0.31 xfuser decord loguru easydict ftfy pyloudnorm accelerate \
  >>"$LOG" 2>&1
echo "    pip 缺包安装完成" | tee -a "$LOG"

# [4/4] 下权重（ModelScope 国内 CDN）
echo "==> [4/4] 下载 SoulX + wav2vec2 权重（ModelScope）" | tee -a "$LOG"
mkdir -p /root/autodl-tmp/models
export MODELSCOPE_CACHE=/root/autodl-tmp/modelscope

# SoulX-FlashHead-1.3B（Model_Lite + VAE_LTX）
$PYTHON -m modelscope download --model Soul-AILab/SoulX-FlashHead-1_3B \
  --local_dir /root/autodl-tmp/models/SoulX-FlashHead-1_3B >>"$LOG" 2>&1 \
  || echo "    WARN: SoulX 下载异常（查日志）" | tee -a "$LOG"

# wav2vec2-base-960h
$PYTHON -m modelscope download --model AI-ModelScope/wav2vec2-base-960h \
  --local_dir /root/autodl-tmp/models/wav2vec2-base-960h >>"$LOG" 2>&1 \
  || echo "    WARN: wav2vec2 下载异常（查日志）" | tee -a "$LOG"

echo "==> 完成 $(date)" | tee -a "$LOG"
echo "FLASHHEAD_FAST_DONE" | tee -a "$LOG"
