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
import contextlib
import json
import os
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
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


@dataclass
class E2eAssets:
    user_wav: Path
    portrait: str
    voice_ref: str


@dataclass
class E2eState:
    t_start: float
    events: list[tuple[float, Event]] = field(default_factory=list)
    first_event_ts: dict[str, float] = field(default_factory=dict)
    got: dict[str, bool] = field(
        default_factory=lambda: {
            "transcript": False,
            "llm_delta": False,
            "tts_delta": False,
            "tts_done": False,
            "avatar": False,
            "video": False,
        }
    )
    video_path: str | None = None
    transcript_text: str = ""
    llm_full: str = ""
    tts_pcm: bytearray = field(default_factory=bytearray)
    frames: list[bytes] = field(default_factory=list)
    cursor: int = 0


def _configure_stdout() -> None:
    with contextlib.suppress(Exception):
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(line_buffering=True)


def _resolve_assets() -> E2eAssets:
    user_wav = Path(os.environ.get("E2E_USER_WAV", "data/assets/user_input.wav"))
    if not user_wav.is_absolute():
        user_wav = PROJECT_ROOT / user_wav
    return E2eAssets(
        user_wav=user_wav,
        portrait=os.environ.get(
            "E2E_PORTRAIT", "personas/demo-assistant/avatar/portrait.png"
        ),
        voice_ref=os.environ.get("E2E_VOICE_REF", "personas/demo-assistant/voice/ref.wav"),
    )


def _print_header(assets: E2eAssets) -> None:
    print("=" * 64)
    print("AvatarLoom Real E2E (RTX 5090)")
    print("=" * 64)
    print(f"[env] user_wav={assets.user_wav}")
    print(f"[env] portrait={assets.portrait}")
    print(f"[env] voice_ref={assets.voice_ref}")


async def _missing_assets(assets: E2eAssets) -> list[str]:
    asset_paths = (
        assets.user_wav,
        PROJECT_ROOT / assets.portrait,
        PROJECT_ROOT / assets.voice_ref,
    )
    return await asyncio.to_thread(
        lambda: [str(path) for path in asset_paths if not path.exists()]
    )


def _print_missing_assets(missing_assets: list[str]) -> None:
    print(
        "[FATAL] 资产缺失（persona 三件套不在仓库，需先跑 "
        "scripts/generate_asset_matrix.sh 或手动放置）：",
        file=sys.stderr,
    )
    for missing in missing_assets:
        print(f"  - {missing}", file=sys.stderr)


def _load_e2e_profile(profile_name: str, assets: E2eAssets):
    profile_path = PROJECT_ROOT / "profiles" / f"{profile_name}.yaml"
    config = load_profile(profile_path)
    if "avatar" in config.blocks:
        config.blocks["avatar"].config["portrait"] = assets.portrait
    if "tts" in config.blocks:
        config.blocks["tts"].config["voiceRef"] = assets.voice_ref
    print(f"[1] profile={config.profile_id} blocks={list(config.blocks)}")
    return config


def _make_sink(state: E2eState):
    async def sink(e: Event) -> None:
        state.events.append((time.perf_counter() - state.t_start, e))
        # 非高频事件直接打印（排障：状态迁移/finish_reason/打断 一目了然）
        if e.type in (
            "audio.appended",
            "tts.audio.delta",
            "avatar.speech_frame",
            "avatar.idle_frame",
        ):
            return
        extra = ""
        if e.type == "llm.text.done":
            extra = f" finish={e.payload.get('finish_reason')}"
        elif e.type == "session.state_changed":
            extra = f" {e.payload.get('from')}→{e.payload.get('to')}"
        print(
            f"    [evt] {e.type} @{time.perf_counter() - state.t_start:.2f}s{extra}",
            flush=True,
        )

    return sink


async def _start_orchestrator(config, state: E2eState):
    orch = Orchestrator(config, event_sink=_make_sink(state))
    print("[2] orchestrator.setup() ...")
    await orch.setup()
    print(f"    ready blocks: {list(orch.blocks)} degraded={orch.degraded_blocks}")
    session = await orch.start_session(
        persona_id="demo-assistant",
        workspace_root=str(PROJECT_ROOT),
    )
    print(f"[3] session={session.session_id}")
    return orch, session


