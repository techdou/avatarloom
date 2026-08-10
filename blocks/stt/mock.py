"""Mock STT Block。

收到 speech.ended 后 emit transcript.completed。

策略：
- v0.1 Mock 不真做 ASR——从配置的回复模板池里选一句作为"识别结果"
- random 模式轮转选择（避免连续两轮出现同一句），fixed 模式固定返回 fixed_text
- 这样 Mock 链路能演示 STT→LLM 完整数据流
"""

from __future__ import annotations

import random

from avatarloom_protocol import (
    AUDIO_APPENDED,
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

    def __init__(self) -> None:
        super().__init__()
        self._utterances: list[str] = _DEFAULT_UTTERANCES
        self._mode: str = "random"  # random | fixed
        self._fixed_text: str = "你好"
        # session -> 上一次选中的索引（random 轮转去重）
        self._last_pick_idx: dict[str, int] = {}

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="stt.mock",
            name="Mock STT",
            category="stt",
            runtime_type="mock",
            capabilities=Capability(streaming=False, languages=["zh", "en"]),
            inputs=[AUDIO_APPENDED, SPEECH_ENDED],
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
        self._last_pick_idx = {}
        self._mark_ready()
        await ctx.logger.ainfo("stt.mock ready", mode=self._mode)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        # 在 speech.ended 时输出"识别结果"——inputs 只订阅 AUDIO_APPENDED/SPEECH_ENDED
        # （对齐 sensevoice/openai_compatible STT，此前多订阅 SPEECH_DETECTED 但收到后
        # 直接 return，是死分支且让 manifest 误导调用方）
        if event.type == SPEECH_ENDED:
            text = self._pick_text(ctx.session_id)
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

    def _pick_text(self, session_id: str) -> str:
        if self._mode == "fixed":
            return self._fixed_text
        if not self._utterances:
            return ""
        pool = self._utterances
        last = self._last_pick_idx.get(session_id, -1)
        if len(pool) > 1:
            candidates = [i for i in range(len(pool)) if i != last]
            idx = random.choice(candidates)
        else:
            idx = 0
        self._last_pick_idx[session_id] = idx
        return pool[idx]

    async def reset(self, session_id: str) -> None:
        # 打断时清除轮转记忆，下一轮重新从池中选
        self._last_pick_idx.pop(session_id, None)
