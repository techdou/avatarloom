"""Session Manager 测试。"""

from __future__ import annotations

import pytest
from avatarloom_protocol import (
    SESSION_CLOSED,
    SESSION_STARTED,
    SESSION_STATE_CHANGED,
    IllegalTransitionError,
    State,
)

from runtime.session import Session, SessionManager


class TestSession:
    async def test_session_start_emits_event(self) -> None:
        emitted: list = []
        session = Session()

        async def emit(e) -> None:
            emitted.append(e)

        session.set_emit_fn(emit)
        await session.start()
        assert len(emitted) == 1
        assert emitted[0].type == SESSION_STARTED
        assert emitted[0].payload["session_id"] == session.session_id

    async def test_trigger_advances_state(self) -> None:
        session = Session()

        async def emit(e) -> None:
            pass

        session.set_emit_fn(emit)
        assert session.state == State.IDLE
        await session.trigger("speech_started")
        assert session.state == State.LISTENING

    async def test_illegal_trigger_raises(self) -> None:
        session = Session()

        async def emit(e) -> None:
            pass

        session.set_emit_fn(emit)
        with pytest.raises(IllegalTransitionError):
            await session.trigger("response_done")  # IDLE 不能直接到 SPEAKING done

    async def test_state_callback_invoked(self) -> None:
        session = Session()
        callbacks: list[tuple[State, State, str]] = []

        async def cb(old, new, trigger, event) -> None:
            callbacks.append((old, new, trigger))

        async def emit(e) -> None:
            pass

        session.set_emit_fn(emit)
        session.add_state_callback(cb)
        await session.trigger("speech_started")
        assert len(callbacks) == 1
        assert callbacks[0] == (State.IDLE, State.LISTENING, "speech_started")

    async def test_state_changed_event_emitted(self) -> None:
        emitted: list = []
        session = Session()

        async def emit(e) -> None:
            emitted.append(e)

        session.set_emit_fn(emit)
        await session.trigger("speech_started")
        # 第二个事件应是 state_changed
        state_event = emitted[-1]
        assert state_event.type == SESSION_STATE_CHANGED
        assert state_event.payload == {"from": "idle", "to": "listening"}

    async def test_user_speaking_tracked(self) -> None:
        session = Session()

        async def emit(e) -> None:
            pass

        session.set_emit_fn(emit)
        assert session.user_speaking is False
        await session.trigger("speech_started")
        assert session.user_speaking is True
        await session.trigger("speech_ended")
        assert session.user_speaking is False

    async def test_sequence_monotonic(self) -> None:
        session = Session()
        s1 = session.next_sequence()
        s2 = session.next_sequence()
        s3 = session.next_sequence()
        assert s1 < s2 < s3

    async def test_close_emits_session_closed(self) -> None:
        emitted: list = []
        session = Session()

        async def emit(e) -> None:
            emitted.append(e)

        session.set_emit_fn(emit)
        await session.close()
        types = [e.type for e in emitted]
        assert SESSION_CLOSED in types
        assert session.closed

    async def test_close_idempotent(self) -> None:
        session = Session()

        async def emit(e) -> None:
            pass

        session.set_emit_fn(emit)
        await session.close()
        await session.close()  # 不抛错

    async def test_try_trigger_returns_none_on_illegal(self) -> None:
        session = Session()

        async def emit(e) -> None:
            pass

        session.set_emit_fn(emit)
        result = await session.try_trigger("bogus")
        assert result is None

    async def test_trigger_after_closed_raises(self) -> None:
        session = Session()

        async def emit(e) -> None:
            pass

        session.set_emit_fn(emit)
        await session.close()
        with pytest.raises(RuntimeError, match="closed"):
            await session.trigger("speech_started")

    async def test_start_new_run_generates_id(self) -> None:
        session = Session()
        rid = await session.start_new_run()
        assert rid.startswith("run_")
        assert session.current_run_id == rid


class TestSessionManager:
    async def test_create_and_get(self) -> None:
        sm = SessionManager()
        s = sm.create_session(profile_id="test")
        assert sm.get(s.session_id) is s
        assert sm.active_count == 1

    async def test_remove(self) -> None:
        sm = SessionManager()
        s = sm.create_session()
        sm.remove(s.session_id)
        assert sm.get(s.session_id) is None

    async def test_close_all(self) -> None:
        sm = SessionManager()
        s1 = sm.create_session()
        s2 = sm.create_session()

        async def emit(e) -> None:
            pass

        s1.set_emit_fn(emit)
        s2.set_emit_fn(emit)
        await sm.close_all()
        assert s1.closed
        assert s2.closed
        assert sm.active_count == 0
