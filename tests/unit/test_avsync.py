"""AVSyncScheduler 单测（对齐 VoxEMW avsync 语义）。"""

from __future__ import annotations

import asyncio

from avatarloom_runtime_gateway.avsync import (
    AUDIO_TICK_SAMPLES,
    SAMPLES_PER_FRAME,
    AVSyncScheduler,
)


def _pcm(samples: int) -> bytes:
    return b"\x01\x00" * samples


class TestAudioLead:
    def test_audio_held_during_lead(self) -> None:
        s = AVSyncScheduler(audio_lead=10.0)  # 大 lead 模拟等待期
        s.feed_audio(_pcm(AUDIO_TICK_SAMPLES * 2))
        # 压后等待期：补静音而非真音频
        assert s.next_audio_tick() == b"\x00" * AUDIO_TICK_SAMPLES * 2

    def test_audio_flows_after_lead(self) -> None:
        s = AVSyncScheduler(audio_lead=0.0)
        s.feed_audio(_pcm(AUDIO_TICK_SAMPLES))
        assert s.next_audio_tick() == _pcm(AUDIO_TICK_SAMPLES)

    def test_partial_tick_pads_silence(self) -> None:
        s = AVSyncScheduler(audio_lead=0.0)
        s.feed_audio(_pcm(AUDIO_TICK_SAMPLES // 2))  # 不足一拍
        assert s.next_audio_tick() == b"\x00" * AUDIO_TICK_SAMPLES * 2


class TestTailFrameDrop:
    def test_zero_pad_tail_frames_dropped(self) -> None:
        """speech 帧序号超出实喂音频时长 = 零填充闭嘴尾帧，逐帧丢而非清队列。"""
        s = AVSyncScheduler(audio_lead=0.0)
        # 喂 2 帧时长的音频（2*640 采样）
        s.feed_audio(_pcm(SAMPLES_PER_FRAME * 2))
        for _ in range(4):  # 引擎因补零多产 2 帧
            s.feed_frame(b"jpeg", True)
        # 前 2 帧交付，后 2 帧丢弃
        assert asyncio.run(s.next_frame_tick()) == b"jpeg"
        assert asyncio.run(s.next_frame_tick()) == b"jpeg"
        assert s.tail_dropped == 0
        # 队列剩 2 个尾帧——下帧到达前会逐帧丢
        asyncio.run(self._drain_two(s))
        assert s.tail_dropped == 2

    async def _drain_two(self, s: AVSyncScheduler) -> list[bytes]:
        # 尾帧被丢弃后队空且有 last_jpeg——next_frame_tick 会重复上一帧返回
        out = []
        out.append(await asyncio.wait_for(s.next_frame_tick(), 1))
        out.append(await asyncio.wait_for(s.next_frame_tick(), 1))
        return out


class TestFlushSuppress:
    def test_flush_suppresses_stale_speech_frames(self) -> None:
        s = AVSyncScheduler(audio_lead=0.0)
        s.feed_audio(_pcm(SAMPLES_PER_FRAME * 10))
        s.feed_frame(b"a", True)
        s.flush()
        # 打断后在途陈旧 speech 帧被封杀（不误杀新回复帧的前提）
        s.feed_frame(b"stale", True)
        assert s.stale_dropped == 1
        assert s.queued_frames == 0
        # 新音频到达解除封杀
        s.feed_audio(_pcm(SAMPLES_PER_FRAME))
        s.feed_frame(b"new", True)
        assert asyncio.run(s.next_frame_tick()) == b"new"

    def test_idle_frames_pass_after_flush(self) -> None:
        s = AVSyncScheduler(audio_lead=0.0)
        s.flush()
        s.feed_frame(b"idle", False)  # idle 帧不受封杀
        assert asyncio.run(s.next_frame_tick()) == b"idle"

    def test_suppression_holds_until_new_audio_arrives(self) -> None:
        # flush 后新音频未到（ready_at=inf）：陈旧 speech 帧持续封杀
        s = AVSyncScheduler(audio_lead=0.0)
        s.flush()
        s.feed_frame(b"stale1", True)
        s.feed_frame(b"stale2", True)
        assert s.stale_dropped == 2
        assert s.queued_frames == 0

    def test_suppression_holds_during_lead_window(self) -> None:
        # 新音频已到但仍在 lead 压后期：此时到达的 speech 帧仍是旧队列陈旧帧
        # （avatar 渲染滞后 ~0.35s > lead 0.25s，新真帧不可能这么早）——
        # "新音频一到就解封"的旧语义会在此窗口放进陈旧帧，推进 _speech_out
        # 后新回复真帧反被丢尾规则误杀
        s = AVSyncScheduler(audio_lead=10.0)  # 大 lead 拉长窗口便于观测
        s.flush()
        s.feed_audio(_pcm(SAMPLES_PER_FRAME * 4))
        s.feed_frame(b"stale", True)
        assert s.stale_dropped == 1
        assert s.queued_frames == 0
        # idle 帧不受影响
        s.feed_frame(b"idle", False)
        assert s.queued_frames == 1


class TestFrameRepeat:
    def test_empty_queue_repeats_last_frame(self) -> None:
        s = AVSyncScheduler(audio_lead=0.0)
        s.feed_frame(b"f1", False)
        assert asyncio.run(s.next_frame_tick()) == b"f1"
        # 队空：等一拍超时后重复上一帧（防定格）
        assert asyncio.run(s.next_frame_tick()) == b"f1"

    def test_close_returns_none(self) -> None:
        s = AVSyncScheduler()
        s.close()
        assert asyncio.run(s.next_frame_tick()) is None
