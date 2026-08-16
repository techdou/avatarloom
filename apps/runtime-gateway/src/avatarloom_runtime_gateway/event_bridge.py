"""Orchestrator 事件桥接 + 三队列下行调度。

从 ws_handler.py 抽出的下行链路：接收 Orchestrator emit 的事件，按类型分发到
三条下行队列（控制 / 音频 / 视频），独立任务按优先级发送给浏览器。

队列策略（AL-P2-006）：
- 控制（512，阻塞 2s 后丢）：状态/错误/边界事件，量小，几乎不满
- 音频（64，丢最旧）：TTS PCM 32ms/块 ≈ 2s 缓冲，队满跳段
- 视频（32，丢最旧）：Avatar 25fps ≈ 1.3s 缓冲，队满跳帧

下行优先级：控制 > 音频 > 视频。每轮从控制队列开始轮询，发一条即重排——
控制事件绝对优先；全空时 5ms 短睡眠（25fps 帧间隔 40ms，无感）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    AVATAR_VIDEO_READY,
    RESPONSE_DONE,
    RUN_STARTED,
    SESSION_STATE_CHANGED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    VISION_REQUEST,
    VISION_RESULT,
    Event,
)
from fastapi import WebSocket
from starlette.websockets import WebSocketState

from avatarloom_runtime_gateway.protocol import (
    TAG_AVATAR_JPEG,
    TAG_TTS_PCM_DOWNLINK,
)
from runtime.recorder import RunRecorder
from runtime.session import Session

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def put_drop_oldest(q: asyncio.Queue[bytes], item: bytes) -> None:
    """非阻塞入队；队满丢最旧（音频跳段/视频跳帧，绝不反压事件出口）。"""
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        pass


class OrchestratorEventBridge:
    """Orchestrator 事件出口 → 浏览器下行链路。

    持三条下行队列 + recorder + session 引用（取 profile/persona 用于 recorder）。
    由 WebSocketSession 持有；setup 成功后 session 会设置 ``recorder`` 和
    ``session_ref``，cleanup 时调 ``stop`` 回收 downlink 任务 + recorder。

    ``is_closed`` 是查 ``WebSocketSession._closed`` 的回调——下行发送循环靠它
    感知会话结束（不能直接持 session 引用避免循环依赖）。
    """

    def __init__(
        self,
        ws: WebSocket,
        is_closed: Callable[[], bool],
    ) -> None:
        self.ws = ws
        self._is_closed = is_closed

        # 下行三队列（AL-P2-006）
        # 控制事件量小（状态/错误/边界），512 深度几乎不会满；
        # 真满说明客户端已不消费——enqueue_json 会短等待 2s 后丢弃并告警。
        self._control_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        # TTS PCM：32ms/块，64 块 ≈ 2s 缓冲；队满丢最旧（音频可跳段）
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        # Avatar 帧：25fps，32 帧 ≈ 1.3s 缓冲；队满丢最旧（视频可跳帧）
        self._video_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)

        self._downlink_task: asyncio.Task[None] | None = None
        # 下行最近一次成功发送时间——run() 主循环的 90s idle 超时按下行活动顺延
        # （AL-P2-007：半开连接断网未发 FIN，下行仍在走时不算 idle）
        self._last_downlink_at = time.monotonic()

        # recorder / session_ref 在 _start_session 成功后由 session 注入。
        # 用 Optional 属性表示"装配中"状态，事件出口在它们就绪前也能被调
        # （虽然实际上 setup 成功前 orchestrator 不会 emit 业务事件）。
        self.recorder: RunRecorder | None = None
        self.session_ref: Session | None = None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def last_downlink_at(self) -> float:
        """最近一次成功下行的时间（monotonic）——供主循环 idle 超时判断读。"""
        return self._last_downlink_at

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动下行发送任务。"""
        if self._downlink_task is None or self._downlink_task.done():
            self._downlink_task = asyncio.create_task(self._downlink_sender())

    async def stop(self) -> None:
        """停止下行任务 + flush recorder。

        cleanup 流程调用——cancel downlink task 后等待退出，再把未 finalize
        的 Run 收尾（events.jsonl 句柄、metrics/transcript 落盘）。
        """
        if self._downlink_task is not None:
            self._downlink_task.cancel()
            try:
                await self._downlink_task
            except asyncio.CancelledError:
                pass
            self._downlink_task = None

        if self.recorder is not None:
            try:
                await self.recorder.shutdown()
            except Exception:
                logger.exception("recorder shutdown error")
            self.recorder = None

    # ------------------------------------------------------------------
    # Orchestrator 事件 → 下行
    # ------------------------------------------------------------------

    async def on_orchestrator_event(self, event: Event) -> None:
        """Orchestrator emit 的事件出口——转发给浏览器。

        - session.* / transcript.* / llm.* / response.* → JSON 下行
        - tts.audio.delta → 二进制 PCM 下行（tag + PCM）+ JSON 元数据
        - avatar.*_frame → 二进制 JPEG 下行（tag + 子tag + JPEG）+ JSON 元数据
        """
        # 新一轮 Run：在 record() 之前 start_run，保证后续（含本事件）都被记录
        if (
            event.type == RUN_STARTED
            and self.recorder
            and event.run_id
            and not self.recorder.is_active(event.run_id)
        ):
            await self.recorder.start_run(
                event.run_id,
                event.session_id,
                self.session_ref.profile_id if self.session_ref else "mock",
                persona_id=self.session_ref.persona_id if self.session_ref else None,
            )

        # Recorder 记录
        if self.recorder and event.run_id:
            await self.recorder.record(event)

        # 状态变更/会话事件
        if event.type == SESSION_STATE_CHANGED:
            await self.enqueue_json(
                {
                    "type": "session.state_changed",
                    "payload": event.payload,
                }
            )
        # 注意：orchestrator 内部 emit 的 "session.started"（session.start()）不转发——
        # ws_handler._start_session 成功后会发一条 payload 更完整的 session.started
        # （含 state/degraded）。转发 orchestrator 那条会导致前端收到双份，reducer
        # 二次重置还会清掉两条之间到达的事件流条目。
        elif event.type == TRANSCRIPT_COMPLETED:
            await self.enqueue_json(
                {
                    "type": "transcript.completed",
                    "payload": event.payload,
                }
            )
        elif event.type == RUN_STARTED:
            # 通知前端新 Run 开始（Recorder 已在上方的 start_run 早启动逻辑里就绪）
            await self.enqueue_json({"type": "run.started", "payload": event.payload})
        elif event.type == "llm.text.delta":
            await self.enqueue_json({"type": "llm.text.delta", "payload": event.payload})
        elif event.type == "llm.text.done":
            await self.enqueue_json({"type": "llm.text.done", "payload": event.payload})
        elif event.type == RESPONSE_DONE:
            await self.enqueue_json({"type": "response.done", "payload": event.payload})
            # 结束 Run 记录
            if self.recorder and event.run_id and self.recorder.is_active(event.run_id):
                await self.recorder.finalize_run(event.run_id)

        # Vision：触发词命中 → 请求浏览器截帧；分析结果 → 下行描述
        elif event.type == VISION_REQUEST:
            await self.enqueue_json({"type": "vision.request", "payload": event.payload})
        elif event.type == VISION_RESULT:
            await self.enqueue_json({"type": "vision.result", "payload": event.payload})

        # TTS 音频：二进制下行 + JSON 元数据
        elif event.type == TTS_AUDIO_DELTA:
            pcm_b64 = event.payload.get("pcm_b64", "")
            if pcm_b64:
                try:
                    pcm = base64.b64decode(pcm_b64)
                    # 下行格式：0x03 + PCM；音频队列非阻塞丢最旧（不反压事件出口）
                    put_drop_oldest(self._audio_queue, bytes([TAG_TTS_PCM_DOWNLINK]) + pcm)
                except Exception:
                    logger.warning("TTS audio base64 decode failed——audio chunk dropped", exc_info=True)
            # 元数据（不含 pcm_b64，减小 JSON 体积）——控制队列，不丢
            meta = {k: v for k, v in event.payload.items() if k != "pcm_b64"}
            await self.enqueue_json({"type": "tts.audio.delta", "payload": meta})

        elif event.type == TTS_AUDIO_COMPLETED:
            await self.enqueue_json({"type": "tts.audio.completed", "payload": event.payload})

        elif event.type == AVATAR_VIDEO_READY:
            await self.enqueue_json(
                {"type": "avatar.video.ready", "payload": event.payload}
            )

        # Avatar 帧：二进制下行
        elif event.type in (AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME):
            frame_b64 = event.payload.get("frame_b64", "")
            if frame_b64:
                try:
                    jpeg = base64.b64decode(frame_b64)
                    # 下行格式：0x01 + 0x00/0x01(子tag) + JPEG；视频队列丢最旧
                    sub_tag = 0x01 if event.type == AVATAR_SPEECH_FRAME else 0x00
                    put_drop_oldest(self._video_queue, bytes([TAG_AVATAR_JPEG, sub_tag]) + jpeg)
                except Exception:
                    logger.warning("avatar frame base64 decode failed——frame dropped", exc_info=True)

    async def _downlink_sender(self) -> None:
        """独立任务：三队列优先级调度发送（控制 > 音频 > 视频）。

        每轮从 control 开始轮询，发一条即重排——控制事件绝对优先；
        全空时 5ms 短睡眠（25fps 帧间隔 40ms，无感）。避免阻塞 Orchestrator。
        """
        try:
            while not self._is_closed():
                sent = False
                # 控制队列（JSON）
                try:
                    ctrl = self._control_queue.get_nowait()
                    if self.ws.client_state != WebSocketState.CONNECTED:
                        break

                    await self.ws.send_text(json.dumps(ctrl, ensure_ascii=False))
                    sent = True
                    self._last_downlink_at = time.monotonic()
                except asyncio.QueueEmpty:
                    pass
                # 音频队列
                if not sent:
                    try:
                        audio = self._audio_queue.get_nowait()
                        if self.ws.client_state != WebSocketState.CONNECTED:
                            break
                        await self.ws.send_bytes(audio)
                        sent = True
                        self._last_downlink_at = time.monotonic()
                    except asyncio.QueueEmpty:
                        pass
                # 视频队列
                if not sent:
                    try:
                        video = self._video_queue.get_nowait()
                        if self.ws.client_state != WebSocketState.CONNECTED:
                            break
                        await self.ws.send_bytes(video)
                        sent = True
                        self._last_downlink_at = time.monotonic()
                    except asyncio.QueueEmpty:
                        pass
                if not sent:
                    await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("downlink send error")

    # ------------------------------------------------------------------
    # 入队 API（session / dispatcher 调用）
    # ------------------------------------------------------------------

    async def enqueue_json(self, data: dict[str, Any]) -> None:
        """入队 JSON 控制消息（AL-P2-006）。

        控制事件量小（状态/错误/边界），512 深度几乎不会满；
        真满说明客户端已不消费——短等待（2s）后丢弃并告警，
        避免慢客户端反压整个 Orchestrator 事件出口（含 recorder/TTS 链路）。
        """
        try:
            self._control_queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                await asyncio.wait_for(self._control_queue.put(data), timeout=2.0)
            except TimeoutError:
                logger.warning(
                    "control queue full for 2s——dropping JSON message %s",
                    data.get("type"),
                )

    async def send_error(self, message: str) -> None:
        await self.enqueue_json({"type": "error", "payload": {"message": message}})
