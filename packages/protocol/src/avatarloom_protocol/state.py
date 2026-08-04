"""显式会话状态机。

状态定义见 docs/02-事件协议状态机与音画同步.md：

    IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING → IDLE
                       ↑                ↓           ↓
                     INTERRUPTING ←───────────────── 用户打断
                                                           ↓
                                                         ERROR / CLOSED

设计原则：
- 纯函数 + 表驱动，便于单测覆盖所有合法 / 非法转换。
- 非法转换 raise IllegalTransitionError，禁止用散落布尔变量模拟状态。
- INTERRUPTING 是瞬态：进入后必须自动转向 LISTENING（清空 TTS/Avatar 后）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    """会话状态。StrEnum 让 JSON 序列化直接是字符串，也保持 == 'str' 比较。"""

    IDLE = "idle"  # 空闲，等待用户开口
    LISTENING = "listening"  # 正在收音（VAD 已检测到语音活动）
    TRANSCRIBING = "transcribing"  # STT 正在识别
    THINKING = "thinking"  # LLM 正在推理
    SPEAKING = "speaking"  # TTS 正在播放 / 数字人正在说话
    INTERRUPTING = "interrupting"  # 瞬态：正在取消 LLM/TTS，准备转回 LISTENING
    ERROR = "error"  # 错误态，可恢复回 IDLE
    CLOSED = "closed"  # 会话已关闭，终态

    @classmethod
    def parse(cls, value: str) -> State:
        """字符串 -> State；非法值 raise ValueError。"""
        try:
            return cls(value)
        except ValueError as e:
            raise ValueError(f"Unknown state: {value!r}") from e


# ---------------------------------------------------------------------------
# 合法转换表。
# key = (from_state, trigger) -> to_state
# trigger 是触发转换的事件类别字符串（不是 EventType 枚举，保持状态机与事件协议解耦）。
# ---------------------------------------------------------------------------

# fmt: off
_TRANSITIONS: dict[tuple[State, str], State] = {
    # ---- 从 IDLE ----
    (State.IDLE,        "speech_started"):      State.LISTENING,
    (State.IDLE,        "session_closed"):      State.CLOSED,
    (State.IDLE,        "error"):               State.ERROR,

    # ---- 从 LISTENING ----
    (State.LISTENING,   "speech_ended"):        State.TRANSCRIBING,
    (State.LISTENING,   "speech_started"):      State.LISTENING,      # 继续说话，保持
    (State.LISTENING,   "cancel"):              State.IDLE,
    (State.LISTENING,   "session_closed"):      State.CLOSED,
    (State.LISTENING,   "error"):               State.ERROR,

    # ---- 从 TRANSCRIBING ----
    (State.TRANSCRIBING, "transcript_ready"):   State.THINKING,
    (State.TRANSCRIBING, "transcript_empty"):   State.IDLE,           # 没识别出内容，回 Idle
    (State.TRANSCRIBING, "cancel"):             State.IDLE,
    (State.TRANSCRIBING, "session_closed"):     State.CLOSED,
    (State.TRANSCRIBING, "error"):              State.ERROR,

    # ---- 从 THINKING ----
    (State.THINKING,    "llm_first_token"):     State.SPEAKING,
    (State.THINKING,    "llm_empty"):           State.IDLE,           # LLM 没产出
    (State.THINKING,    "speech_started"):      State.INTERRUPTING,    # 用户抢话打断思考
    (State.THINKING,    "cancel"):              State.IDLE,
    (State.THINKING,    "session_closed"):      State.CLOSED,
    (State.THINKING,    "error"):               State.ERROR,

    # ---- 从 SPEAKING ----
    (State.SPEAKING,    "response_done"):       State.IDLE,
    (State.SPEAKING,    "speech_started"):      State.INTERRUPTING,    # 用户打断说话
    (State.SPEAKING,    "cancel"):              State.IDLE,
    (State.SPEAKING,    "session_closed"):      State.CLOSED,
    (State.SPEAKING,    "error"):               State.ERROR,

    # ---- 从 INTERRUPTING（瞬态）----
    # 取消完成后自动转回 LISTENING（用户正在说话）或 IDLE（用户已停）
    (State.INTERRUPTING, "interrupt_done_speaking"):    State.LISTENING,
    (State.INTERRUPTING, "interrupt_done_silent"):      State.IDLE,
    (State.INTERRUPTING, "session_closed"):             State.CLOSED,
    (State.INTERRUPTING, "error"):                      State.ERROR,

    # ---- 从 ERROR ----
    (State.ERROR,       "recover"):             State.IDLE,
    (State.ERROR,       "session_closed"):      State.CLOSED,

    # ---- CLOSED 是终态 ----
}
# fmt: on


@dataclass(frozen=True)
class TransitionResult:
    """转换结果。"""

    from_state: State
    to_state: State
    trigger: str


class IllegalTransitionError(ValueError):
    """非法状态转换。包含 from、trigger 信息便于调试。"""

    def __init__(self, from_state: State, trigger: str) -> None:
        self.from_state = from_state
        self.trigger = trigger
        super().__init__(
            f"Illegal state transition: {from_state.value} + {trigger!r}. "
            f"Legal triggers from {from_state.value}: "
            f"{sorted({t for (s, t) in _TRANSITIONS if s == from_state})}"
        )


def can_transition(from_state: State, trigger: str) -> bool:
    """查询某转换是否合法。不抛异常。"""
    return (from_state, trigger) in _TRANSITIONS


def transition(from_state: State, trigger: str) -> TransitionResult:
    """执行状态转换。

    Args:
        from_state: 当前状态。
        trigger: 触发事件类别字符串（如 "speech_started"）。

    Returns:
        TransitionResult。

    Raises:
        IllegalTransitionError: 当 (state, trigger) 不在合法表里。
    """
    key = (from_state, trigger)
    if key not in _TRANSITIONS:
        raise IllegalTransitionError(from_state, trigger)
    to_state = _TRANSITIONS[key]
    return TransitionResult(from_state=from_state, to_state=to_state, trigger=trigger)


def legal_triggers(from_state: State) -> list[str]:
    """列出从某状态的所有合法触发器，用于文档和调试。"""
    return sorted({t for (s, t) in _TRANSITIONS if s == from_state})
