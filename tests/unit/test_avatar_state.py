"""avatar_state 纯函数单测。"""

from __future__ import annotations

from runtime.orchestrator.avatar_state import AvatarState, transition_avatar_state


class TestAvatarStateTransition:
    def test_first_audio_delta_turns_speech_on(self) -> None:
        s = AvatarState()
        s2 = transition_avatar_state(s, "tts.audio.delta", has_audio=True)
        assert s2.speech_active is True
        assert s2.idle_mode == "calm"

    def test_audio_delta_after_first_keeps_speech_on(self) -> None:
        s = AvatarState(speech_active=True, _seen_first_audio=True)
        s2 = transition_avatar_state(s, "tts.audio.delta", has_audio=True)
        assert s2.speech_active is True
        # 状态不重复置位
        assert s2 is s

    def test_completed_turns_speech_off(self) -> None:
        s = AvatarState(speech_active=True, _seen_first_audio=True)
        s2 = transition_avatar_state(s, "tts.audio.completed")
        assert s2.speech_active is False
        assert s2.idle_mode == "calm"

    def test_speech_detected_enters_listening(self) -> None:
        s = AvatarState(speech_active=True)
        s2 = transition_avatar_state(s, "speech.detected")
        assert s2.speech_active is False
        assert s2.idle_mode == "listening"

    def test_speech_ended_enters_thinking_when_idle(self) -> None:
        s = AvatarState(speech_active=False)
        s2 = transition_avatar_state(s, "speech.ended")
        assert s2.idle_mode == "thinking"

    def test_speech_ended_keeps_mode_when_speaking(self) -> None:
        s = AvatarState(speech_active=True, idle_mode="calm")
        s2 = transition_avatar_state(s, "speech.ended")
        assert s2.idle_mode == "calm"

    def test_speech_ended_no_mix_when_interruption_disabled(self) -> None:
        """allow_interruption=False 时，助手说话期间收到 speech.ended 不应改状态（防混帧）。"""
        s = AvatarState(speech_active=True, idle_mode="calm")
        s2 = transition_avatar_state(s, "speech.ended", allow_interruption=False)
        assert s2.speech_active is True  # 不打断 → 保持说话状态
        assert s2 is s

    def test_unknown_event_is_noop(self) -> None:
        s = AvatarState(speech_active=True)
        s2 = transition_avatar_state(s, "llm.text.delta")
        assert s2 is s

    def test_full_conversation_flow(self) -> None:
        """完整对话流：用户说 → 助手说 → 助手说完 → 用户再说。"""
        s = AvatarState()
        # 用户开口
        s = transition_avatar_state(s, "speech.detected")
        assert (s.speech_active, s.idle_mode) == (False, "listening")
        # 用户说完，助手待命
        s = transition_avatar_state(s, "speech.ended")
        assert (s.speech_active, s.idle_mode) == (False, "thinking")
        # 助手开始说话（首音频块）
        s = transition_avatar_state(s, "tts.audio.delta", has_audio=True)
        assert (s.speech_active, s.idle_mode) == (True, "calm")
        # 助手说完
        s = transition_avatar_state(s, "tts.audio.completed")
        assert (s.speech_active, s.idle_mode) == (False, "calm")
