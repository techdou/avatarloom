"""avatar 状态推导纯函数（对齐 VoxEMW orchestrator.avatar_state_transition）。

从事件流推导数字人的门控状态：
- speech_active: 助手说话期间 True，禁 idle 生成（防句间停顿插 idle 帧卡画面）
- idle_mode: listening（用户在说）/ thinking（用户说完等回复）/ calm（默认待机）

纯函数、无 IO，便于单测。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AvatarState:
    """数字人门控状态的不可变快照。"""

    speech_active: bool = False
    idle_mode: str = "calm"  # listening | thinking | calm
    # 内部：是否已看到当前回复的首个音频块（用于推导 speech_active on）
    _seen_first_audio: bool = field(default=False, repr=False)


def transition_avatar_state(
    state: AvatarState,
    event_type: str,
    *,
    has_audio: bool = False,
    is_interrupt: bool = False,
) -> AvatarState:
    """按事件类型推导新的 AvatarState。

    事件类型取值（与 avatarloom_protocol 对齐）：
    - "tts.audio.delta": 首个音频块 → speech_active=on
    - "tts.audio.completed": 回复完成 → speech_active=off, idle_mode=calm
    - "speech.detected": 用户开口 → speech_active=off, idle_mode=listening
    - "speech.ended": 用户说完 → idle_mode=thinking（若助手没在说）
    - "interrupt": 打断 → speech_active=off, idle_mode=calm
    """
    if event_type == "tts.audio.delta" and has_audio:
        # 首个音频块：开始说话（不重复置位）
        if not state._seen_first_audio:
            return AvatarState(
                speech_active=True,
                idle_mode="calm",
                _seen_first_audio=True,
            )
        return state
    if event_type == "tts.audio.completed":
        # 回复完成：停止说话，回到 calm
        return AvatarState(speech_active=False, idle_mode="calm")
    if event_type == "speech.detected":
        # 用户开口：停止说话，进入聆听态
        return AvatarState(speech_active=False, idle_mode="listening")
    if event_type == "speech.ended":
        # 用户说完：若助手没在说，进入思考态
        return AvatarState(
            speech_active=False,
            idle_mode="thinking" if not state.speech_active else state.idle_mode,
        )
    if event_type == "interrupt":
        return AvatarState(speech_active=False, idle_mode="calm")
    return state
