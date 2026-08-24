#!/usr/bin/env python
"""AVTR-1 流式说话头 worker（长驻子进程，pixi renderer env 直调）。

语义逐条对齐 VoxEMW avtr1_engine.py（2026-08-21 逐行对账版）：
- 0.2s chunk（3200 采样@16k）产 5 帧@25fps，输入窗 6480（当前 3280 + 前瞻 3280）
- 运动上下文（pipeline state）跨 chunk/打断永续——reset 只清音频缓冲，姿态自然衰减
- 句中欠载（speech_active 而缓冲不足一窗）：停帧等待，不补零（补零插假帧致口型漂移）
- 句尾（speech_active 转 false）仍有真音频尾巴：先 0.5s 余弦淡出（仅模型输入，
  用户听到的音频不变）再立即右补零排空，嘴型自然闭合
- 无活动语音段：静音 chunk 按 0.2s 实时节奏节流产 idle 微动帧
- listen 轨（active listening）v1 不接——我方架构暂无用户麦克风向 avatar 块的通道

与 block 侧协议（stdin JSON 行命令 / stdout 二进制包）：
  入：{"cmd":"ping"} / {"cmd":"audio","pcm":<b64 int16 16k>} / {"cmd":"reset"} /
      {"cmd":"speech_active","on":bool} / {"cmd":"set_image","path":P} /
      {"cmd":"warm"} / {"cmd":"shutdown"}
      带 "id" 的命令回控制包；audio/speech_active/reset 约定不带 id（fire-and-forget）
  出：stdout 二进制包 [1B type][4B BE len][payload]
      type 0x01=JSON 控制（含 ready/命令应答）；0x02=帧（payload=1B tag+JPEG，
      tag 0x00=idle / 0x01=speech）
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import faulthandler
import json
import os
import struct
import sys
import threading
import time
from pathlib import Path

# 启动探针：worker 段错误（SIGSEGV）无输出时，用这些标记定位崩溃的 import。
_DBG = open("/tmp/avtr1_worker_boot.log", "a", buffering=1)  # noqa: SIM115 -- 进程级探针日志
faulthandler.enable(file=_DBG)


def _probe(msg: str) -> None:
    _DBG.write(f"{msg}\n")


_probe("A1_IMPORT_START")
import queue  # noqa: E402

import numpy as np  # noqa: E402

_probe("A2_NUMPY_OK")

SAMPLE_RATE = 16000
FPS = 25
CHUNK_STEP = 3200                      # 0.2s（5 帧 × 640）
CHUNK_WINDOW = (5 + 5) * 640 + 80      # 6480 = 当前 3280 + 前瞻 3200+80
CHUNK_SECONDS = CHUNK_STEP / SAMPLE_RATE
OUT_W, OUT_H = 1280, 720
WARMUP_CHUNKS = 2
TAIL_FADE_SECONDS = 0.5   # 句尾淡出（防模型急回中性位"说完立马摆正"）
JPEG_QUALITY = 95

# stdout 包类型
PKT_CONTROL = 0x01
PKT_FRAME = 0x02
FRAME_TAG_IDLE = 0x00
FRAME_TAG_SPEECH = 0x01

_WRITE_LOCK = threading.Lock()


def _write_packet(pkt_type: int, payload: bytes) -> None:
    with _WRITE_LOCK:
        sys.stdout.buffer.write(bytes([pkt_type]) + struct.pack(">I", len(payload)) + payload)
        sys.stdout.buffer.flush()


def _reply(obj: dict) -> None:
    _write_packet(PKT_CONTROL, json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _encode_jpeg(frame_rgb: np.ndarray) -> bytes:
    import cv2

    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    # 轻量锐化（unsharp mask）：找回 JPEG 压缩丢掉的边缘
    blur = cv2.GaussianBlur(bgr, (0, 0), 1.0)
    bgr = cv2.addWeighted(bgr, 1.35, blur, -0.35, 0)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return buf.tobytes()


class StreamEngine:
    """AVTR-1 流式引擎：音频账本法调度，所有 pipeline 调用串行在 inference 线程。"""

    def __init__(self, image_path: str, storage: str | None, bg_id: str, cfg_self_audio: float):
        if storage:
            os.environ.setdefault("AVTR1_LOCAL_STORAGE", storage)
        if not os.environ.get("AVTR1_LOCAL_STORAGE"):
            raise RuntimeError("AVTR1_LOCAL_STORAGE 未设置（权重/TRT 引擎根目录）")

        from avtr1_renderer.avatar_loader import AvatarLoader
        from avtr1_renderer.avtr1_artifact_manager import get_artifact_manager
        from avtr1_renderer.pipeline import Pipeline
        from avtr1_renderer.types import RenderOptions

        _probe("A3_RENDERER_IMPORTED")
        self.pipeline, _ = Pipeline.from_artifacts(avatar_ids=None, download_workers=1)
        mgr = get_artifact_manager()
        mask_path = (
            mgr.get_artifact_path("pasteback_mask")
            if "pasteback_mask" in mgr._artifacts
            else None
        )
        self._loader = AvatarLoader(
            engine_files={
                "insightface_det": mgr.get_artifact_path("insightface_det"),
                "landmark106": mgr.get_artifact_path("landmark106"),
                "landmark203": mgr.get_artifact_path("landmark203"),
                "appearance_extractor": mgr.get_artifact_path("appearance_extractor"),
                "motion_extractor": mgr.get_artifact_path("motion_extractor"),
            },
            mask_template_path=mask_path,
            out_h=OUT_H,
            out_w=OUT_W,
            max_dim=max(OUT_H, OUT_W),
        )
        self._options = RenderOptions(
            pixel_format="yuv_i420", bg_id=bg_id, stream_frames=False,
            cfg_self_audio=cfg_self_audio,
        )
        self._avatar = None
        self._load_avatar(image_path)
        self._state = None  # 跨 chunk 运动上下文（None=冷启动）

        # 音频流账本：_buf = 未消费采样流（含句尾补零），_pos = 已消费帧边界，
        # _real_len = 其中真实音频长度（补零只在末尾，新音频到达即丢弃未消费补零段）
        self._buf = np.empty(0, dtype=np.float32)
        self._pos = 0
        self._real_len = 0
        self._tail_faded = False

        self._cond = threading.Condition()
        self._closed = False
        self._pending_image: str | None = None
        self._speech_active = False

    def _load_avatar(self, image_path: str) -> None:
        self._avatar = self._loader.load(Path(image_path), avatar_id=str(image_path))
        self._avatar_path = image_path

    # ── 生产侧（stdin 线程调用）──

    def feed_audio(self, pcm_f32: np.ndarray) -> None:
        with self._cond:
            self._buf = np.concatenate([self._buf[: self._real_len], pcm_f32])
            self._real_len += len(pcm_f32)
            self._tail_faded = False
            self._cond.notify()

    def reset(self) -> None:
        """打断：丢弃未消费音频；运动上下文保留（静音 chunk 让姿态自然衰减）。

        _speech_active 必须一并复位——否则打断后 idle 判定
        ``unconsumed == 0 and not _speech_active`` 永假，画面冻在最后一帧。
        （block 侧 reset 只发 reset cmd 不发 speech_active off，且打断后
        block 的 _speaking 已置 False，下一轮 COMPLETED 不会补发 off。）"""
        with self._cond:
            self._buf = np.empty(0, dtype=np.float32)
            self._pos = 0
            self._real_len = 0
            self._tail_faded = False
            self._speech_active = False
            self._cond.notify()

    def set_image(self, image_path: str) -> None:
        with self._cond:
            self._pending_image = image_path
            self._cond.notify()

    def set_speech_active(self, on: bool) -> None:
        with self._cond:
            self._speech_active = on
            self._cond.notify()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify()

    # ── 消费侧（inference 线程）──

    @staticmethod
    def _to_display(frame) -> np.ndarray:
        import cv2

        rgb = cv2.cvtColor(frame.data, cv2.COLOR_YUV2RGB_I420)
        return cv2.resize(rgb, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)

    def _fade_tail(self) -> None:
        n = min(int(TAIL_FADE_SECONDS * SAMPLE_RATE), self._real_len - self._pos)
        if n <= 0:
            return
        ramp = (np.cos(np.linspace(0, np.pi / 2, n)) ** 1.5).astype(np.float32)
        self._buf[self._real_len - n : self._real_len] *= ramp

    def run_loop(self, on_frames) -> None:
        from avtr1_renderer.types import Chunk

        _probe("A4_LOOP_START")
        last_idle_at = 0.0
        while True:
            with self._cond:
                while not self._closed:
                    unconsumed = self._real_len - self._pos
                    buffered = len(self._buf) - self._pos
                    if buffered >= CHUNK_WINDOW:
                        break
                    if 0 < unconsumed < CHUNK_WINDOW and not self._speech_active:
                        if not self._tail_faded:
                            self._fade_tail()
                            self._tail_faded = True
                        pad = CHUNK_WINDOW - buffered
                        self._buf = np.concatenate([self._buf, np.zeros(pad, dtype=np.float32)])
                        continue
                    if unconsumed == 0 and not self._speech_active:
                        # idle 微动：0.2s 实时节流
                        wait = last_idle_at + CHUNK_SECONDS - time.monotonic()
                        if wait > 0:
                            self._cond.wait(timeout=wait)
                            continue
                        break
                    self._cond.wait(timeout=0.5)
                if self._closed:
                    return
                if self._pending_image:
                    self._load_avatar(self._pending_image)
                    self._state = None  # state 是 avatar 相关的，换图必须冷启动
                    self._pending_image = None
                is_idle = (self._real_len - self._pos) == 0
                if is_idle:
                    audio = np.zeros(CHUNK_WINDOW, dtype=np.float32)
                    last_idle_at = time.monotonic()
                else:
                    audio = self._buf[self._pos : self._pos + CHUNK_WINDOW]
                    self._pos += CHUNK_STEP
                    if self._pos > 0:
                        self._buf = self._buf[self._pos :]
                        self._real_len = max(0, self._real_len - self._pos)
                        self._pos = 0
            chunk = Chunk(audio_speech=audio,
                          audio_listen=np.zeros(CHUNK_WINDOW, dtype=np.float32))
            self._state, frames_iter = self.pipeline.process_chunk(
                self._avatar, chunk, self._state, self._options
            )
            frames = np.stack([self._to_display(f) for f in frames_iter])
            on_frames(frames, is_idle)

    def warmup(self, on_frames) -> None:
        """静音跑 2+ chunk：TRT 首个 chunk 初始化 + 运动上下文预填。"""
        self.feed_audio(np.zeros(CHUNK_WINDOW + WARMUP_CHUNKS * CHUNK_STEP, dtype=np.float32))
        while True:
            with self._cond:
                done = self._real_len - self._pos <= 0
            if done:
                break
            threading.Event().wait(0.1)
        self.reset()
        _probe("A5_WARM_DONE")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage", default="")
    ap.add_argument("--image", required=True)
    ap.add_argument("--bg", default="plain_white")
    ap.add_argument("--cfg-self-audio", type=float, default=2.0)
    args = ap.parse_args()

    engine = StreamEngine(args.image, args.storage or None, args.bg, args.cfg_self_audio)
    _probe("A6_ENGINE_OK")

    # 帧通路：推理线程只入队原始帧（满丢最旧）；JPEG 编码在专用线程
    raw_q: queue.Queue = queue.Queue(maxsize=FPS * 2)

    def on_frames(frames: np.ndarray, is_idle: bool) -> None:
        tag = FRAME_TAG_IDLE if is_idle else FRAME_TAG_SPEECH
        for frame in frames:
            if raw_q.full():
                with contextlib.suppress(queue.Empty):
                    raw_q.get_nowait()
            raw_q.put_nowait((frame, tag))

    def _encoder() -> None:
        encode_errors = 0
        while True:
            frame, tag = raw_q.get()
            try:
                jpeg = _encode_jpeg(frame)
            except Exception:
                # 编码异常计数进探针日志（不能走 stdout——会污染二进制协议流）；
                # 持续失败的表现是"画面全黑但进程活着"，有计数才能定位
                encode_errors += 1
                _probe(f"ENCODE_ERROR_{encode_errors}")
                continue
            _write_packet(PKT_FRAME, bytes([tag]) + jpeg)

    threading.Thread(target=_encoder, daemon=True).start()
    threading.Thread(target=engine.run_loop, args=(on_frames,), daemon=True).start()
    engine.warmup(on_frames)
    _reply({"type": "ready"})

    # 命令循环：带 id 的应答；audio/speech_active/reset 不带 id 不应答
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        cmd = req.get("cmd")
        rid = req.get("id")
        try:
            if cmd == "ping":
                if rid is not None:
                    _reply({"id": rid, "ok": True})
            elif cmd == "audio":
                pcm = np.frombuffer(base64.b64decode(req["pcm"]), dtype=np.int16)
                engine.feed_audio(pcm.astype(np.float32) / 32768.0)
            elif cmd == "reset":
                engine.reset()
            elif cmd == "speech_active":
                engine.set_speech_active(bool(req.get("on")))
            elif cmd == "set_image":
                engine.set_image(str(req["path"]))
                if rid is not None:
                    _reply({"id": rid, "ok": True})
            elif cmd == "warm":
                # 引擎已在启动时预热；重复 warm 只应答（幂等）
                if rid is not None:
                    _reply({"id": rid, "ok": True})
            elif cmd == "shutdown":
                engine.close()
                if rid is not None:
                    _reply({"id": rid, "ok": True})
                return 0
        except Exception as e:
            if rid is not None:
                _reply({"id": rid, "ok": False, "error": str(e)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
