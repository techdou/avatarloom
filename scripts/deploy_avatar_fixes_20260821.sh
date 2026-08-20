#!/bin/bash
# 服务器端一键部署：新形象 + 垫音重铸（2026-08-21）
# 由本地 deploy-watcher 在 SSH 恢复后推送执行；也可手动 bash 运行。
set -uo pipefail

ROOT=/root/autodl-tmp/avatarloom
cd "$ROOT" || exit 1

echo "=== [1/4] git pull（先加载学术加速，防 fetch 卡死）==="
source /etc/network_turbo 2>/dev/null || true
git pull --ff-only origin main || { echo "GIT_PULL_FAILED"; exit 1; }
git log --oneline -1

echo "=== [2/4] 部署新形象（旧版备份）==="
AVATAR_DIR="$ROOT/personas/demo-assistant/avatar"
[ -f "$AVATAR_DIR/portrait.jpg" ] && cp "$AVATAR_DIR/portrait.jpg" "$AVATAR_DIR/portrait.jpg.bak-20260821"
cp /tmp/avatarloom-deploy/portrait_female_1280x720.jpg "$AVATAR_DIR/portrait.jpg"
cp /tmp/avatarloom-deploy/portrait_male_1280x720.jpg "$AVATAR_DIR/portrait-alt-male.jpg"
python3 -c "
from struct import unpack
# 校验 JPEG 尺寸（无 PIL 环境）：解析 SOF0
import sys
def jpeg_size(p):
    with open(p,'rb') as f:
        d=f.read()
    i=2
    while i < len(d):
        if d[i] != 0xFF: i+=1; continue
        m=d[i+1]
        if m in (0xC0,0xC1,0xC2):
            h,w = unpack('>HH', d[i+5:i+9]); return w,h
        i += 2 + unpack('>H', d[i+2:i+4])[0]
    return None
print('portrait.jpg', jpeg_size('$AVATAR_DIR/portrait.jpg'))
"

echo "=== [3/4] GPU 空闲检查（防与活动会话争显存）==="
USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
echo "GPU memory.used=${USED}MiB"
if [ "$USED" -gt 3000 ]; then
  echo "GPU_BUSY_SKIP_REGEN（网关可能在会话中；垫音重铸跳过，稍后手动跑 scripts/regen_fillers.py）"
  exit 0
fi

echo "=== [4/4] 垫音处置（对齐 VoxEMW：生产弃用，废片清理）==="
# 坏例废片无条件清理（profile 已 fillerEnabled:false，不会再播；重铸仅 A/B 备用）
python3 -c "
import glob, os, shutil
root = '$ROOT/personas/demo-assistant/fillers'
for p in glob.glob(root + '/neutral/*.wav'):
    os.remove(p)
for p in glob.glob(root + '/neutral.bak-*'):
    shutil.rmtree(p, ignore_errors=True)
print('服务器坏例垫音废片已清理')
"
if [ "${RUN_REGEN:-0}" = "1" ]; then
  USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  echo "GPU memory.used=${USED}MiB"
  if [ "$USED" -gt 3000 ]; then
    echo "GPU_BUSY_SKIP_REGEN（有活动会话；稍后手动跑 scripts/regen_fillers.py）"
    exit 0
  fi
  echo "RUN_REGEN=1：重铸垫音（频谱门控，badcase 自动重试）"
  "$ROOT/.venv/bin/python" "$ROOT/scripts/regen_fillers.py" --profile autodl-best --persona demo-assistant
  RC=$?
  echo "REGEN_RC=$RC"
  ls -la "$ROOT/personas/demo-assistant/fillers/neutral/"
  exit $RC
fi
echo "垫音已对齐弃用（如需 A/B：RUN_REGEN=1 重跑本脚本）"
