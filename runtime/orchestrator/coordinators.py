"""Orchestrator 的协调器子模块——把 Vision/Filler/Memory 三组职责从 God Class 拆出。

设计：
- 每个 coordinator 持有 orchestrator 引用（_orch），通过它访问 blocks/config/sessions/emit。
- 状态字典在 coordinator 内部创建；Orchestrator 通过 @property 转发，保持外部访问透明。
- coordinator 只暴露 Orchestrator 内部调用所需的方法，不构成公共 API。

为何不用纯函数：这三组都有跨调用的可变状态（pending future、task 句柄、缓存 dict），
封装成类比裸函数 + 闭包更清晰，也比把状态全挂 Orchestrator 上更好测试。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avatarloom_protocol import (
    TTS_AUDIO_DELTA,
    VISION_REQUEST,
    Event,
)
from avatarloom_sdk import BlockContext

from runtime.orchestrator._helpers import (
    _VISION_CONTEXT_TTL_S,
    _VISION_MIN_INTERVAL_S,
    CATEGORY_VISION,
    _read_wav_16k_mono_s16,
)

if TYPE_CHECKING:
    from runtime.orchestrator.orchestrator import Orchestrator
    from runtime.session import Session

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# VisionCoordinator
# ----------------------------------------------------------------------


class VisionCoordinator:
    """封装视觉感知的所有状态和方法。

    职责：
    - 接收浏览器截帧，调 vision block 多模态分析
    - 管理同轮等待（触发词命中后挂起 LLM，等截帧结果）
    - 并发锁 + 节流（AL-P1-011：同 session 同时仅 1 个多模态调用，手动帧限频）
    - 视觉上下文的 TTL + 单次消费
    """

    def __init__(self, orch: Orchestrator) -> None:
        self._orch = orch
        # 同轮 Vision 等待：session_id -> (request_id, Future)。
        # 触发词命中后挂起，ingest_vision_frame/超时/打断时 resolve。
        self._pending: dict[str, tuple[str, asyncio.Future[None]]] = {}
        # Vision 调用并发锁与节流（AL-P1-011）
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}
        # 视觉感知上下文：session_id -> {"description", "request_id", "ts"}，
        # 单次消费 + TTL，供 LLM 下一轮回复注入
        self._contexts: dict[str, dict[str, Any]] = {}

    async def ingest_frame(self, session: Session, jpeg_b64: str) -> None:
        """接收浏览器摄像头截帧（0x02 上行），调用 vision block 多模态分析。

        结果存到 _contexts（单次消费 + TTL，供 LLM 注入）；若本轮有挂起的
        同轮 Vision 等待（触发词命中），resolve 它让 LLM 立即继续。
        vision block 缺席时静默跳过（不阻断主链路）。
        """
        vision = self._orch.blocks.get(CATEGORY_VISION)
        if vision is None:
            logger.info("vision block 未装配，跳过摄像头帧分析")
            self.resolve_pending(session.session_id)
            return
        pending = self._pending.get(session.session_id)
        # AL-P1-011 并发锁：同 session 已有 vision 调用进行中 → 丢弃重复帧
        lock = self._locks.setdefault(session.session_id, asyncio.Lock())
        if lock.locked():
            logger.info(
                "vision 调用进行中，丢弃重复帧 (session %s)",
                session.session_id[:12],
            )
            return
        # AL-P1-011 节流：无同轮等待的手动帧受最小间隔限制（费用控制）。
        # 有 pending（触发词同轮）的帧必须服务——它是本轮回答的前提。
        if pending is None:
            last = self._last_call.get(session.session_id, 0.0)
            gap = time.monotonic() - last
            if gap < _VISION_MIN_INTERVAL_S:
                logger.info(
                    "vision 帧节流丢弃（距上次 %.1fs < %.1fs, session %s）",
                    gap,
                    _VISION_MIN_INTERVAL_S,
                    session.session_id[:12],
                )
                return
        self._last_call[session.session_id] = time.monotonic()
        request_id = pending[0] if pending else None
        ctx = BlockContext(
            session_id=session.session_id,
            run_id=session.current_run_id,
            workspace_root=".",
            config=self._orch._block_configs.get(CATEGORY_VISION, {}),
            _emit_fn=self._orch._on_event,
        )
        async with lock:
            try:
                describe_frame = getattr(vision, "describe_frame", None)
                if not callable(describe_frame):
                    raise AttributeError("vision block does not implement describe_frame")
                # 外层超时——block 内部 httpx 超时是传输层兜底，但若 block 实现
                # 忘了设超时，锁会被永久持有，该 session 后续所有帧被静默丢弃
                result = await asyncio.wait_for(
                    describe_frame(
                        ctx,
                        jpeg_b64,
                        prompt=(
                            "描述这张图片里的内容，包括人物外貌特征、穿着、表情、"
                            "以及周围环境。用中文，2-3 句话。"
                        ),
                        request_id=request_id,
                    ),
                    timeout=self._orch.config.vision_timeout_s,
                )
                description = result.payload.get("description", "")
                if description and "视觉感知失败" not in description:
                    self._contexts[session.session_id] = {
                        "description": description,
                        "request_id": request_id,
                        "ts": time.monotonic(),
                    }
                    logger.info(
                        "vision 分析完成 (session %s, req %s): %.60s",
                        session.session_id[:12],
                        (request_id or "-")[:12],
                        description,
                    )
            except Exception as e:
                logger.warning("vision describe_frame 失败: %s", e)
            finally:
                # 成功/失败都唤醒同轮等待——失败走降级回答，不让 LLM 干等超时
                self.resolve_pending(session.session_id)

    async def handle_frame_error(self, session: Session, reason: str) -> None:
        """浏览器截帧失败（摄像头拒绝/不可用）——立即降级，不等超时。"""
        logger.info(
            "vision 截帧失败 (session %s): %s——降级为无视觉回答",
            session.session_id[:12],
            reason,
        )
        self.resolve_pending(session.session_id)

    def resolve_pending(self, session_id: str) -> None:
        """唤醒 session 上挂起的同轮 Vision 等待（若有）。"""
        pending = self._pending.pop(session_id, None)
        if pending is not None and not pending[1].done():
            pending[1].set_result(None)

    def cancel_pending(self, session_id: str) -> None:
        """取消挂起的同轮 Vision 等待（打断/会话结束用）。

        与 resolve_pending 的区别：resolve 是 set_result（正常唤醒），
        cancel 是 future.cancel()（等待方收到 CancelledError，跳过本轮 LLM）。
        """
        pending = self._pending.pop(session_id, None)
        if pending is not None and not pending[1].done():
            pending[1].cancel()

    async def request_and_wait(self, session: Session, keyword: str) -> bool:
        """下行 vision.request 并挂起等待截帧分析。返回 True=继续 LLM。

        唤醒路径：ingest_frame（成功/失败）/ handle_frame_error /
        超时降级。打断或会话结束 → Future 被 cancel → 返回 False 跳过 LLM。
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        request_id = f"vreq_{uuid.uuid4().hex[:12]}"
        # 同 session 已有 pending（连说两次触发词）→ 取消旧的，以新请求为准
        old = self._pending.pop(session.session_id, None)
        if old is not None and not old[1].done():
            old[1].cancel()
        self._pending[session.session_id] = (request_id, fut)

        await self._orch._on_event(
            Event(
                type=VISION_REQUEST,
                session_id=session.session_id,
                source="orchestrator.trigger",
                run_id=session.current_run_id,
                payload={"keyword": keyword, "request_id": request_id},
            )
        )

        timeout = float(self._orch.config.vision_timeout_s)
        try:
            # shield：超时只放弃等待，不取消 fut——迟到的截帧仍可存上下文
            await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            return True
        except TimeoutError:
            self._pending.pop(session.session_id, None)
            logger.info(
                "vision 等待超时（%.1fs, session %s）——降级为无视觉回答",
                timeout,
                session.session_id[:12],
            )
            return True
        except asyncio.CancelledError:
            # 区分两种取消（Python 语义：吞掉 task.cancel() 又不 re-raise，
            # 任务会继续跑——asyncio.run/shutdown 的 gather 会因此永远等它）：
            # - fut 被 _do_interrupt/end_session 取消（任务本身未被 cancel）
            #   → 内部打断，跳过本轮 LLM，返回 False
            # - 消费者任务自身被 cancel（bus 关闭/loop teardown）
            #   → 必须 re-raise 让任务正常消亡
            task = asyncio.current_task()
            if fut.cancelled() and (task is None or task.cancelling() == 0):
                self._pending.pop(session.session_id, None)
                logger.info(
                    "vision 等待被打断（session %s），跳过本轮 LLM",
                    session.session_id[:12],
                )
                return False
            raise

    def consume_context(self, session_id: str) -> str | None:
        """取出 session 的视觉描述（单次消费 + TTL 过期清理）。"""
        entry = self._contexts.pop(session_id, None)
        if entry is None:
            return None
        age = time.monotonic() - float(entry.get("ts", 0.0))
        if age > _VISION_CONTEXT_TTL_S:
            logger.info("vision context 已过期（%.1fs），丢弃", age)
            return None
        return str(entry.get("description") or "") or None

    def cleanup_session(self, session_id: str) -> None:
        """清理 session 级状态（shutdown/end_session 调用）。"""
        self.cancel_pending(session_id)
        self._contexts.pop(session_id, None)
        self._locks.pop(session_id, None)
        self._last_call.pop(session_id, None)