async def _feed_user_audio(orch: Orchestrator, session, user_wav: Path) -> None:
    print(f"[4] load user audio: {user_wav}")
    pcm = _load_pcm16_16k(user_wav)
    print(f"    {len(pcm) / 2 / 16000:.2f}s @16k")
    print("[5] feed audio to orchestrator ...")
    # 接近实时节奏喂食（512 采样=32ms @16k）：此前 5ms 快喂导致 silero VAD
    # 积压，滞后的 speech.detected 在 LLM 启动后才到达 → 假打断吞掉全部 delta。
    # 真实用户就是实时说话，E2E 对齐真实时序。
    for chunk in _chunks16(pcm):
        await orch.ingest_audio(session, base64.b64encode(chunk).decode("ascii"), 512)
        await asyncio.sleep(0.032)
    # append >=1.25s silence so Silero VAD emits speech.ended
    silent = base64.b64encode(b"\x00\x00" * 512).decode("ascii")
    for _ in range(40):
        await orch.ingest_audio(session, silent, 512)
        await asyncio.sleep(0.032)
    print("    (appended 1.25s silence to trigger speech end)")


def _print_heartbeat(state: E2eState) -> None:
    # 事件类型分布（诊断用：定位链路卡在哪）
    from collections import Counter

    now = time.perf_counter()
    type_counts = Counter(e.type for _, e in state.events)
    top = ", ".join(f"{t}:{c}" for t, c in type_counts.most_common(6))
    print(
        f"    [heartbeat] t={now - state.t_start:.0f}s events={len(state.events)} "
        f"types=[{top}] "
        f"got={ dict(state.got.items()) }",
        flush=True,
    )


def _consume_event(state: E2eState, dt: float, e: Event) -> None:
    if e.type == TRANSCRIPT_COMPLETED and not state.got["transcript"]:
        state.transcript_text = e.payload.get("text", "")
        state.got["transcript"] = True
        state.first_event_ts["transcript"] = dt
        print(f"    [event] transcript @{dt:.2f}s: {state.transcript_text!r}")
    elif e.type == LLM_TEXT_DELTA and not state.got["llm_delta"]:
        state.got["llm_delta"] = True
        state.first_event_ts["first_llm_delta"] = dt
        print(f"    [event] first llm delta @{dt:.2f}s: {e.payload.get('text', '')!r}")
    elif e.type == LLM_TEXT_DONE:
        state.llm_full = e.payload.get("full_text", state.llm_full)
    elif e.type == TTS_AUDIO_DELTA and not state.got["tts_delta"] and not e.payload.get("filler"):
        state.got["tts_delta"] = True
        state.first_event_ts["first_tts_delta"] = dt
        print(f"    [event] first tts delta @{dt:.2f}s")
    _collect_media_event(state, dt, e)


def _collect_media_event(state: E2eState, dt: float, e: Event) -> None:
    # 垫音（filler）不计入验收音频——它是盖等待空白的口头禅，
    # 混入会让 TTS 时长/音频产物失真（payload.filler 由 orchestrator 标记）
    if e.type == TTS_AUDIO_DELTA and not e.payload.get("filler"):
        state.tts_pcm += base64.b64decode(e.payload.get("pcm_b64", ""))
    elif e.type == TTS_AUDIO_COMPLETED:
        state.got["tts_done"] = True
        state.first_event_ts["tts_completed"] = dt
        print(f"    [event] tts completed @{dt:.2f}s")
    elif e.type == AVATAR_SPEECH_FRAME and not state.got["avatar"]:
        state.got["avatar"] = True
        state.first_event_ts["first_avatar_frame"] = dt
        print(f"    [event] first avatar frame @{dt:.2f}s")
    elif e.type == AVATAR_VIDEO_READY:
        _record_video_ready(state, dt, e)
    if e.type == AVATAR_SPEECH_FRAME:
        state.frames.append(base64.b64decode(e.payload.get("frame_b64", "")))


def _record_video_ready(state: E2eState, dt: float, e: Event) -> None:
    if not state.got["video"]:
        state.first_event_ts["video_ready"] = dt
    state.got["video"] = True
    state.video_path = e.payload.get("video_path", "")
    print(
        f"    [event] avatar video ready @{dt:.2f}s "
        f"frames={e.payload.get('frames')} "
        f"infer_s={e.payload.get('infer_s')} mp4={state.video_path}"
    )


def _consume_new_events(state: E2eState) -> None:
    new_events = state.events[state.cursor :]
    state.cursor = len(state.events)
    for dt, event in new_events:
        _consume_event(state, dt, event)


