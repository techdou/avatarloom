"""Mock STT Block。

收到 speech.ended 后 emit transcript.completed。

策略：
- 累积 speech 期间收到的音频（这里简化：从 speech.detected 到 speech.ended 收集"已识别文本"）
- v0.1 Mock 不真做 ASR——从配置的回复模板池里选一句作为"识别结果"
- 这样 Mock 链路能演示 STT→LLM 完整数据流

如果配置 `mode: echo`，把最近一段用户输入文本原样回（用于纯文本测试模式）。
"""

from __future__ import annotations

import random

from avatarloom_protocol import (
    AUDIO_APPENDED,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability

_DEFAULT_UTTERANCES = [
    "你好，请介绍一下你自己。",
    "今天天气怎么样？",
    "帮我解释一下什么是数字人。",
    "你能做什么？",
]


class MockSttBlock(Block):
    """Mock 语音识别。"""

    _utterances: list[str] = _DEFAULT_UTTERANCES
    _mode: str = "random"  # random | fixed
    _fixed_text: str = "你好"

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="stt.mock",
            name="Mock STT",
            category="stt",
            runtime_type="mock",
            capabilities=Capability(streaming=False, languages=["zh", "en"]),
            inputs=[AUDIO_APPENDED, SPEECH_DETECTED, SPEECH_ENDED],
            outputs=[TRANSCRIPT_COMPLETED],
            config_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["random", "fixed"],
                        "default": "random",
                    },
                    "utterances": {"type": "array", "items": {"type": "string"}},
                    "fixed_text": {"type": "string"},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._mode = str(cfg.get("mode", "random"))
        if custom := cfg.get("utterances"):
            self._utterances = list(custom)
        self._fixed_text = str(cfg.get("fixed_text", "你好"))
        self._mark_ready()
        await ctx.logger.ainfo("stt.mock ready", mode=self._mode)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        # 在 speech.detected 时记录开始；speech.ended 时输出"识别结果"
        if event.type == SPEECH_DETECTED:
            # 记录潜在用户输入的"开头"——Mock 不真识别，这里仅记状态
            return
        if event.type == SPEECH_ENDED:
            text = self._pick_text()
            await ctx.emit(
                Event(
                    type=TRANSCRIPT_COMPLETED,
                    session_id=ctx.session_id,
                    source="stt.mock",
                    run_id=ctx.run_id,
                    payload={
                        "text": text,
                        "language": "zh",
                        "confidence": 0.95,
                    },
                )
            )

    def _pick_text(self) -> str:
        if self._mode == "fixed":
            return self._fixed_text
        return random.choice(self._utterances)

    async def reset(self, session_id: str) -> None:
        self._last_user_input = ""
