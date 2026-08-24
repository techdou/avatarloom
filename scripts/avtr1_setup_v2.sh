#!/bin/bash
# AVTR-1 下载+编译自足驱动（v5）：网络段双通道轮替，GPU 在则自动编译。
# 设计目标：一条短 ssh 投递即跑，全程标记驱动，SSH 抖动不影响执行。
set -uo pipefail
exec > >(tee -a /root/autodl-tmp/avtr1_setup.log) 2>&1
echo "=== [v5] $(date +%T) start ==="
export AVTR1_LOCAL_STORAGE=/root/autodl-tmp/avtr1_storage
# 最终定版：全程 hf-mirror（实测 2026-08-21：hf-mirror 带 token 可代理 gated 仓授权；
# 官方直连+turbo 会停滞）。token 由 ~/.cache/huggingface/token 自动携带。
export HF_ENDPOINT=https://hf-mirror.com
export CONDA_OVERRIDE_CUDA=12.8
export PATH="$HOME/.pixi/bin:$PATH"
cd /root/autodl-tmp/avtr-1 || { echo "FAIL_CD"; exit 1; }

echo "=== [env] pixi install（幂等，已装秒过）==="
pixi install || { echo "FAIL_PIXI_PROJECT_INSTALL"; exit 1; }

ok=0
for round in 1 2 3 4; do
  echo "=== [dl] round $round ==="
  if pixi run python scripts/download_artifacts.py; then ok=1; break; fi
  echo "round $round 失败，15s 后断点续传"
  sleep 15
done
[ "$ok" = "1" ] || { echo "FAIL_DOWNLOAD"; exit 1; }
echo "=== [dl] 制品齐备 ==="

if nvidia-smi -L 2>/dev/null | grep -q GPU; then
  echo "=== [build] 检测到 GPU，编译 TRT 引擎（sm120）==="
  pixi run build-trt-engines && echo "ALL_DONE" || { echo "FAIL_BUILD"; exit 1; }
else
  echo "READY_FOR_GPU_BUILD"
fi
