"""Mock LLM Block。

收到 transcript.completed 后，按回复模板 emit llm.text.delta 流，
最后 emit llm.text.done。

策略：
- 模板回复（可配置）
- 按"句"切分，逐句 emit delta（is_sentence_end=True 在每句末）
- 模拟流式延迟（可配置 chunk_delay_ms）

这样下游 TTS Block 能演示"逐句喂入"的真实流式合成。
"""

from __future__ import annotations

import asyncio
import re

from avatarloom_protocol import (
    LLM_REQUEST,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TRANSCRIPT_COMPLETED,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability

# 中文/英文句末切分（。！？!?.）
_SENTENCE_END = re.compile(r"[。！？!?\.]")


_DEFAULT_REPLIES = {
    "default": [
        "你好，我是 AvatarLoom 演示助手。",
        "我能实时听懂你说话，并给出回应。",
        "你可以问我任何问题。",
    ],
    "天气": ["今天天气看起来不错，适合出去走走。", "不过我没有真实传感器，这只是 Mock 回复。"],
    "数字人": [
        "数字人是由语音识别、大模型、语音合成和形象驱动组合而成的。",
        "AvatarLoom 把这些能力拆成可替换的积木模块。",
    ],
}


class MockLlmBlock(Block):
    """Mock LLM，按规则模板回复。"""

    _replies: dict[str, list[str]] = _DEFAULT_REPLIES
    _default_reply: list[str] = _DEFAULT_REPLIES["default"]
    _chunk_delay_ms: int = 80
    _first_token_emitted: bool = False

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="llm.mock",
            name="Mock LLM (Template)",
            category="llm",
            runtime_type="mock",
            capabilities=Capability(streaming=True, interruption=True),
            inputs=[LLM_REQUEST, TRANSCRIPT_COMPLETED],
            outputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            config_schema={
                "type": "object",
                "properties": {
                    "chunk_delay_ms": {"type": "integer", "default": 80},
                    "default_reply": {"type": "array", "items": {"type": "string"}},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._chunk_delay_ms = int(cfg.get("chunk_delay_ms", 80))
        if custom_default := cfg.get("default_reply"):
            self._default_reply = list(custom_default)
        self._mark_ready()
        await ctx.logger.ainfo("llm.mock ready", delay_ms=self._chunk_delay_ms)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        # 主链路消费 llm.request；兼容 transcript.completed（单测/直连）
        if event.type not in (LLM_REQUEST, TRANSCRIPT_COMPLETED):
            return

        user_text: str = event.payload.get("text", "")
        sentences = self._pick_reply(user_text)

        full_text = ""
        self._first_token_emitted = False

        for idx, sentence in enumerate(sentences):
            # 切分成更小的 delta chunk，模拟流式 token
            chunks = self._split_to_chunks(sentence)
            for chunk in chunks:
                full_text += chunk
                await ctx.emit(
                    Event(
                        type=LLM_TEXT_DELTA,
                        session_id=ctx.session_id,
                        source="llm.mock",
                        run_id=ctx.run_id,
                        payload={
                            "text": chunk,
                            "sentence_index": idx,
                            "is_sentence_end": False,
                        },
                    )
                )
                if self._chunk_delay_ms > 0:
                    await asyncio.sleep(self._chunk_delay_ms / 1000.0)

            # 句末标记
            await ctx.emit(
                Event(
                    type=LLM_TEXT_DELTA,
                    session_id=ctx.session_id,
                    source="llm.mock",
                    run_id=ctx.run_id,
                    payload={
                        "text": "",
                        "sentence_index": idx,
                        "is_sentence_end": True,
                    },
                )
            )

        await ctx.emit(
            Event(
                type=LLM_TEXT_DONE,
                session_id=ctx.session_id,
                source="llm.mock",
                run_id=ctx.run_id,
                payload={
                    "full_text": full_text,
                    "finish_reason": "stop",
                },
            )
        )

    def _pick_reply(self, user_text: str) -> list[str]:
        """根据用户输入关键词选回复模板。"""
        for keyword, reply in self._replies.items():
            if keyword != "default" and keyword in user_text:
                return reply
        return self._default_reply

    @staticmethod
    def _split_to_chunks(sentence: str) -> list[str]:
        """把句子切成小 chunk（模拟 token 流）。

        中文按 2-4 字一组，英文按词。简化版：按字符数。
        """
        if not sentence:
            return []
        # 简单策略：每 3 个字符一个 chunk
        return [sentence[i : i + 3] for i in range(0, len(sentence), 3)]

    async def reset(self, session_id: str) -> None:
        self._first_token_emitted = False
