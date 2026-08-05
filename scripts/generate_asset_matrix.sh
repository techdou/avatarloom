#!/bin/bash
# MuseTalk 素材矩阵批量生成：充分利用 GPU 产出多组真实口型视频
set -euo pipefail
cd /root/autodl-tmp/musetalk
OUT=/root/autodl-tmp/avatarloom/runs/asset-matrix
mkdir -p "$OUT"
PY=/root/autodl-tmp/musetalk-venv/bin/python
AV=/root/autodl-tmp/avatarloom/personas/demo-assistant/avatar
VO=/root/autodl-tmp/avatarloom/personas/demo-assistant/voice
IN=/root/autodl-tmp/avatarloom/data/assets
START=$(date +%s)
for portrait in portrait.jpg portrait2.jpg; do
  for voice in ref_moli.wav ref_suda.wav ref_baihua.wav; do
    for input in 16k_user_input_2.wav 16k_user_input_3.wav; do
      name="${portrait%.*}_${voice%.*}_${input%.*}"
      echo "==> $name"
      "$PY" lite_driver.py \
        --portrait "$AV/$portrait" \
        --audio "$IN/$input" \
        --out "$OUT/$name.mp4" \
        --max-side 1280 --keep-frames 2>&1 | grep -E "SUMMARY" || true
    done
  done
done
echo "MATRIX_DONE in $(( $(date +%s) - START ))s"
ls -l "$OUT" | tail -15
