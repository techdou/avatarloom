#!/bin/bash
# GPU 模式切换后的一键验证脚本
# 用法: bash scripts/verify_after_gpu.sh
set -euo pipefail
cd /root/autodl-tmp/avatarloom

export PATH="$HOME/.local/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
export HF_HOME=/root/autodl-tmp/huggingface MODELSCOPE_CACHE=/root/autodl-tmp/modelscope TORCH_HOME=/root/autodl-tmp/torch
set -a; . ./.env; set +a

echo "========== [1] 停旧服务 =========="
bash scripts/autodl_start.sh stop 2>/dev/null || true
pkill -f 'avatarloom_control_api|avatarloom_runtime_gateway' 2>/dev/null || true
sleep 2

echo "========== [2] 启动三服务 =========="
setsid nohup env \
  HF_ENDPOINT="$HF_ENDPOINT" HF_HUB_DISABLE_XET=1 \
  HF_HOME="$HF_HOME" MODELSCOPE_CACHE="$MODELSCOPE_CACHE" TORCH_HOME="$TORCH_HOME" \
  PATH="$PATH" \
  bash scripts/autodl_start.sh start \
  </dev/null >/tmp/avatarloom_start.log 2>&1 &
echo "等待服务启动..."
sleep 15

echo "========== [3] 端口检查 =========="
for port in 8100 8101 3000; do
  printf "port %s: " $port
  curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$port/ 2>/dev/null || echo "fail"
  echo
done

echo "========== [4] MuseTalk E2E 验证 =========="
E2E_PROFILE=autodl-best E2E_TIMEOUT=300 uv run python -u scripts/e2e_real.py 2>&1 | tail -20

echo "========== [5] FlashHead probe(如果权重就绪) =========="
if [ -f /root/autodl-tmp/models/SoulX-FlashHead-1_3B/Model_Lite/diffusion_pytorch_model.safetensors ]; then
  echo "SoulX 权重存在，启动 FlashHead 服务..."
  setsid nohup /root/autodl-tmp/avatarloom-avatar-venv/bin/python scripts/flashhead_service.py \
    --model-dir /root/autodl-tmp/models/SoulX-FlashHead-1_3B \
    --wav2vec-dir /root/autodl-tmp/models/wav2vec2-base-960h \
    --port 8767 --image /root/autodl-tmp/avatarloom/personas/demo-assistant/avatar/portrait.jpg \
    </dev/null >/tmp/flashhead_service.log 2>&1 &
  echo "FlashHead PID=$! 等待启动..."
  sleep 30
  /root/autodl-tmp/avatarloom-avatar-venv/bin/python scripts/flashhead_probe.py \
    --port 8767 \
    --image /root/autodl-tmp/avatarloom/personas/demo-assistant/avatar/portrait.jpg \
    --audio /root/autodl-tmp/musetalk/demo_10s.wav \
    --out /tmp/flashhead_probe.mp4 2>&1 | tail -10
  echo "FlashHead probe 完成"
else
  echo "SoulX 权重未就绪，跳过 FlashHead probe"
fi

echo "========== 验证结束 =========="