async def _wait_for_pipeline(state: E2eState, timeout: float) -> None:
    print("[6] wait for pipeline ...")
    deadline = time.perf_counter() + timeout
    last_heartbeat = time.perf_counter()
    while time.perf_counter() < deadline and not (
        state.got["tts_done"] and state.got["avatar"]
    ):
        now = time.perf_counter()
        if now - last_heartbeat >= 30:
            last_heartbeat = now
            _print_heartbeat(state)
        await asyncio.sleep(0.2)
        _consume_new_events(state)


async def _maybe_wait_for_video(
    orch: Orchestrator,
    state: E2eState,
    is_flashhead: bool,
) -> None:
    if not state.got["tts_done"] or state.got["video"]:
        return
    avatar_block_id = ""
    with contextlib.suppress(Exception):
        avatar_block_id = orch.blocks["avatar"].manifest().block_id if "avatar" in orch.blocks else ""
    if is_flashhead or avatar_block_id in ("avatar.mock", "avatar.static"):
        print(f"[6.5] {avatar_block_id or 'flashhead'}: frames == video (no reply mp4)")
        state.got["video"] = True
        return
    await _wait_for_rendered_video(state)


async def _wait_for_rendered_video(state: E2eState) -> None:
    video_deadline = time.perf_counter() + 720
    print("[6.5] waiting for avatar video render ...")
    while time.perf_counter() < video_deadline and not state.got["video"]:
        await asyncio.sleep(0.2)
        _consume_video_ready_events(state)


def _consume_video_ready_events(state: E2eState) -> None:
    # 复用主循环游标续扫——原行为只在渲染等待阶段处理 avatar.video.ready。
    new_events = state.events[state.cursor :]
    state.cursor = len(state.events)
    for dt, event in new_events:
        if event.type == AVATAR_VIDEO_READY:
            _record_video_ready(state, dt, event)


def _event_type_counts(events: list[tuple[float, Event]]) -> dict[str, int]:
    from collections import Counter

    return dict(Counter(e.type for _, e in events).most_common())


def _build_manifest(
    ts: str,
    e2e: float,
    orch: Orchestrator,
    config,
    session,
    profile_name: str,
    assets: E2eAssets,
    state: E2eState,
    tts_wav: Path,
) -> dict:
    return {
        "ts": ts,
        "profile": config.profile_id,
        "session_id": session.session_id,
        # AL-E2E-002：fallback 必须显式记录——输出 PASS 不等于目标真实 Block 成功
        "ready_blocks": _ready_block_ids(orch),
        "degraded_blocks": dict(orch.degraded_blocks),
        "inputs": {
            "user_wav": str(assets.user_wav),
            "portrait": assets.portrait,
            "voice_ref": assets.voice_ref,
            "profile": profile_name,
            "llm_model": os.environ.get("LLM_MODEL", ""),
            "llm_base_url": os.environ.get("LLM_BASE_URL", ""),
        },
        "transcript": state.transcript_text,
        "llm_reply": state.llm_full,
        "events": {k: bool(v) for k, v in state.got.items()},
        "event_type_counts": _event_type_counts(state.events),
        "metrics": {
            "total_e2e_s": round(e2e, 3),
            "tts_audio_seconds": round(len(state.tts_pcm) / 2 / 16000, 3),
            "frames": len(state.frames),
            "first_event_ts": {k: round(v, 3) for k, v in state.first_event_ts.items()},
        },
        "gpu": _gpu_snapshot(),
        "outputs": {"tts_wav": str(tts_wav)},
    }


async def _collect_outputs(
    out_dir: Path,
    ts: str,
    e2e: float,
    orch: Orchestrator,
    config,
    session,
    profile_name: str,
    assets: E2eAssets,
    state: E2eState,
) -> dict:
    print("[7] collect outputs ...")
    tts_wav = out_dir / "tts_reply.wav"
    tts_wav.write_bytes(_wav_bytes_16k(bytes(state.tts_pcm)))
    (out_dir / "transcript.txt").write_text(state.transcript_text, encoding="utf-8")
    (out_dir / "llm_reply.txt").write_text(state.llm_full, encoding="utf-8")
    manifest = _build_manifest(
        ts,
        e2e,
        orch,
        config,
        session,
        profile_name,
        assets,
        state,
        tts_wav,
    )
    await _attach_video_output(out_dir, manifest, state, tts_wav)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


