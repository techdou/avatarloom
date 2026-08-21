#!/bin/bash
# AVTR-1 安装链 v3（无卡模式版）：pixi env → 下权重 → 有卡则编译 / 无卡则停
# v3：CONDA_OVERRIDE_CUDA=12.8 模拟 __cuda 虚拟包（无卡模式 pixi 拒绝解 cuda 环境）；
#     编译前检查 GPU——无卡则停并打 READY_FOR_GPU_BUILD 标记（TRT 编译必须真卡调优）。
set -uo pipefail
exec > >(tee -a /root/autodl-tmp/avtr1_setup.log) 2>&1
echo "=== [0] $(date +%T) start v3 ==="
export AVTR1_LOCAL_STORAGE=/root/autodl-tmp/avtr1_storage
export HF_ENDPOINT=https://hf-mirror.com
export CONDA_OVERRIDE_CUDA=12.8

export PATH="$HOME/.pixi/bin:$PATH"
pixi --version || { echo "FAIL_PIXI"; exit 1; }

cd /root/autodl-tmp/avtr-1
echo "=== [2] env solve+install（renderer，清华+阿里镜像）==="
pixi install || { echo "FAIL_PIXI_PROJECT_INSTALL"; exit 1; }

echo "=== [3] download artifacts（断点续传 + 失败自动重试 6 轮）==="
# warp_plugin 等制品走 GitHub releases（需 turbo）；HF 制品走 hf-mirror。
# 单制品网络抖动会整批抛错——外层重试，ensure_all_artifacts 断点续传逐轮推进。
source /etc/network_turbo 2>/dev/null || true
_ok=0
for _i in 1 2 3 4 5 6; do
  if pixi run python scripts/download_artifacts.py; then _ok=1; break; fi
  echo "download 第 ${_i} 轮失败，20s 后断点续传重试"; sleep 20
done
[ "$_ok" = "1" ] || { echo "FAIL_DOWNLOAD"; exit 1; }

if ! nvidia-smi -L 2>/dev/null | grep -q GPU; then
  echo "=== READY_FOR_GPU_BUILD（无卡模式，编译留到有卡窗口）==="
  exit 0
fi
echo "=== [4] build TRT engines（sm120，最长步骤）==="
pixi run build-trt-engines || { echo "FAIL_BUILD"; exit 1; }
echo "=== [5] ALL_DONE ==="
