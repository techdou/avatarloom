"""状态机全边覆盖测试。

验证 docs/02 定义的所有合法转换 + 所有非法转换被拒。
"""

from __future__ import annotations

import pytest
from avatarloom_protocol import (
    IllegalTransitionError,
    State,
    can_transition,
    legal_triggers,
    transition,
)

# ---------------------------------------------------------------------------
# 主链路
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_full_conversation_cycle(self) -> None:
        """一次完整对话：IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING → IDLE。"""
        s = State.IDLE
        s = transition(s, "speech_started").to_state
        assert s == State.LISTENING

        s = transition(s, "speech_ended").to_state
        assert s == State.TRANSCRIBING

        s = transition(s, "transcript_ready").to_state
        assert s == State.THINKING

        s = transition(s, "llm_first_token").to_state
        assert s == State.SPEAKING

        s = transition(s, "response_done").to_state
        assert s == State.IDLE

    def test_empty_transcript_returns_to_idle(self) -> None:
        """VAD 误判（说完但没识别出内容）：回 IDLE 不前进。"""
        s = transition(State.IDLE, "speech_started").to_state
        s = transition(s, "speech_ended").to_state
        assert s == State.TRANSCRIBING
        s = transition(s, "transcript_empty").to_state
        assert s == State.IDLE

    def test_llm_empty_returns_to_idle(self) -> None:
        s = transition(State.IDLE, "speech_started").to_state
        s = transition(s, "speech_ended").to_state
        s = transition(s, "transcript_ready").to_state
        s = transition(s, "llm_empty").to_state
        assert s == State.IDLE


# ---------------------------------------------------------------------------
# 打断（INTERRUPTING 瞬态）
# ---------------------------------------------------------------------------


class TestInterruption:
    def test_interrupt_while_speaking_goes_through_interrupting(self) -> None:
        """说话时被打断 → INTERRUPTING → LISTENING。"""
        s = State.SPEAKING
        s = transition(s, "speech_started").to_state
        assert s == State.INTERRUPTING
        # 清理完成后，用户还在说话 → LISTENING
        s = transition(s, "interrupt_done_speaking").to_state
        assert s == State.LISTENING

    def test_interrupt_while_thinking(self) -> None:
        s = transition(State.THINKING, "speech_started").to_state
        assert s == State.INTERRUPTING
        s = transition(s, "interrupt_done_silent").to_state
        assert s == State.IDLE

    def test_interrupt_silent_user_returns_to_idle(self) -> None:
        """打断完成后用户已停 → IDLE。"""
        s = transition(State.SPEAKING, "speech_started").to_state
        s = transition(s, "interrupt_done_silent").to_state
        assert s == State.IDLE


# ---------------------------------------------------------------------------
# 错误与恢复
# ---------------------------------------------------------------------------


class TestErrorRecovery:
    @pytest.mark.parametrize("state", list(State))
    def test_any_state_can_error(self, state: State) -> None:
        """所有非终态都应该能进入 ERROR。CLOSED 除外（终态）。"""
        if state == State.CLOSED:
            pytest.skip("CLOSED 是终态")
        if state == State.ERROR:
            pytest.skip("ERROR 自身")
        result = transition(state, "error")
        assert result.to_state == State.ERROR

    def test_error_recovers_to_idle(self) -> None:
        assert transition(State.ERROR, "recover").to_state == State.IDLE

    def test_closed_is_terminal(self) -> None:
        """CLOSED 不能转出。"""
        assert legal_triggers(State.CLOSED) == []


# ---------------------------------------------------------------------------
# 会话关闭
# ---------------------------------------------------------------------------


class TestSessionClose:
    @pytest.mark.parametrize(
        "state",
        [
            State.IDLE,
            State.LISTENING,
            State.TRANSCRIBING,
            State.THINKING,
            State.SPEAKING,
            State.INTERRUPTING,
            State.ERROR,
        ],
    )
    def test_any_state_can_close(self, state: State) -> None:
        result = transition(state, "session_closed")
        assert result.to_state == State.CLOSED


# ---------------------------------------------------------------------------
# 非法转换
# ---------------------------------------------------------------------------


class TestIllegalTransitions:
    def test_illegal_transition_raises(self) -> None:
        with pytest.raises(IllegalTransitionError) as exc_info:
            transition(State.IDLE, "response_done")
        assert exc_info.value.from_state == State.IDLE
        assert "response_done" in str(exc_info.value)

    def test_illegal_transition_message_lists_legal_triggers(self) -> None:
        """错误信息要告诉开发者合法 trigger 有哪些（调试友好）。"""
        with pytest.raises(IllegalTransitionError) as exc_info:
            transition(State.THINKING, "totally_unknown")
        msg = str(exc_info.value)
        assert "llm_first_token" in msg
        assert "speech_started" in msg

    def test_can_transition_returns_false_without_raising(self) -> None:
        assert can_transition(State.IDLE, "bogus") is False
        assert can_transition(State.IDLE, "speech_started") is True

    def test_closed_cannot_transition_out(self) -> None:
        """CLOSED 是终态，任何 trigger 都不合法。"""
        for trigger in ["speech_started", "error", "recover", "session_closed"]:
            assert can_transition(State.CLOSED, trigger) is False


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------


class TestStateEnum:
    def test_parse_roundtrip(self) -> None:
        for s in State:
            assert State.parse(s.value) == s

    def test_parse_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown state"):
            State.parse("bogus")

    def test_state_is_string_serializable(self) -> None:
        """State 继承 str，可直接 JSON 序列化。"""
        import json

        assert json.dumps(State.SPEAKING.value) == '"speaking"'
        assert State.SPEAKING == "speaking"  # str 比较


# ---------------------------------------------------------------------------
# transition result
# ---------------------------------------------------------------------------


class TestTransitionResult:
    def test_result_records_all_fields(self) -> None:
        r = transition(State.IDLE, "speech_started")
        assert r.from_state == State.IDLE
        assert r.to_state == State.LISTENING
        assert r.trigger == "speech_started"

    def test_result_is_hashable(self) -> None:
        """TransitionResult 是 frozen dataclass，应可哈希。"""
        r = transition(State.IDLE, "speech_started")
        assert hash(r) == hash(r)
        # 不同结果不同哈希
        r2 = transition(State.SPEAKING, "response_done")
        assert hash(r) != hash(r2)
