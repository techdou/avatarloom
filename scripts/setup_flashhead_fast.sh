#!/bin/bash
# FlashHead 精简安装（基于 musetalk-venv，跳过 torch 下载）
# 策略：复用 musetalk-venv 的 torch 2.8.0+cu128，只装 FlashHead 缺的包 + 下权重
# 无卡模式下可安全运行（不碰 CUDA）
#
# 幂等——可多次运行：vendor 已克隆跳过、pip 自带去重、权重已下载跳过。
# 失败正确——任一步失败立即非零退出（不再打印"完成"假绿）。
set -euo pipefail

PROJECT_DIR=/root/autodl-tmp/avatarloom
if [ ! -d "$PROJECT_DIR" ]; then
  echo "ERROR: 项目目录 $PROJECT_DIR 不存在——先同步代码再跑本脚本" >&2
  exit 1
fi
cd "$PROJECT_DIR"

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
  rm -rf vendor/SoulX-FlashHead   # 可能有上次失败的残留空目录
  git clone --depth 1 https://github.com/Soul-AILab/SoulX-FlashHead.git vendor/SoulX-FlashHead >>"$LOG" 2>&1 \
    || git clone --depth 1 https://gh-proxy.com/https://github.com/Soul-AILab/SoulX-FlashHead.git vendor/SoulX-FlashHead >>"$LOG" 2>&1 \
    || { echo "ERROR: vendor 克隆失败（直连与 gh-proxy 都失败，查 $LOG）" | tee -a "$LOG"; exit 1; }
fi
echo "    vendor OK" | tee -a "$LOG"

# [2/4] 确认 torch 可用（复用 musetalk-venv，不下载）——venv 缺了后面全白跑，fail fast
echo "==> [2/4] torch 状态" | tee -a "$LOG"
if [ ! -x "$PYTHON" ]; then
  echo "ERROR: $PYTHON 不存在——先建 musetalk-venv 再跑本脚本" | tee -a "$LOG"
  exit 1
fi
$PYTHON -c "import torch; print(f'    torch {torch.__version__} cuda {torch.version.cuda}')" 2>&1 | tee -a "$LOG" \
  || { echo "ERROR: musetalk-venv 里 import torch 失败" | tee -a "$LOG"; exit 1; }

# [3/4] 装 FlashHead 缺的包（阿里云镜像，不装 gradio/flask/nvidia-）
echo "==> [3/4] 安装 FlashHead 缺包（阿里云镜像）" | tee -a "$LOG"
$PIP install --no-cache-dir \
  xformers==0.0.31 xfuser decord loguru easydict ftfy pyloudnorm accelerate \
  >>"$LOG" 2>&1 \
  || { echo "ERROR: pip 缺包安装失败（查 $LOG）" | tee -a "$LOG"; exit 1; }
echo "    pip 缺包安装完成" | tee -a "$LOG"

# [4/4] 下权重（ModelScope 国内 CDN）——目录已有内容则跳过（幂等）
echo "==> [4/4] 下载 SoulX + wav2vec2 权重（ModelScope）" | tee -a "$LOG"
mkdir -p /root/autodl-tmp/models
export MODELSCOPE_CACHE=/root/autodl-tmp/modelscope

download_model() {
  local model_id=$1 dest=$2
  if [ -d "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ]; then
    echo "    ~ $model_id 已存在（$dest 非空），跳过" | tee -a "$LOG"
    return 0
  fi
  $PYTHON -m modelscope download --model "$model_id" \
    --local_dir "$dest" >>"$LOG" 2>&1
}

FAILED=()
# SoulX-FlashHead-1.3B（Model_Lite + VAE_LTX）
download_model Soul-AILab/SoulX-FlashHead-1_3B /root/autodl-tmp/models/SoulX-FlashHead-1_3B \
  || { echo "    ERROR: SoulX 下载失败（查 $LOG，网络恢复后重跑本脚本续传）" | tee -a "$LOG"; FAILED+=("soulx"); }
# wav2vec2-base-960h
download_model AI-ModelScope/wav2vec2-base-960h /root/autodl-tmp/models/wav2vec2-base-960h \
  || { echo "    ERROR: wav2vec2 下载失败（查 $LOG，网络恢复后重跑本脚本续传）" | tee -a "$LOG"; FAILED+=("wav2vec2"); }

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "ERROR: 权重下载失败：${FAILED[*]}——重跑本脚本可续传（幂等）" | tee -a "$LOG"
  exit 1
fi

echo "==> 完成 $(date)" | tee -a "$LOG"
echo "FLASHHEAD_FAST_DONE" | tee -a "$LOG"
