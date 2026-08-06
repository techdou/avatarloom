#!/usr/bin/env python
"""FlashHead 服务验证探针：连接 WS，喂音频，收 JPEG 帧，mux 成 mp4。

用法：
  python flashhead_probe.py --port 8767 \
    --image /root/autodl-tmp/avatarloom/personas/demo-assistant/avatar/portrait.jpg \
    --audio /root/autodl-tmp/musetalk/demo_10s.wav \
    --out /tmp/flashhead_probe.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import websockets


def load_pcm16_16k(wav_path: str) -> bytes:
    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    if ch > 1:
        arr = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch)
        raw = arr[:, 0].tobytes()
    if sr != 16000:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        idx = (np.arange(int(len(x) * 16000 / sr)) * sr / 16000).astype(np.int64)
        x = x[idx]
        raw = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    return raw


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--image", required=True)
    ap.add_argument("--audio", default=None, help="16k/任意采样率 wav（不传则喂 5s 静音）")
    ap.add_argument("--out", default="/tmp/flashhead_probe.mp4")
    ap.add_argument("--chunk-samples", type=int, default=3200, help="0.2s@16k")
    ap.add_argument("--inter-chunk-s", type=float, default=0.15)
    ap.add_argument("--max-frames", type=int, default=300)
    args = ap.parse_args()

    pcm = (
        load_pcm16_16k(args.audio)
        if args.audio
        else b"\x00\x00" * (16000 * 5)
    )
    out_path = Path(args.out)
    frame_dir = out_path.parent / "flashhead_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.jpg"):
        old.unlink()

    uri = f"ws://127.0.0.1:{args.port}"
    print(f"[1] connect {uri} ...", flush=True)
    async with websockets.connect(uri, open_timeout=30) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        print("[2] ready:", ready, flush=True)
        await ws.send(json.dumps({"type": "set_image", "path": args.image}))
        print("[3] feed audio ...", flush=True)

        async def sender():
            for i in range(0, len(pcm), args.chunk_samples * 2):
                chunk = pcm[i : i + args.chunk_samples * 2]
                if not chunk:
                    break
                await ws.send(
                    json.dumps({"type": "audio", "pcm": base64.b64encode(chunk).decode()})
                )
                await asyncio.sleep(args.inter_chunk_s)
            await ws.send(json.dumps({"type": "reset"}))

        send_task = asyncio.create_task(sender())
        frames = 0
        t0 = asyncio.get_event_loop().time()
        last_frame_at = t0
        try:
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=3.0)
                except asyncio.TimeoutError:
                    # 空闲超时：音频播完且 idle 帧节流（0.96s）下无新帧——
                    # 已有足够帧就收工（probe 不是长跑服务）
                    print(
                        f"    idle timeout after {frames} frames",
                        flush=True,
                    )
                    break
                if isinstance(message, (bytes, bytearray)):
                    data = bytes(message)
                    # 服务下行协议：首字节 tag（0x00=idle / 0x01=speech）+ JPEG
                    if data and data[0] in (0x00, 0x01):
                        data = data[1:]
                    if not data:
                        continue
                    (frame_dir / f"{frames:05d}.jpg").write_bytes(data)
                    frames += 1
                    last_frame_at = asyncio.get_event_loop().time()
                    if frames % 25 == 0:
                        print(f"    frames={frames}", flush=True)
                    if frames >= args.max_frames:
                        break
        finally:
            send_task.cancel()
        dt = asyncio.get_event_loop().time() - t0
        print(f"[4] got {frames} frames in {dt:.1f}s ({frames / max(dt, 0.001):.1f} fps)", flush=True)

    if frames > 0:
        print("[5] mux mp4 ...", flush=True)
        cmd = [
            "ffmpeg", "-y", "-framerate", "25",
            "-i", str(frame_dir / "%05d.jpg"),
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print("ffmpeg rc:", r.returncode, flush=True)
        if r.returncode != 0:
            print(r.stderr[-300:], flush=True)
    print("OUT:", out_path, flush=True)
    return 0 if frames > 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