# ----------------------------------------------------------------------
# FillerPlayer
# ----------------------------------------------------------------------


class FillerPlayer:
    """封装 filler 垫音的所有状态和方法（VoxEMW 移植）。

    转写完成即播 persona 预渲染口头禅，盖 LLM 首句空白；
    伪造为普通 tts.audio.delta 事件——前端播放、Avatar 张嘴、AVMux 同步全部复用。
    与上游一致：单发不循环；真 TTS 抢先即停余量；打断即取消。
    """

    def __init__(self, orch: Orchestrator) -> None:
        self._orch = orch
        # Filler 垫音：persona_id -> [(pcm_bytes, label)]；session_id -> 播放 task
        self._cache: dict[str, list[tuple[bytes, str]]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._last_idx: dict[str, int] = {}

    async def start(self, session: Session) -> None:
        """转写完成后启动垫音（盖 LLM 首句空白，含 Vision 等待期）。"""
        if not self._orch.config.filler_enabled:
            return
        clips = self._load_clips(session)
        if not clips:
            return
        # 防御：同 session 旧垫音先取消
        self.cancel(session.session_id)
        # 随机选一条，避免与上次重复（VoxEMW 同款策略）
        persona_key = session.persona_id or ""
        last = self._last_idx.get(persona_key, -1)
        idx = random.randrange(len(clips))
        if len(clips) > 1 and idx == last:
            idx = (idx + 1) % len(clips)
        self._last_idx[persona_key] = idx
        pcm, _label = clips[idx]
        self._tasks[session.session_id] = asyncio.create_task(
            self._play(session, pcm)
        )

    async def _play(self, session: Session, pcm: bytes) -> None:
        """按实时节奏分块 emit 垫音（0.4s/块），伪 TTS 通道。

        M2：除 CancelledError 外捕获所有异常——否则 task 静默死亡，
        _tasks 残留（pop 在 finally 里，但异常若不进 finally 会泄漏）。
        """
        try:
            chunk_bytes = 6400 * 2  # 0.4s @16k int16
            for offset in range(0, len(pcm), chunk_bytes):
                chunk = pcm[offset : offset + chunk_bytes]
                if not chunk:
                    break
                await self._orch._on_event(
                    Event(
                        type=TTS_AUDIO_DELTA,
                        session_id=session.session_id,
                        source="orchestrator.filler",
                        run_id=session.current_run_id,
                        payload={
                            "pcm_b64": base64.b64encode(chunk).decode("ascii"),
                            "sample_rate": 16000,
                            "samples": len(chunk) // 2,
                            "text": "",
                            "filler": True,
                        },
                    )
                )
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            raise
        except Exception:
            # M2：非取消异常（如 base64/网络 sink 报错）不能让 task 静默死亡——
            # 记日志，task 正常结束（finally 会清 _tasks）
            logger.exception("filler play error (session %s)", session.session_id[:12])
        finally:
            self._tasks.pop(session.session_id, None)

    def cancel(self, session_id: str) -> None:
        """取消垫音（打断 / 真 TTS 抢先 / 会话结束）。"""
        task = self._tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def on_tts_delta_preempt(self, event: Event) -> None:
        """真 TTS 首块到达 → 停发垫音余量（VoxEMW：真音频抢先，尾帧不错切 idle）。"""
        if event.payload.get("filler"):
            return
        self.cancel(event.session_id)

    def cleanup_session(self, session_id: str) -> None:
        """清理 session 级状态（shutdown/end_session 调用）。"""
        self.cancel(session_id)

    def _load_clips(self, session: Session) -> list[tuple[bytes, str]]:
        """加载 persona 垫音（16k mono s16 校验，按 persona 缓存）。"""
        persona_id = session.persona_id or ""
        if persona_id in self._cache:
            return self._cache[persona_id]
        clips: list[tuple[bytes, str]] = []
        try:
            root = (
                Path(getattr(session, "workspace_root", ".") or ".")
                / "personas"
                / persona_id
                / "fillers"
            )
            for wav_path in sorted(root.rglob("*.wav")):
                pcm = _read_wav_16k_mono_s16(wav_path)
                if pcm is not None:
                    clips.append((pcm, wav_path.stem))
            if clips:
                logger.info("filler 加载 %d 条 (persona %s)", len(clips), persona_id)
        except Exception as e:
            logger.info("filler 无可用垫音 (persona %s): %s", persona_id, e)
        self._cache[persona_id] = clips
        return clips


# ----------------------------------------------------------------------
# MemoryBridge
# ----------------------------------------------------------------------


class MemoryBridge:
    """封装 memory 记忆相关的状态和方法（Mem0 移植）。

    职责：
    - 凑对写入：transcript 时存本轮用户文本，llm.done 时与 assistant 文本凑对写入
    - 召回：start_session 时召回 persona 的记忆块追加到 instructions
    - 打断的回复不写入（finish_reason=interrupted）
    """

    def __init__(self, orch: Orchestrator) -> None:
        self._orch = orch
        # session_id -> 本轮用户文本（llm.done 时凑对写入）
        self._pending_users: dict[str, str] = {}

    def store_user_text(self, session_id: str, text: str) -> None:
        """记录本轮用户文本（transcript 完成时存，llm.done 时凑对）。"""
        self._pending_users[session_id] = text

    async def on_llm_done(self, event: Event) -> None:
        """记忆写入：一轮 user/assistant 凑对，response.done 后异步抽取。

        打断的回复（finish_reason=interrupted）不完整，写入会污染记忆——跳过。
        memory.memorize 内部已用 asyncio.to_thread 包装 Mem0 的同步阻塞调用，
        不占语音延迟；block 未启用时内部 no-op。
        """
        if event.payload.get("finish_reason") == "interrupted":
            self._pending_users.pop(event.session_id, None)
            return
        user_text = self._pending_users.pop(event.session_id, "")
        assistant_text = str(event.payload.get("full_text") or "")
        if not user_text and not assistant_text:
            return
        session = self._orch.sessions.get(event.session_id)
        agent_id = (session.persona_id if session else None) or "default"
        await self.memorize_turn(user_text, assistant_text, agent_id)

    async def recall(self, session: Session) -> str:
        """召回该 persona 的记忆块（未启用/无 block 返回 ""）。"""
        memory = self._orch.blocks.get("memory")
        if memory is None or not getattr(memory, "active", False):
            return ""
        try:
            return await memory.recall(session.persona_id or "default")  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("memory recall 异常（按无记忆继续）: %s", e)
            return ""

    async def memorize_turn(
        self, user_text: str, assistant_text: str, agent_id: str
    ) -> None:
        """写入一轮对话（未启用/无 block no-op）。"""
        memory = self._orch.blocks.get("memory")
        if memory is None or not getattr(memory, "active", False):
            return
        try:
            await memory.memorize(user_text, assistant_text, agent_id)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("memory memorize 异常（静默跳过）: %s", e)

    def cleanup_session(self, session_id: str) -> None:
        """清理 session 级状态（shutdown/end_session 调用）。"""
        self._pending_users.pop(session_id, None)
