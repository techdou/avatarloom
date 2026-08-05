#!/bin/bash
# FlashHead 安装第二阶段:torch 已下载为本地 wheel,本脚本装剩余依赖 + 下权重
# 前置:torch wheel 已在 /root/autodl-tmp/wheels/
# 用法:bash scripts/flashhead_install_phase2.sh
set -euo pipefail
cd /root/autodl-tmp/avatarloom

VENV=/root/autodl-tmp/avatarloom-avatar-venv
PIP="$VENV/bin/pip install --no-cache-dir --retries 20 --timeout 120 --progress-bar off"
WHEEL_DIR=/root/autodl-tmp/wheels

echo "==> [1/4] 本地安装 torch wheel(跳过网络)"
TORCH_WHL=$(ls $WHEEL_DIR/torch-2.7.1+cu128-*.whl 2>/dev/null | head -1)
if [ -z "$TORCH_WHL" ]; then
  echo "FATAL: torch wheel not found in $WHEEL_DIR"
  exit 1
fi
echo "    using: $TORCH_WHL"
# 先装 torch 本体,再补 torchvision/torchaudio(仍需从 pytorch.org,但小得多)
$PIP "$TORCH_WHL"
$PIP --index-url https://download.pytorch.org/whl/cu128 \
  torchvision==0.22.1 torchaudio==2.7.1 || echo "WARN: torchvision/audio install partial"

echo "==> [2/4] FlashHead requirements"
grep -vE '^(gradio|flask|nvidia-|torch==|torchvision|torchaudio)' \
  vendor/SoulX-FlashHead/requirements.txt > /tmp/fh-req.txt 2>/dev/null || true
$PIP -r /tmp/fh-req.txt || echo "WARN: fh requirements partial failure (continue)"
$PIP websockets pyyaml modelscope opencv-python-headless

echo "==> [3/4] 权重下载(ModelScope 国内高速)"
mkdir -p /root/autodl-tmp/models
export HF_ENDPOINT=https://hf-mirror.com
$VENV/bin/modelscope download --model Soul-AILab/SoulX-FlashHead-1_3B \
  --include "Model_Lite/*" "VAE_LTX/*" "config.json" "model_index.json" \
  --local_dir /root/autodl-tmp/models/SoulX-FlashHead-1_3B \
  || echo "WARN: SoulX download may need retry"
$VENV/bin/modelscope download --model AI-ModelScope/wav2vec2-base-960h \
  --local_dir /root/autodl-tmp/models/wav2vec2-base-960h \
  || echo "WARN: wav2vec2 download may need retry"

echo "==> [4/4] 验证"
echo "torch:"; $VENV/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
echo "models:"; du -sh /root/autodl-tmp/models/SoulX-FlashHead-1_3B /root/autodl-tmp/models/wav2vec2-base-960h 2>/dev/null
echo "FLASHHEAD_SETUP_DONE"
