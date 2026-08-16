#!/usr/bin/env python
"""AvatarLoom 本机 GPU 链路冒烟测试（RTX 5070 Ti）。

链路：silero VAD(CPU) → mock STT → DeepSeek LLM(远程) → Qwen3-TTS(GPU) → mock Avatar

不启动 HTTP 服务——直接用 Orchestrator + local-5070 Profile 跑完整链路。
用法：
    uv run python scripts/smoke_local.py

环境要求：
    - .env 中配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
    - uv sync --extra dev --extra silero --extra qwen3-tts
    - torch CUDA 版（cu128 for Blackwell）
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from pathlib import Path

import numpy as np

# 加载 .env
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT))

from avatarloom_protocol import (  # noqa: E402
    AVATAR_SPEECH_FRAME,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from runtime.orchestrator.orchestrator import Orchestrator  # noqa: E402
from runtime.orchestrator.profile_loader import load_profile  # noqa: E402

# 16kHz 单声道，32ms/帧 = 512 samples
_SAMPLE_RATE = 16000
_CHUNK_SAMPLES = 512


def _loud_pcm(amp: float = 800.0) -> bytes:
    """高能量 PCM（模拟说话）。"""
    t = np.linspace(0, _CHUNK_SAMPLES / _SAMPLE_RATE, _CHUNK_SAMPLES, endpoint=False)
    wave = amp * np.sin(2 * np.pi * 440 * t)
    return (wave.astype(np.int16)).tobytes()


def _silent_pcm() -> bytes:
    """静音 PCM。"""
    return np.zeros(_CHUNK_SAMPLES, dtype=np.int16).tobytes()


def _load_real_speech_wav(path: Path) -> list[bytes]:
    """读取 wav（自动降采样到 16kHz），切成 512-sample PCM chunks 返回。

    silero VAD 是神经网络模型——纯音/噪声几乎不触发（概率 <0.02），
    需要真实人声特征。用真实人声录音测试。
    """
    import wave

    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())

    raw = np.frombuffer(frames, dtype=np.int16)
    # 降采样到 16kHz（粗降采样——smoke 测试够用）
    if sr != _SAMPLE_RATE:
        ratio = sr / _SAMPLE_RATE
        indices = np.arange(0, len(raw), ratio).astype(int)
        raw = raw[indices]
    chunks = []
    for i in range(0, len(raw), _CHUNK_SAMPLES):
        chunk = raw[i : i + _CHUNK_SAMPLES]
        if len(chunk) == _CHUNK_SAMPLES:
            chunks.append(chunk.astype(np.int16).tobytes())
    return chunks


async def main() -> int:
    print("=" * 60)
    print("AvatarLoom 本机 GPU 链路冒烟测试")
    print("链路: silero VAD(CPU) → mock STT → DeepSeek LLM → Qwen3-TTS(GPU)")
    print("=" * 60)

    # ---- 1. 加载 Profile ----
    profile_path = PROJECT_ROOT / "profiles" / "local-5070.yaml"
    print(f"\n[1/6] 加载 Profile: {profile_path.name}")
    try:
        config = load_profile(profile_path)
    except Exception as e:
        print(f"  ✗ Profile 加载失败: {e}")
        return 1
    print(f"  ✓ profile_id={config.profile_id}")
    print(f"  ✓ blocks={list(config.blocks.keys())}")

    # ---- 2. 事件收集 ----
    events: list[Event] = []
    timings: dict[str, float] = {}
    t0 = 0.0

    async def event_sink(event: Event) -> None:
        events.append(event)
        elapsed = time.monotonic() - t0
        if event.type == TRANSCRIPT_COMPLETED and "transcript" not in timings:
            timings["transcript"] = elapsed
            print(f"  → transcript.completed @ {elapsed:.2f}s")
        elif event.type == LLM_TEXT_DELTA and "first_llm_delta" not in timings:
            timings["first_llm_delta"] = elapsed
            print(f"  → first llm.text.delta @ {elapsed:.2f}s（首字延迟）")
        elif event.type == LLM_TEXT_DONE and "llm_done" not in timings:
            timings["llm_done"] = elapsed
            text = str(event.payload.get("full_text") or "")
            print(f"  → llm.text.done @ {elapsed:.2f}s: {text[:80]}")
        elif event.type == TTS_AUDIO_DELTA and "first_tts_delta" not in timings:
            timings["first_tts_delta"] = elapsed
            print(f"  → first tts.audio.delta @ {elapsed:.2f}s（首音延迟）")
        elif event.type == TTS_AUDIO_COMPLETED and "tts_done" not in timings:
            timings["tts_done"] = elapsed
            print(f"  → tts.audio.completed @ {elapsed:.2f}s")
        elif event.type == AVATAR_SPEECH_FRAME and "first_frame" not in timings:
            timings["first_frame"] = elapsed
            print(f"  → first avatar frame @ {elapsed:.2f}s")

    # ---- 3. 装配 Orchestrator ----
    print("\n[2/6] 装配 Orchestrator（加载 GPU 模型，可能需要几分钟）...")
    orch = Orchestrator(config, event_sink=event_sink)
    try:
        await orch.setup()
    except Exception as e:
        print(f"  ✗ Orchestrator setup 失败: {e}")
        import traceback

        traceback.print_exc()
        return 1
    print(f"  ✓ ready blocks: {list(orch.blocks.keys())}")
    if orch.degraded_blocks:
        print(f"  ⚠ 降级: {orch.degraded_blocks}")

    # ---- 4. 启动 Session ----
    print("\n[3/6] 启动 Session")
    session = await orch.start_session(
        persona_id="demo-assistant",
        workspace_root=str(PROJECT_ROOT),
    )
    print(f"  ✓ session_id={session.session_id}")

    # ---- 5. 注入真实人声音频 ----
    print("\n[4/6] 注入真实人声音频（filler wav，按 32ms/chunk 节奏喂）")
    t0 = time.monotonic()

    # 用真实人声录音（silero VAD 需要人声特征，纯音/合成音频不触发）
    wav_path = PROJECT_ROOT / ".omx" / "assets" / "mimo" / "audio" / "user_input.wav"
    if not wav_path.exists():
        wav_path = PROJECT_ROOT / "personas" / "demo-assistant" / "fillers" / "neutral" / "filler_01.wav"
    speech_chunks = _load_real_speech_wav(wav_path)
    if not speech_chunks:
        print(f"  ⚠ 无法加载 {wav_path}，回退到正弦波（可能不触发 VAD）")
        speech_chunks = [_loud_pcm() for _ in range(4)]

    for i, pcm in enumerate(speech_chunks):
        pcm_b64 = base64.b64encode(pcm).decode("ascii")
        await orch.ingest_audio(session, pcm_b64, _CHUNK_SAMPLES)
        if (i + 1) % 10 == 0 or i == len(speech_chunks) - 1:
            print(f"  → speech chunk {i+1}/{len(speech_chunks)}")
        await asyncio.sleep(0.032)

    # 静音段：5 帧静音触发 speech.ended
    print("  → 注入静音段触发 speech.ended...")
    for i in range(8):
        pcm = _silent_pcm()
        pcm_b64 = base64.b64encode(pcm).decode("ascii")
        await orch.ingest_audio(session, pcm_b64, _CHUNK_SAMPLES)
        await asyncio.sleep(0.032)

    # ---- 6. 等待链路完成 ----
    print("\n[5/6] 等待链路完成（最多 60s）...")
    try:
        await asyncio.wait_for(_wait_for_completion(events), timeout=60.0)
        print("  ✓ 链路完成")
    except TimeoutError:
        print("  ⚠ 超时——检查上面的事件输出，看链路卡在哪一步")

    # 打印延迟报告
    print("\n" + "=" * 60)
    print("延迟报告")
    print("=" * 60)
    for key, label in [
        ("transcript", "转写完成"),
        ("first_llm_delta", "LLM 首字"),
        ("llm_done", "LLM 完成"),
        ("first_tts_delta", "TTS 首音"),
        ("tts_done", "TTS 完成"),
        ("first_frame", "首帧"),
    ]:
        val = timings.get(key)
        if val is not None:
            print(f"  {label:12s}: {val:.2f}s")
        else:
            print(f"  {label:12s}: —")

    # 事件统计
    event_types: dict[str, int] = {}
    for e in events:
        event_types[e.type] = event_types.get(e.type, 0) + 1
    print(f"\n  总事件数: {len(events)}")
    for etype, count in sorted(event_types.items()):
        print(f"    {etype}: {count}")

    # ---- 关闭 ----
    print("\n[6/6] 关闭 Orchestrator")
    await orch.shutdown()
    print("  ✓ 已关闭")

    # 判定
    success = "first_tts_delta" in timings
    print("\n" + "=" * 60)
    if success:
        print("✓ 本机 GPU 链路冒烟通过——Qwen3-TTS GPU 推理成功")
    else:
        print("✗ 链路未完成——TTS 未产出音频，检查上面的输出")
    print("=" * 60)
    return 0 if success else 1


async def _wait_for_completion(events: list[Event]) -> None:
    """等到收到 tts.audio.completed 或超时。"""
    while True:
        if any(e.type == TTS_AUDIO_COMPLETED for e in events):
            return
        await asyncio.sleep(0.1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
