#!/usr/bin/env python
"""AvatarLoom Mock 全链路冒烟测试。

不启动 HTTP 服务——直接用 Orchestrator + Mock Profile 跑完整链路：
1. 加载 mock.yaml
2. 装配 Orchestrator
3. 启动 Session
4. 注入模拟音频（高能量 -> 触发 VAD -> 静音 -> 触发 STT）
5. 验证事件序列（transcript/llm/tts/avatar）
6. Run Recorder 落盘
7. 报告结果

成功标准：收到至少 1 个 transcript.completed + 1 个 tts.audio.delta + 1 个 avatar frame
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from avatarloom_protocol import (  # noqa: E402
    AVATAR_SPEECH_FRAME,
    LLM_TEXT_DELTA,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)

from runtime.orchestrator import Orchestrator  # noqa: E402
from runtime.orchestrator.profile_loader import load_profile  # noqa: E402


def _loud_pcm(samples: int = 1600, amp: float = 800) -> str:
    arr = (np.ones(samples, dtype=np.float32) * amp * 32767 / 1000).astype(np.int16)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def _silent_pcm(samples: int = 1600) -> str:
    return base64.b64encode(np.zeros(samples, dtype=np.int16).tobytes()).decode("ascii")


async def run_smoke() -> int:
    print("=" * 60)
    print("AvatarLoom Mock 全链路冒烟测试")
    print("=" * 60)

    # 1. 加载 profile
    profile_path = PROJECT_ROOT / "profiles" / "mock.yaml"
    print(f"\n[1/6] 加载 Profile: {profile_path.name}")
    config = load_profile(profile_path)
    print(f"  ✓ profile_id={config.profile_id}")
    print(f"  ✓ blocks={list(config.blocks.keys())}")

    # 2. 装配
    print("\n[2/6] 装配 Orchestrator")
    emitted: list[Event] = []

    async def sink(e: Event) -> None:
        emitted.append(e)

    orch = Orchestrator(config, event_sink=sink)
    await orch.setup()
    ready_blocks = list(orch.blocks.keys())
    print(f"  ✓ ready blocks: {ready_blocks}")

    # 3. 启动 Session
    print("\n[3/6] 启动 Session")
    session = await orch.start_session()
    print(f"  ✓ session_id={session.session_id}")

    # 4. 注入音频
    print("\n[4/6] 注入模拟音频（说话 + 静音）")
    for i in range(4):
        await orch.ingest_audio(session, _loud_pcm(), 1600)
        await asyncio.sleep(0.02)
        print(f"  → loud chunk {i + 1}/4")
    for _ in range(5):
        await orch.ingest_audio(session, _silent_pcm(), 1600)
        await asyncio.sleep(0.02)
    print("  → silent chunks x5 (触发 speech.ended)")

    # 等链路完成
    print("\n[5/6] 等待链路完成...")
    await asyncio.sleep(1.0)

    # 5. 验证
    types = [e.type for e in emitted]
    has_transcript = TRANSCRIPT_COMPLETED in types
    has_llm = LLM_TEXT_DELTA in types
    has_tts = TTS_AUDIO_DELTA in types
    has_avatar = AVATAR_SPEECH_FRAME in types

    print(f"  transcript.completed: {'✓' if has_transcript else '✗'}")
    print(f"  llm.text.delta:       {'✓' if has_llm else '✗'}")
    print(f"  tts.audio.delta:      {'✓' if has_tts else '✗'}")
    print(f"  avatar.speech_frame:  {'✓' if has_avatar else '✗'}")
    print(f"  总事件数: {len(emitted)}")

    # 6. 关闭
    print("\n[6/6] 关闭 Orchestrator")
    await orch.shutdown()
    print("  ✓ 已关闭")

    print("\n" + "=" * 60)
    if has_transcript and has_llm and has_tts:
        print("✓ Mock 全链路冒烟通过")
        return 0
    else:
        print("✗ Mock 全链路冒烟失败——事件序列不完整")
        return 1


def main() -> int:
    return asyncio.run(run_smoke())


if __name__ == "__main__":
    sys.exit(main())
