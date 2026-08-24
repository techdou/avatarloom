"""avtr1_worker StreamEngine 账本与消费窗单测（无 GPU 依赖）。

__init__ 会加载 TRT 引擎（仅服务器 renderer env 可用）——账本/调度语义
独立于渲染，用 __new__ 绕过初始化、手工填账本字段来测。
run_loop 依赖的 avtr1_renderer.types.Chunk 用 fake 模块注入。
"""

from __future__ import annotations

import sys
import threading
import time as time_mod
import types as py_types
from typing import Any

import numpy as np
import pytest

from scripts.avtr1_worker import (
    CHUNK_WINDOW,
    SAMPLE_RATE,
    StreamEngine,
)


def _bare_engine() -> StreamEngine:
    eng = StreamEngine.__new__(StreamEngine)
    eng._buf = np.empty(0, dtype=np.float32)
    eng._pos = 0
    eng._real_len = 0
    eng._tail_faded = False
    eng._cond = threading.Condition()
    eng._closed = False
    eng._pending_image = None
    eng._speech_active = False
    return eng


def _pcm(samples: int, value: float = 0.5) -> np.ndarray:
    return np.full(samples, value, dtype=np.float32)


class TestLedger:
    """生产侧账本：feed 追加 / 补零段丢弃 / reset 复位。"""

    def test_feed_audio_appends(self) -> None:
        eng = _bare_engine()
        eng.feed_audio(_pcm(1000))
        with eng._cond:
            assert eng._real_len == 1000
            assert len(eng._buf) == 1000

    def test_feed_audio_drops_unconsumed_padding(self) -> None:
        # 句尾补零场景：real=1000 + 补零 1000，新音频到达应丢弃未消费补零段
        eng = _bare_engine()
        eng._buf = np.concatenate([_pcm(1000), np.zeros(1000, dtype=np.float32)])
        eng._real_len = 1000
        eng.feed_audio(_pcm(500))
        with eng._cond:
            assert len(eng._buf) == 1500  # 1000 真 + 500 新，补零段已丢
            assert eng._real_len == 1500

    def test_reset_clears_ledger_and_speech_active(self) -> None:
        # 回归锚：reset 不清 _speech_active 会让 idle 判定永假——打断后画面
        # 冻在最后一帧（2026-08-25 review 必改项）
        eng = _bare_engine()
        eng.feed_audio(_pcm(2000))
        eng.set_speech_active(True)
        eng.reset()
        with eng._cond:
            assert eng._real_len == 0
            assert len(eng._buf) == 0
            assert eng._speech_active is False

    def test_close_sets_flag_and_wakes(self) -> None:
        eng = _bare_engine()
        eng.close()
        with eng._cond:
            assert eng._closed is True


class _FakePipeline:
    def __init__(self) -> None:
        self.audios: list[np.ndarray] = []

    def process_chunk(
        self, _avatar: Any, chunk: Any, state: Any, _options: Any
    ) -> tuple[Any, list[Any]]:
        self.audios.append(np.asarray(chunk.audio_speech).copy())
        return state, [py_types.SimpleNamespace(data=None)]


@pytest.fixture()
def fake_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_loop 里 `from avtr1_renderer.types import Chunk`——注入 fake 模块。"""
    fake_pkg = py_types.ModuleType("avtr1_renderer")
    fake_types = py_types.ModuleType("avtr1_renderer.types")

    class Chunk:
        def __init__(self, audio_speech: np.ndarray, audio_listen: np.ndarray) -> None:
            self.audio_speech = audio_speech
            self.audio_listen = audio_listen

    fake_types.Chunk = Chunk
    fake_pkg.types = fake_types
    monkeypatch.setitem(sys.modules, "avtr1_renderer", fake_pkg)
    monkeypatch.setitem(sys.modules, "avtr1_renderer.types", fake_types)


def _wait_until(cond, timeout: float = 3.0) -> None:
    deadline = time_mod.monotonic() + timeout
    while time_mod.monotonic() < deadline:
        if cond():
            return
        time_mod.sleep(0.02)
    raise AssertionError("condition not met within timeout")


class TestRunLoop:
    """消费侧：真实音频满窗消费 / 句尾补零 / idle 分支。"""

    def test_speech_chunk_consumed(self, fake_renderer, monkeypatch) -> None:
        eng = _bare_engine()
        eng._avatar = object()
        eng._state = None
        eng._options = object()
        pipe = _FakePipeline()
        eng.pipeline = pipe
        monkeypatch.setattr(
            StreamEngine, "_to_display", staticmethod(lambda f: np.zeros((2, 2, 3), np.uint8))
        )
        got: list[tuple[np.ndarray, bool]] = []

        def on_frames(frames: np.ndarray, is_idle: bool) -> None:
            got.append((frames, is_idle))

        t = threading.Thread(target=eng.run_loop, args=(on_frames,), daemon=True)
        t.start()
        try:
            eng.feed_audio(_pcm(CHUNK_WINDOW))
            _wait_until(lambda: len(pipe.audios) >= 1)
            # 满窗消费：取出的音频窗 == 输入（未淡出——speech 期间）
            np.testing.assert_allclose(pipe.audios[0], _pcm(CHUNK_WINDOW))
            assert got and not got[0][1]  # speech 帧非 idle
        finally:
            eng.close()

    def test_tail_pads_zeros_after_speech_end(self, fake_renderer, monkeypatch) -> None:
        eng = _bare_engine()
        eng._avatar = object()
        eng._state = None
        eng._options = object()
        pipe = _FakePipeline()
        eng.pipeline = pipe
        monkeypatch.setattr(
            StreamEngine, "_to_display", staticmethod(lambda f: np.zeros((2, 2, 3), np.uint8))
        )

        t = threading.Thread(target=eng.run_loop, args=(lambda f, i: None,), daemon=True)
        t.start()
        try:
            half = CHUNK_WINDOW // 2
            eng.feed_audio(_pcm(half))
            eng.set_speech_active(False)  # 段结束（COMPLETED 语义）
            _wait_until(lambda: len(pipe.audios) >= 1)
            audio = pipe.audios[0]
            assert len(audio) == CHUNK_WINDOW  # 补零到整窗
            # 后半（补零段）必须为 0；前半是衰减后的真实音频（_fade_tail 余弦）
            assert np.all(audio[half:] == 0)
            assert np.any(audio[:half] != 0)
        finally:
            eng.close()

    def test_idle_when_no_audio(self, fake_renderer, monkeypatch) -> None:
        eng = _bare_engine()
        eng._avatar = object()
        eng._state = None
        eng._options = object()
        eng.pipeline = _FakePipeline()
        monkeypatch.setattr(
            StreamEngine, "_to_display", staticmethod(lambda f: np.zeros((2, 2, 3), np.uint8))
        )
        got: list[bool] = []

        t = threading.Thread(
            target=eng.run_loop, args=(lambda f, i: got.append(i),), daemon=True
        )
        t.start()
        try:
            _wait_until(lambda: len(got) >= 1)
            assert got[0] is True  # 无音频且非 speech → idle 帧
            audio = eng.pipeline.audios[0]
            assert np.all(audio == 0)  # idle 喂静音窗
            assert len(audio) == CHUNK_WINDOW
        finally:
            eng.close()

    def test_sample_rate_sanity(self) -> None:
        # 账本单位锚：16kHz——_fade_tail / CHUNK_WINDOW 都以此推算
        assert SAMPLE_RATE == 16000
