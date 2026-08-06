#!/usr/bin/env python
"""AvatarLoom Real E2E (AutoDL RTX 5090).

Real chain: Silero VAD -> SenseVoice STT -> DeepSeek/MiniMax LLM (stream) -> VoxCPM2 TTS (stream) -> Avatar frames.
User input audio is a real wav (default: MiMo-generated), fed through the orchestrator.

Env overrides for asset matrix testing:
  E2E_USER_WAV   path to 16k mono user input wav
  E2E_PORTRAIT   path to avatar portrait image
  E2E_VOICE_REF  path to assistant voice reference wav (VoxCPM2 cloning)
  E2E_TIMEOUT    pipeline timeout seconds (default 300)
  E2E_PROFILE    profile yaml basename under profiles/ (default autodl-best)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from avatarloom_protocol import (  # noqa: E402
    AVATAR_SPEECH_FRAME,
    AVATAR_VIDEO_READY,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from runtime.orchestrator import Orchestrator  # noqa: E402
from runtime.orchestrator.profile_loader import load_profile  # noqa: E402

OUT_ROOT = Path(os.environ.get("E2E_OUT_DIR", "/root/autodl-tmp/avatarloom/runs/e2e-real"))


def _wav_bytes_16k(pcm16: bytes, sr: int = 16000) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm16))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm16))
        + pcm16
    )


def _load_pcm16_16k(wav_path: Path) -> bytes:
    import wave

    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    if ch > 1:
        arr = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch)
        raw = arr[:, 0].tobytes()
    if sr != 16000:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            from scipy.signal import resample_poly

            y = resample_poly(x, 16000, sr)
        except Exception:
            # naive linear decimation for common ratios
            step = sr / 16000
            idx = (np.arange(int(len(x) / step)) * step).astype(np.int64)
            y = x[idx]
        raw = (np.clip(y, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    return raw


def _chunks16(pcm16: bytes, size: int = 512):
    n = len(pcm16) // 2 // size
    for i in range(n):
        yield pcm16[i * size * 2 : (i + 1) * size * 2]


async def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    t_start = time.perf_counter()
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    timeout = float(os.environ.get("E2E_TIMEOUT", "300"))

    user_wav = Path(os.environ.get("E2E_USER_WAV", "data/assets/user_input.wav"))
    if not user_wav.is_absolute():
        user_wav = PROJECT_ROOT / user_wav
    portrait = os.environ.get("E2E_PORTRAIT", "personas/demo-assistant/avatar/portrait.png")
    voice_ref = os.environ.get("E2E_VOICE_REF", "personas/demo-assistant/voice/ref.wav")

    print("=" * 64)
    print("AvatarLoom Real E2E (RTX 5090)")
    print("=" * 64)
    print(f"[env] user_wav={user_wav}")
    print(f"[env] portrait={portrait}")
    print(f"[env] voice_ref={voice_ref}")

    # 资产预检：缺文件直接报错（而不是深处 BlockSetupError 难定位）。
    # persona 三件套不在 git 仓库，需服务器预先生成（generate_asset_matrix.sh）。
    missing_assets = [str(p) for p in (user_wav, PROJECT_ROOT / portrait, PROJECT_ROOT / voice_ref) if not Path(p).exists()]
    if missing_assets:
        print(
            "[FATAL] 资产缺失（persona 三件套不在仓库，需先跑 "
            "scripts/generate_asset_matrix.sh 或手动放置）：",
            file=sys.stderr,
        )
        for m in missing_assets:
            print(f"  - {m}", file=sys.stderr)
        return 2

    profile_name = os.environ.get("E2E_PROFILE", "autodl-best")
    profile_path = PROJECT_ROOT / "profiles" / f"{profile_name}.yaml"
    is_flashhead = "flashhead" in profile_name
    config = load_profile(profile_path)
    if "avatar" in config.blocks:
        config.blocks["avatar"].config["portrait"] = portrait
    if "tts" in config.blocks:
        config.blocks["tts"].config["voiceRef"] = voice_ref
    print(f"[1] profile={config.profile_id} blocks={list(config.blocks)}")

    events: list[tuple[float, Event]] = []
    # 首事件时刻（相对 t_start 秒）——落盘到 manifest.metrics.first_event_ts
    first_event_ts: dict[str, float] = {}

    async def sink(e: Event) -> None:
        events.append((time.perf_counter() - t_start, e))

    orch = Orchestrator(config, event_sink=sink)
    print("[2] orchestrator.setup() ...")
    await orch.setup()
    print(f"    ready blocks: {list(orch.blocks)} degraded={orch.degraded_blocks}")

    session = await orch.start_session(persona_id="demo-assistant", workspace_root=str(PROJECT_ROOT))
    print(f"[3] session={session.session_id}")

    print(f"[4] load user audio: {user_wav}")
    pcm = _load_pcm16_16k(user_wav)
    print(f"    {len(pcm) / 2 / 16000:.2f}s @16k")
    print("[5] feed audio to orchestrator ...")
    for chunk in _chunks16(pcm):
        await orch.ingest_audio(session, base64.b64encode(chunk).decode("ascii"), 512)
        await asyncio.sleep(0.005)
    # append >=1.25s silence so Silero VAD emits speech.ended
    silent = base64.b64encode(b"\x00\x00" * 512).decode("ascii")
    for _ in range(40):
        await orch.ingest_audio(session, silent, 512)
        await asyncio.sleep(0.005)
    print("    (appended 1.25s silence to trigger speech end)")

    print("[6] wait for pipeline ...")
    deadline = time.perf_counter() + timeout
    got = {
        "transcript": False,
        "llm_delta": False,
        "tts_delta": False,
        "tts_done": False,
        "avatar": False,
        "video": False,
    }
    video_path: str | None = None
    transcript_text = ""
    llm_full = ""
    tts_pcm = bytearray()
    frames: list[bytes] = []
    last_heartbeat = time.perf_counter()
    # 消费游标：AL-E2E-001 修复——每轮 poll 只处理新增事件，
    # 此前全量重扫导致 TTS PCM / Avatar 帧被重复累计，音频时长与帧数全部失真。
    cursor = 0
    while time.perf_counter() < deadline and not (got["tts_done"] and got["avatar"]):
        now = time.perf_counter()
        if now - last_heartbeat >= 30:
            last_heartbeat = now
            # 事件类型分布（诊断用：定位链路卡在哪）
            from collections import Counter

            type_counts = Counter(e.type for _, e in events)
            top = ", ".join(f"{t}:{c}" for t, c in type_counts.most_common(6))
            print(
                f"    [heartbeat] t={now - t_start:.0f}s events={len(events)} "
                f"types=[{top}] "
                f"got={ {k: v for k, v in got.items()} }",
                flush=True,
            )
        await asyncio.sleep(0.2)
        new_events = events[cursor:]
        cursor = len(events)
        for dt, e in new_events:
            if e.type == TRANSCRIPT_COMPLETED and not got["transcript"]:
                transcript_text = e.payload.get("text", "")
                got["transcript"] = True
                first_event_ts["transcript"] = dt
                print(f"    [event] transcript @{dt:.2f}s: {transcript_text!r}")
            elif e.type == LLM_TEXT_DELTA and not got["llm_delta"]:
                got["llm_delta"] = True
                first_event_ts["first_llm_delta"] = dt
                print(f"    [event] first llm delta @{dt:.2f}s: {e.payload.get('text', '')!r}")
            elif e.type == LLM_TEXT_DONE:
                llm_full = e.payload.get("full_text", llm_full)
            elif e.type == TTS_AUDIO_DELTA and not got["tts_delta"]:
                got["tts_delta"] = True
                first_event_ts["first_tts_delta"] = dt
                print(f"    [event] first tts delta @{dt:.2f}s")
            if e.type == TTS_AUDIO_DELTA:
                tts_pcm += base64.b64decode(e.payload.get("pcm_b64", ""))
            elif e.type == TTS_AUDIO_COMPLETED:
                got["tts_done"] = True
                first_event_ts["tts_completed"] = dt
                print(f"    [event] tts completed @{dt:.2f}s")
            elif e.type == AVATAR_SPEECH_FRAME and not got["avatar"]:
                got["avatar"] = True
                first_event_ts["first_avatar_frame"] = dt
                print(f"    [event] first avatar frame @{dt:.2f}s")
            elif e.type == AVATAR_VIDEO_READY:
                if not got["video"]:
                    first_event_ts["video_ready"] = dt
                got["video"] = True
                video_path = e.payload.get("video_path", "")
                print(
                    f"    [event] avatar video ready @{dt:.2f}s "
                    f"frames={e.payload.get('frames')} "
                    f"infer_s={e.payload.get('infer_s')} mp4={video_path}"
                )
            if e.type == AVATAR_SPEECH_FRAME:
                frames.append(base64.b64decode(e.payload.get("frame_b64", "")))

    # 真口型视频是异步渲染的——给 avatar.video.ready 留出渲染时间
    if got["tts_done"] and not got["video"]:
        # 只有真实渲染型 avatar（musetalk）才产出 reply 级 mp4；
        # flashhead 流式帧即视频，mock/static 无渲染概念——跳过等待，
        # 否则 mock 链路本地验证会在此处空等 720s。
        avatar_block_id = ""
        try:
            avatar_block_id = orch.blocks["avatar"].manifest().block_id if "avatar" in orch.blocks else ""
        except Exception:
            pass
        if is_flashhead or avatar_block_id in ("avatar.mock", "avatar.static"):
            print(f"[6.5] {avatar_block_id or 'flashhead'}: frames == video (no reply mp4)")
            got["video"] = True
        else:
            video_deadline = time.perf_counter() + 720
            print("[6.5] waiting for avatar video render ...")
            while time.perf_counter() < video_deadline and not got["video"]:
                await asyncio.sleep(0.2)
                # 复用主循环游标续扫——同样只处理新增事件
                new_events = events[cursor:]
                cursor = len(events)
                for dt, e in new_events:
                    if e.type == AVATAR_VIDEO_READY:
                        got["video"] = True
                        first_event_ts["video_ready"] = dt
                        video_path = e.payload.get("video_path", "")
                        print(
                            f"    [event] avatar video ready @{dt:.2f}s "
                            f"frames={e.payload.get('frames')} "
                            f"infer_s={e.payload.get('infer_s')} mp4={video_path}"
                        )

    e2e = time.perf_counter() - t_start
    print("[7] collect outputs ...")
    tts_wav = out_dir / "tts_reply.wav"
    tts_wav.write_bytes(_wav_bytes_16k(bytes(tts_pcm)))
    (out_dir / "transcript.txt").write_text(transcript_text, encoding="utf-8")
    (out_dir / "llm_reply.txt").write_text(llm_full, encoding="utf-8")
    # 事件类型分布（验收诊断：定位链路卡点）
    from collections import Counter

    event_type_counts = dict(Counter(e.type for _, e in events).most_common())

    manifest = {
        "ts": ts,
        "profile": config.profile_id,
        "session_id": session.session_id,
        # AL-E2E-002：fallback 必须显式记录——输出 PASS 不等于目标真实 Block 成功
        "ready_blocks": _ready_block_ids(orch),
        "degraded_blocks": dict(orch.degraded_blocks),
        "inputs": {
            "user_wav": str(user_wav),
            "portrait": portrait,
            "voice_ref": voice_ref,
            "profile": profile_name,
            "llm_model": os.environ.get("LLM_MODEL", ""),
            "llm_base_url": os.environ.get("LLM_BASE_URL", ""),
        },
        "transcript": transcript_text,
        "llm_reply": llm_full,
        "events": {k: bool(v) for k, v in got.items()},
        "event_type_counts": event_type_counts,
        "metrics": {
            "total_e2e_s": round(e2e, 3),
            "tts_audio_seconds": round(len(tts_pcm) / 2 / 16000, 3),
            "frames": len(frames),
            "first_event_ts": {k: round(v, 3) for k, v in first_event_ts.items()},
        },
        "gpu": _gpu_snapshot(),
        "outputs": {"tts_wav": str(tts_wav)},
    }

    if video_path and Path(video_path).exists():
        # 真实 MuseTalk 口型视频：直接复制为最终产物
        dst_mp4 = out_dir / "avatar_musetalk.mp4"
        dst_mp4.write_bytes(Path(video_path).read_bytes())
        manifest["outputs"]["avatar_mp4"] = str(dst_mp4)
        manifest["metrics"]["video_source"] = "musetalk"
    elif frames:
        frame_dir = out_dir / "frames"
        frame_dir.mkdir(exist_ok=True)
        for i, jpg in enumerate(frames):
            (frame_dir / f"{i:05d}.jpg").write_bytes(jpg)
        mp4 = out_dir / "avatar.mp4"
        tts_seconds = max(0.1, len(tts_pcm) / 2 / 16000)
        fps = max(1, min(30, round(len(frames) / tts_seconds)))
        cmd = [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(frame_dir / "%05d.jpg"),
            "-i", str(tts_wav),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(mp4),
        ]
        manifest["metrics"]["video_fps"] = fps
        r = subprocess.run(cmd, capture_output=True, text=True)
        manifest["outputs"]["avatar_mp4"] = str(mp4)
        manifest["ffmpeg_rc"] = r.returncode
        manifest["metrics"]["video_source"] = "frame-mux"
        if r.returncode != 0:
            print(r.stderr[-500:])
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[8] shutdown")
    try:
        await asyncio.wait_for(orch.shutdown(), timeout=30)
    except Exception:
        pass

    ok = all(got.values())
    print("=" * 64)
    print(
        f"RESULT: {'PASS' if ok else 'FAIL'} "
        f"transcript={got['transcript']} llm={got['llm_delta']} "
        f"tts={got['tts_delta']} avatar={got['avatar']}"
    )
    print(f"E2E total: {e2e:.2f}s | TTS audio: {len(tts_pcm) / 2 / 16000:.2f}s | frames: {len(frames)}")
    print(f"OUTPUTS: {out_dir}")
    return 0 if ok else 1


def _ready_block_ids(orch: Orchestrator) -> dict[str, str]:
    """实际就绪的 block id 清单（fallback 后是降级 block 的 id）。"""
    ids: dict[str, str] = {}
    for cat, blk in orch.blocks.items():
        try:
            ids[cat] = blk.manifest().block_id
        except Exception:
            ids[cat] = type(blk).__name__
    return ids


def _gpu_snapshot() -> dict[str, str]:
    """GPU/VRAM 快照（nvidia-smi 存在时）。本地无 GPU 返回空 dict。"""
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return {}
        name, total, used, driver = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        return {
            "name": name,
            "vram_total_mb": total,
            "vram_used_mb": used,
            "driver": driver,
        }
    except Exception:
        return {}


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
