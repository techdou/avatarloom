#!/usr/bin/env python
"""SoulX-FlashHead 流式说话头服务（单文件版，移植自 techdou/VoxEMW）。

协议（WebSocket，默认 127.0.0.1:8767）：
  入（JSON 文本帧）：
    {"type":"audio","pcm":"<base64 int16 16k mono>"}  喂音频
    {"type":"reset"}                                    utterance 边界/打断：清缓冲+运动上下文归位
    {"type":"set_image","path":"<服务器本地路径>"}        切换肖像
  出：
    二进制 JPEG 帧（512x512，一帧一条，目标 25fps）
    JSON：{"type":"ready"} / {"type":"error","message":...}

实现要点（对齐 SoulX-FlashHead gradio_app_streaming.py 的 producer 模式）：
- 推理固定消费 15360 采样（0.96s）/ chunk，产出 24 帧（25fps）；
- 音频上下文为 8s 零填充环形缓冲，wav2vec2 每 chunk 重提一次；
- utterance 结束/打断 → reset → pipeline.reset_person_name()（运动上下文归位）；
- 欠载策略：不足一 chunk 时静默超时后用零填充补齐全生成，让嘴型自然闭合；
- torch.compile 首次 chunk 编译很慢，启动时用静音跑 2 个 chunk 预热。

运行环境：独立 py310 venv（torch 2.7.1 cu128 / transformers 4.57.3 / xformers / flash_attn 可选）。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import logging
import os
import sys
import threading
from collections import deque
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
# FlashHead 推理代码由 scripts/setup_flashhead.sh 克隆到 vendor/SoulX-FlashHead
sys.path.insert(0, str(REPO_ROOT / "vendor" / "SoulX-FlashHead"))
# flash_head 内部按 CWD 相对路径读配置（import 时 open("flash_head/configs/infer_params.yaml")）
os.chdir(REPO_ROOT / "vendor" / "SoulX-FlashHead")

logger = logging.getLogger("flashhead_service")

# 流式常量（来自 flash_head/configs/infer_params.yaml：frame_num=33、motion_frames_latent_num=2、
#   tgt_fps=25、sample_rate=16000、cached_audio_duration=8）
SAMPLE_RATE = 16000
TGT_FPS = 25
CACHE_SECONDS = 8
AUDIO_END_IDX = CACHE_SECONDS * TGT_FPS  # 200
FRAME_NUM = 33
AUDIO_START_IDX = AUDIO_END_IDX - FRAME_NUM  # 167
MOTION_FRAMES_NUM = 9  # (2-1)*8+1（Lite VAE 时间 stride 8）
CHUNK_SAMPLES = (FRAME_NUM - MOTION_FRAMES_NUM) * SAMPLE_RATE // TGT_FPS  # 15360 = 0.96s
WARMUP_CHUNKS = 2

# 帧 tag（下行二进制首字节，对齐 VoxEMW service.py）
FRAME_TAG_IDLE = 0x00
FRAME_TAG_SPEECH = 0x01


class AvatarEngine:
    """FlashHead 推理引擎：所有 pipeline 调用都序列化在 inference 线程里。"""

    def __init__(self, model_dir: str, wav2vec_dir: str, image_path: str, seed: int = 9999):
        import numpy as np  # noqa: F401
        from flash_head.inference import (
            get_base_data,
            get_infer_params,
            get_pipeline,
        )

        logger.info("加载 FlashHead Lite: %s", model_dir)
        self.pipeline = get_pipeline(
            world_size=1,
            ckpt_dir=model_dir,
            model_type="lite",
            wav2vec_dir=wav2vec_dir,
        )
        params = get_infer_params()
        assert params["sample_rate"] == SAMPLE_RATE and params["tgt_fps"] == TGT_FPS, (
            f"infer_params 与本服务常量不一致: {params}"
        )
        self.seed = seed
        self.image_path = image_path
        get_base_data(
            self.pipeline,
            cond_image_path_or_dir=image_path,
            base_seed=seed,
            use_face_crop=True,
        )
        self._new_audio_dq()

        import numpy as _np

        self._pending = _np.empty(0, dtype=_np.float32)
        self._cond = threading.Condition()
        self._closed = False
        self._reset_motion = False
        self._pending_image = None
        self._inference_error: str | None = None
        # 门控状态（对齐 VoxEMW service.py）：说话期间禁 idle 生成，
        # 句间停顿 pending 排空时插入 idle 帧会被前端直画卡画面
        self._speech_active = False
        self._idle_mode = "calm"  # listening|thinking|calm（决定待机驱动）
        self.on_frames = None  # 单客户端设计：ws 连接建立时接管帧流

    def _new_audio_dq(self):
        self.audio_dq = deque(
            [0.0] * (SAMPLE_RATE * CACHE_SECONDS),
            maxlen=SAMPLE_RATE * CACHE_SECONDS,
        )

    # ---- 生产侧（ws 线程调用，只碰累积缓冲）----

    def feed_audio(self, pcm_f32) -> None:
        with self._cond:
            import numpy as np

            self._pending = np.concatenate([self._pending, pcm_f32])
            self._cond.notify()

    def reset(self) -> None:
        """utterance 边界/打断：丢弃未消费音频，标记运动上下文归位。"""
        with self._cond:
            import numpy as np

            self._pending = np.empty(0, dtype=np.float32)
            self._reset_motion = True
            self._cond.notify()

    def set_image(self, image_path: str) -> None:
        with self._cond:
            self._pending_image = image_path
            self._cond.notify()

    def set_speech_active(self, active: bool) -> None:
        """助手说话期间置 True：禁止 idle 生成（防句间停顿插 idle 帧卡画面）。"""
        with self._cond:
            self._speech_active = bool(active)
            self._cond.notify()

    def set_idle_mode(self, mode: str) -> None:
        """待机驱动模式：listening|thinking|calm。FlashHead 无 murmur，均用静音。"""
        with self._cond:
            self._idle_mode = mode if mode in ("listening", "thinking", "calm") else "calm"
            self._cond.notify()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify()

    # ---- 消费侧（inference 线程）----

    def run_inference_loop(self, on_frames) -> None:
        """阻塞循环：凑满一 chunk 真实音频才生成；0.5s 无新音频且缓冲有残留
        → 零填充补全最后 chunk（句尾嘴型自然闭合）。

        任何异常都不得让本静默挂死：捕获后清空 _pending、记 _inference_error，
        warmup 与 ws 收发循环据此把状态暴露给 orchestrator，而不是无限等待。
        """
        import time as _time

        import numpy as np
        from flash_head.inference import get_audio_embedding, run_pipeline

        chunk_seconds = CHUNK_SAMPLES / SAMPLE_RATE  # 0.96s
        last_idle_at = 0.0
        while True:
            try:
                with self._cond:
                    is_idle = False
                    while not self._closed and len(self._pending) < CHUNK_SAMPLES:
                        # 无音频：非 speech_active 且 idle 节流到期 → 产 idle 帧。
                        # _reset_motion/_pending_image 不挡 idle——它们会在下方
                        # 公共路径被消费（reset 归位/换肖像），否则 reset 后无音频
                        # 时 idle 分支被永久挡住导致停帧。
                        if not self._speech_active:
                            now = _time.monotonic()
                            wait = last_idle_at + chunk_seconds - now
                            # 进入 idle 评估即刷新基准：被音频唤醒后不会因旧基准立即重产
                            last_idle_at = now
                            if wait <= 0:
                                is_idle = True
                                break
                            self._cond.wait(timeout=wait)
                            continue
                        notified = self._cond.wait(timeout=0.5)
                        if not notified and len(self._pending) > 0:
                            break  # 静默超时：句尾尾牙零填充生成
                    if self._closed:
                        return
                    if is_idle:
                        # idle 帧：静音驱动（不抄 murmur——已弃用），
                        # 保持运动上下文，不做 reset 归位
                        chunk = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
                    else:
                        chunk = self._pending[:CHUNK_SAMPLES]
                        self._pending = self._pending[CHUNK_SAMPLES:]
                        if len(chunk) < CHUNK_SAMPLES:
                            chunk = np.pad(chunk, (0, CHUNK_SAMPLES - len(chunk)))
                    if self._reset_motion:
                        self._new_audio_dq()
                        self.pipeline.reset_person_name()
                        self._reset_motion = False
                    if self._pending_image:
                        from flash_head.inference import get_base_data

                        logger.info("切换数字人肖像: %s", self._pending_image)
                        get_base_data(
                            self.pipeline,
                            cond_image_path_or_dir=self._pending_image,
                            base_seed=self.seed,
                            use_face_crop=True,
                        )
                        self._new_audio_dq()
                        self._pending_image = None
                self.audio_dq.extend(chunk.tolist())
                emb = get_audio_embedding(
                    self.pipeline,
                    np.array(self.audio_dq),
                    AUDIO_START_IDX,
                    AUDIO_END_IDX,
                )
                video = run_pipeline(self.pipeline, emb)
                frames = video[MOTION_FRAMES_NUM:].cpu().numpy().astype("uint8")
                on_frames(frames, is_idle)
            except Exception as e:
                logger.exception("flashhead inference loop crashed")
                with self._cond:
                    import numpy as _np

                    self._pending = _np.empty(0, dtype=_np.float32)
                    self._inference_error = repr(e)
                    self._cond.notify_all()
                return

    def warmup(self, on_frames, timeout: float = 300.0) -> None:
        import numpy as np

        logger.info("FlashHead 预热（torch.compile 首个 chunk 很慢）...")
        for _ in range(WARMUP_CHUNKS):
            self.feed_audio(np.zeros(CHUNK_SAMPLES, dtype=np.float32))
        import time

        deadline_ts = time.monotonic() + timeout
        while True:
            with self._cond:
                if self._inference_error is not None:
                    raise RuntimeError(
                        f"flashhead inference loop crashed during warmup: "
                        f"{self._inference_error}"
                    )
                remaining = len(self._pending)
            if remaining == 0:
                break
            if time.monotonic() >= deadline_ts:
                raise TimeoutError(
                    f"flashhead warmup did not drain within {timeout:.0f}s "
                    f"({remaining} samples pending)"
                )
            threading.Event().wait(0.1)
        logger.info("FlashHead 预热完成")


def _encode_jpeg(frame_rgb, quality: int) -> bytes:
    import cv2

    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    # 轻量锐化（unsharp mask）：找回 JPEG 压缩丢掉的边缘，半径小强度低不过曝
    blur = cv2.GaussianBlur(bgr, (0, 0), 1.0)
    bgr = cv2.addWeighted(bgr, 1.35, blur, -0.35, 0)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return buf.tobytes()


async def _serve(ws, engine: AvatarEngine, jpeg_quality: int) -> None:
    """单个 orchestrator 连接：收音频/控制消息，推 JPEG 帧。"""
    import queue as _queue

    import numpy as np

    loop = asyncio.get_running_loop()
    out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=TGT_FPS * 4)
    raw_queue: _queue.Queue = _queue.Queue(maxsize=TGT_FPS * 2)

    def on_frames(frames, is_idle: bool = False) -> None:
        # 推理线程只入队原始帧（满则丢最旧）；JPEG 编码在专用线程，
        # 避免每 chunk 24 帧的编码耗时（q85 约 0.2-0.3s）阻塞下一个 chunk 生成。
        # 每帧带 tag：0x00=idle（待机微动，前端直画）、0x01=speech（进口型队列）
        tag = FRAME_TAG_IDLE if is_idle else FRAME_TAG_SPEECH
        for frame in frames:
            if raw_queue.full():
                with contextlib.suppress(_queue.Empty):
                    raw_queue.get_nowait()
            raw_queue.put_nowait((tag, frame))

    def _encoder() -> None:
        while True:
            tag, frame = raw_queue.get()
            data = _encode_jpeg(frame, jpeg_quality)
            loop.call_soon_threadsafe(_offer, bytes([tag]) + data)

    def _offer(data: bytes) -> None:
        if out_queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                out_queue.get_nowait()
        out_queue.put_nowait(data)

    engine.on_frames = on_frames  # 单客户端设计：最后一个连接接管帧流
    threading.Thread(target=_encoder, daemon=True).start()

    async def sender() -> None:
        while True:
            data = await out_queue.get()
            await ws.send(data)

    send_task = asyncio.create_task(sender())
    await ws.send(json.dumps({"type": "ready"}))
    try:
        async for message in ws:
            if not isinstance(message, str):
                continue
            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "audio":
                pcm = np.frombuffer(base64.b64decode(event["pcm"]), dtype=np.int16)
                engine.feed_audio(pcm.astype(np.float32) / 32768.0)
            elif etype == "reset":
                engine.reset()
            elif etype == "set_image":
                engine.set_image(event["path"])
            elif etype == "speech_active":
                engine.set_speech_active(bool(event.get("on", False)))
            elif etype == "idle_mode":
                engine.set_idle_mode(str(event.get("mode", "calm")))
    finally:
        send_task.cancel()
        engine.on_frames = None


def main() -> None:
    parser = argparse.ArgumentParser(description="AvatarLoom FlashHead 数字人服务")
    parser.add_argument("--model-dir", default="/root/autodl-tmp/models/SoulX-FlashHead-1_3B")
    parser.add_argument("--wav2vec-dir", default="/root/autodl-tmp/models/wav2vec2-base-960h")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--image", required=True, help="初始肖像（服务器本地路径）")
    parser.add_argument("--jpeg-quality", type=int, default=85)
    parser.add_argument("--seed", type=int, default=9999)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    engine = AvatarEngine(args.model_dir, args.wav2vec_dir, args.image, seed=args.seed)

    import websockets

    async def _main() -> None:
        def on_frames(frames, is_idle: bool = False) -> None:
            cb = engine.on_frames
            if cb:
                cb(frames, is_idle)

        thread = threading.Thread(
            target=engine.run_inference_loop,
            args=(on_frames,),
            daemon=True,
        )
        thread.start()
        # warmup 放后台线程——先 bind 端口让 block 能连上，
        # torch.compile 首次预热（Blackwell 上可能 >180s）不再阻塞端口绑定
        warmup_thread = threading.Thread(
            target=engine.warmup,
            args=(on_frames,),
            daemon=True,
        )
        warmup_thread.start()
        async with websockets.serve(
            lambda ws: _serve(ws, engine, args.jpeg_quality),
            args.host,
            args.port,
        ):
            logger.info("数字人服务就绪: ws://%s:%d (warmup 后台进行中)", args.host, args.port)
            await asyncio.Future()  # 永久运行

    asyncio.run(_main())


if __name__ == "__main__":
    main()