async def _attach_video_output(
    out_dir: Path,
    manifest: dict,
    state: E2eState,
    tts_wav: Path,
) -> None:
    rendered_video = Path(state.video_path) if state.video_path else None
    video_exists = bool(
        rendered_video and await asyncio.to_thread(rendered_video.exists)
    )
    if video_exists and rendered_video is not None:
        await _copy_rendered_video(out_dir, manifest, rendered_video)
    elif state.frames:
        await _mux_frames(out_dir, manifest, state, tts_wav)


async def _copy_rendered_video(out_dir: Path, manifest: dict, rendered_video: Path) -> None:
    dst_mp4 = out_dir / "avatar_musetalk.mp4"
    video_bytes = await asyncio.to_thread(rendered_video.read_bytes)
    await asyncio.to_thread(dst_mp4.write_bytes, video_bytes)
    manifest["outputs"]["avatar_mp4"] = str(dst_mp4)
    manifest["metrics"]["video_source"] = "musetalk"


async def _mux_frames(
    out_dir: Path,
    manifest: dict,
    state: E2eState,
    tts_wav: Path,
) -> None:
    frame_dir = out_dir / "frames"
    frame_dir.mkdir(exist_ok=True)
    for i, jpg in enumerate(state.frames):
        (frame_dir / f"{i:05d}.jpg").write_bytes(jpg)
    mp4 = out_dir / "avatar.mp4"
    tts_seconds = max(0.1, len(state.tts_pcm) / 2 / 16000)
    fps = max(1, min(30, round(len(state.frames) / tts_seconds)))
    cmd = [
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", str(frame_dir / "%05d.jpg"),
        "-i", str(tts_wav),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(mp4),
    ]
    manifest["metrics"]["video_fps"] = fps
    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True
    )
    manifest["outputs"]["avatar_mp4"] = str(mp4)
    manifest["ffmpeg_rc"] = result.returncode
    manifest["metrics"]["video_source"] = "frame-mux"
    if result.returncode != 0:
        print(result.stderr[-500:])


async def _shutdown_orchestrator(orch: Orchestrator) -> None:
    print("[8] shutdown")
    try:
        await asyncio.wait_for(orch.shutdown(), timeout=30)
    except asyncio.CancelledError:
        # 基类异常，不受 Exception 捕获——musetalk 渲染 task 取消时透传，
        # 此前吞掉了 RESULT 打印（真因排查花了三轮）
        pass
    except Exception as e:
        # shutdown 失败不影响 RESULT 判定（产物已落盘），但不能静默吞掉——
        # 否则 shutdown 阶段的资源泄漏/超时无从排查
        print(f"[warn] shutdown raised, ignored: {type(e).__name__}: {e}", file=sys.stderr)


def _print_result(state: E2eState, e2e: float, out_dir: Path) -> bool:
    ok = all(state.got.values())
    print("=" * 64)
    print(
        f"RESULT: {'PASS' if ok else 'FAIL'} "
        f"transcript={state.got['transcript']} llm={state.got['llm_delta']} "
        f"tts={state.got['tts_delta']} avatar={state.got['avatar']}"
    )
    print(
        f"E2E total: {e2e:.2f}s | "
        f"TTS audio: {len(state.tts_pcm) / 2 / 16000:.2f}s | "
        f"frames: {len(state.frames)}"
    )
    print(f"OUTPUTS: {out_dir}")
    return ok


async def main() -> int:
    _configure_stdout()
    t_start = time.perf_counter()
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    timeout = float(os.environ.get("E2E_TIMEOUT", "300"))
    state = E2eState(t_start=t_start)
    assets = _resolve_assets()
    _print_header(assets)

    # 资产预检：缺文件直接报错（而不是深处 BlockSetupError 难定位）。
    # persona 三件套不在 git 仓库，需服务器预先生成（generate_asset_matrix.sh）。
    missing_assets = await _missing_assets(assets)
    if missing_assets:
        _print_missing_assets(missing_assets)
        return 2

    profile_name = os.environ.get("E2E_PROFILE", "autodl-best")
    is_flashhead = "flashhead" in profile_name
    config = _load_e2e_profile(profile_name, assets)
    orch, session = await _start_orchestrator(config, state)
    await _feed_user_audio(orch, session, assets.user_wav)
    await _wait_for_pipeline(state, timeout)
    await _maybe_wait_for_video(orch, state, is_flashhead)

    e2e = time.perf_counter() - t_start
    await _collect_outputs(
        out_dir,
        ts,
        e2e,
        orch,
        config,
        session,
        profile_name,
        assets,
        state,
    )
    await _shutdown_orchestrator(orch)
    ok = _print_result(state, e2e, out_dir)
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
