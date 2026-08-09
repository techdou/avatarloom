"""Session 实现。

一个 Session 对应一次浏览器连接或一次 API 调用。
Session 持有状态机、事件序号、persona 上下文。

设计原则（docs/01 第 7 节）：
- 会话使用显式状态机
- 重要状态全部可观测
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from avatarloom_protocol import (
    RUN_STARTED,
    SESSION_CLOSED,
    SESSION_STARTED,
    Event,
    IllegalTransitionError,
    State,
    make_event,
    make_state_event,
    transition,
)

logger = logging.getLogger(__name__)

# 状态变更回调类型：(from, to, trigger, event) -> None
StateChangeCallback = Callable[[State, State, str, Event], "Awaitable[None]"]


def _new_session_id() -> str:
    return f"ses_{uuid.uuid4().hex[:20]}"


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:20]}"


@dataclass
class Session:
    """单会话状态容器。"""

    session_id: str = field(default_factory=_new_session_id)
    profile_id: str = "mock"
    persona_id: str | None = None
    workspace_root: str = "."
    state: State = State.IDLE
    # 当前 Run（一轮对话的 ID）
    current_run_id: str | None = None
    # 事件序号（单调递增）
    sequence: int = 0
    # 用户是否正在说话（VAD 状态）
    user_speaking: bool = False
    # 会话是否已关闭
    closed: bool = False
    # 锁，保证状态转换原子性
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # 状态变更回调列表
    _state_callbacks: list[StateChangeCallback] = field(default_factory=list, repr=False)
    # 事件发射器（由 Orchestrator 注入）
    _emit: Callable[[Event], Awaitable[None]] | None = field(default=None, repr=False)

    @property
    def is_idle(self) -> bool:
        return self.state == State.IDLE

    @property
    def is_speaking(self) -> bool:
        return self.state == State.SPEAKING

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence

    def set_emit_fn(self, emit: Callable[[Event], Awaitable[None]]) -> None:
        self._emit = emit

    def add_state_callback(self, cb: StateChangeCallback) -> None:
        self._state_callbacks.append(cb)

    async def start(self) -> Event:
        """会话启动。emit session.started。"""
        event = make_event(
            SESSION_STARTED,
            session_id=self.session_id,
            source="session.manager",
            sequence=self.next_sequence(),
            payload={
                "session_id": self.session_id,
                "profile_id": self.profile_id,
                "persona_id": self.persona_id,
                "workspace_root": self.workspace_root,
            },
        )
        await self._emit_event(event)
        return event

    async def trigger(self, trigger: str, payload: dict[str, Any] | None = None) -> State:
        """触发状态转换。

        非法转换 raise IllegalTransitionError（不静默吞）。
        成功转换会：
        1. 更新 self.state
        2. 调用所有状态回调
        3. emit session.state_changed 事件

        Args:
            trigger: 触发器名（见 state_machine._TRANSITIONS）
            payload: 附加在 state_changed 事件的负载

        Returns:
            新状态。
        """
        async with self._lock:
            if self.closed and trigger != "session_closed":
                raise RuntimeError(f"Session {self.session_id} is closed")

            result = transition(self.state, trigger)
            old_state = self.state
            self.state = result.to_state

            # 用户说话状态跟踪（VAD 相关 trigger）
            if trigger == "speech_started":
                self.user_speaking = True
            elif trigger in ("speech_ended", "interrupt_done_silent"):
                self.user_speaking = False

            # 会话关闭
            if result.to_state == State.CLOSED:
                self.closed = True

            # emit 状态变更事件
            state_event = make_state_event(
                self.session_id,
                old_state,
                result.to_state,
                sequence=self.next_sequence(),
                run_id=self.current_run_id,
            )
            if payload:
                state_event.payload.update(payload)

        # emit 和回调移出锁外——持锁期间 publish 遇 BLOCK 满队列会阻塞所有后续
        # trigger（含打断路径）；回调里再调 try_trigger 会死锁（Lock 不可重入）。
        # trade-off：两个协程的 emit 可能乱序，但 state_event.sequence 严格递增，
        # 下游需要严格保序时可按 sequence 排序。
        await self._emit_event(state_event)

        # 调状态回调
        for cb in self._state_callbacks:
            try:
                await cb(old_state, result.to_state, trigger, state_event)
            except Exception:
                logger.exception("state callback error: %s + %s", old_state.value, trigger)

        logger.debug(
            "session %s: %s + %s -> %s",
            self.session_id[:12],
            old_state.value,
            trigger,
            result.to_state.value,
        )
        return self.state

    async def try_trigger(
        self, trigger: str, payload: dict[str, Any] | None = None
    ) -> State | None:
        """尝试触发；非法则返回 None 不抛。用于"可选"转换。"""
        try:
            return await self.trigger(trigger, payload)
        except IllegalTransitionError:
            return None

    async def start_new_run(self) -> str:
        """开始新一轮对话。返回 run_id。

        同时 emit run.started 事件，让 Recorder/Studio UI 在 LLM/TTS 事件
        到达前就能感知到新 Run（避免 delta 事件先到、run 还未注册导致丢录）。
        """
        self.current_run_id = _new_run_id()
        event = make_event(
            RUN_STARTED,
            session_id=self.session_id,
            source="session.manager",
            run_id=self.current_run_id,
            sequence=self.next_sequence(),
            payload={
                "run_id": self.current_run_id,
                "session_id": self.session_id,
                "profile_id": self.profile_id,
                "persona_id": self.persona_id,
            },
        )
        await self._emit_event(event)
        return self.current_run_id

    async def close(self, reason: str = "normal") -> None:
        """关闭会话。"""
        if self.closed:
            return
        await self.try_trigger("session_closed")
        # emit session.closed（即使状态机没经过 CLOSED 也 emit，保证客户端收到）
        event = make_event(
            SESSION_CLOSED,
            session_id=self.session_id,
            source="session.manager",
            sequence=self.next_sequence(),
            payload={"session_id": self.session_id, "reason": reason},
        )
        await self._emit_event(event)

    async def _emit_event(self, event: Event) -> None:
        if self._emit is None:
            logger.debug("emit (no emitter wired): %s", event.type)
            return
        await self._emit(event)


class SessionManager:
    """管理多个 Session。

    v0.1 单进程单用户为主，但保留多 Session 接口。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create_session(
        self,
        *,
        profile_id: str = "mock",
        persona_id: str | None = None,
        workspace_root: str = ".",
    ) -> Session:
        session = Session(
            profile_id=profile_id,
            persona_id=persona_id,
            workspace_root=workspace_root,
        )
        self._sessions[session.session_id] = session
        logger.info("session created: %s (profile=%s)", session.session_id, profile_id)
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if not s.closed)

    async def close_all(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
