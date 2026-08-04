"""OpenAI-compatible LLM Block。

实现 chat-completions 流式接口，任何 OpenAI 兼容端点都适用：
- OpenAI 官方
- DeepSeek（OpenAI 兼容）
- Moonshot / Kimi
- Ollama（OpenAI 兼容模式）
- vLLM / LM Studio / 本地兼容服务

特性：
- 流式逐 token 输出（stream: true）
- 按句切分喂 TTS（stream_batch_sentences）
- 支持 system prompt（来自 Persona）
- 支持 thinking 关闭（DeepSeek 等推理模型）
- asyncio cancel 支持（用户打断时取消进行中的 HTTP 请求）
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from avatarloom_protocol import (
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    TRANSCRIPT_COMPLETED,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability

# 中文/英文句末标点
_SENTENCE_END_RE = re.compile(r"[。！？!?\.…\n]")


class OpenAILlmBlock(Block):
    """OpenAI-compatible chat-completions LLM。"""

    _base_url: str = "https://api.openai.com/v1"
    _api_key: str = ""
    _model: str = "gpt-4o-mini"
    _timeout: float = 30.0
    _max_tokens: int = 512
    _temperature: float = 0.7
    _disable_thinking: bool = False  # DeepSeek 等推理模型用
    _batch_sentences: int = 1  # 凑够几句喂 TTS

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="llm.openai-compatible",
            name="OpenAI-compatible LLM",
            category="llm",
            runtime_type="http_remote",
            capabilities=Capability(streaming=True, interruption=True),
            inputs=[TRANSCRIPT_COMPLETED],
            outputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            resources=ResourceRequirements_stub(),
            config_schema={
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string", "default": "https://api.openai.com/v1"},
                    "apiKeyEnv": {"type": "string", "default": "LLM_API_KEY"},
                    "model": {"type": "string"},
                    "maxTokens": {"type": "integer", "default": 512},
                    "temperature": {"type": "number", "default": 0.7},
                    "disableThinking": {"type": "boolean", "default": False},
                    "systemPrompt": {"type": "string"},
                },
            },
            install_extras=[],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._base_url = str(
            cfg.get("baseUrl") or cfg.get("baseUrl") or "https://api.openai.com/v1"
        )
        # apiKeyEnv 指向环境变量名；apiKey 直接给值（二选一）
        api_key_env = str(cfg.get("apiKeyEnv") or "LLM_API_KEY")
        self._api_key = str(cfg.get("apiKey") or _read_env(api_key_env))
        self._model = str(cfg.get("model") or "gpt-4o-mini")
        self._max_tokens = int(cfg.get("maxTokens", 512))
        self._temperature = float(cfg.get("temperature", 0.7))
        self._disable_thinking = bool(cfg.get("disableThinking", False))
        self._batch_sentences = int(cfg.get("batchSentences", 1))
        self._mark_ready()
        await ctx.logger.ainfo(
            "llm.openai-compatible ready",
            base_url=self._base_url,
            model=self._model,
            has_key=bool(self._api_key),
        )

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type != TRANSCRIPT_COMPLETED:
            return

        user_text = event.payload.get("text", "")
        if not user_text.strip():
            return

        system_prompt = ctx.persona_instructions or str(ctx.config.get("systemPrompt") or "")
        messages = _build_messages(system_prompt, user_text)

        full_text = ""
        sentence_buf = ""
        sentence_idx = 0

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            ) as client:
                payload: dict[str, Any] = {
                    "model": self._model,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": self._max_tokens,
                    "temperature": self._temperature,
                }
                # DeepSeek 等推理模型：关 thinking
                if self._disable_thinking:
                    payload["extra_body"] = {"thinking": {"type": "disabled"}}

                async with client.stream("POST", "/chat/completions", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = _extract_delta(chunk)
                        if not delta:
                            continue

                        full_text += delta
                        sentence_buf += delta

                        # 流式 emit 每个 delta
                        await ctx.emit(
                            Event(
                                type=LLM_TEXT_DELTA,
                                session_id=ctx.session_id,
                                source="llm.openai-compatible",
                                run_id=ctx.run_id,
                                payload={
                                    "text": delta,
                                    "sentence_index": sentence_idx,
                                    "is_sentence_end": False,
                                },
                            )
                        )

                        # 按句切分（sentence 不直接用，TTS 按 sentence_index 累积）
                        while _has_sentence_end(sentence_buf):
                            _unused, sentence_buf = _split_sentence(sentence_buf)
                            sentence_idx += 1
                            await ctx.emit(
                                Event(
                                    type=LLM_TEXT_DELTA,
                                    session_id=ctx.session_id,
                                    source="llm.openai-compatible",
                                    run_id=ctx.run_id,
                                    payload={
                                        "text": "",
                                        "sentence_index": sentence_idx - 1,
                                        "is_sentence_end": True,
                                    },
                                )
                            )

        except httpx.HTTPStatusError as e:
            await ctx.emit(
                Event(
                    type=LLM_TEXT_DONE,
                    session_id=ctx.session_id,
                    source="llm.openai-compatible",
                    run_id=ctx.run_id,
                    payload={
                        "full_text": full_text,
                        "finish_reason": "error",
                        "first_token_ms": None,
                    },
                )
            )
            raise RuntimeError(
                f"LLM HTTP error {e.response.status_code}: {e.response.text[:200]}"
            ) from e

        # 句尾剩余
        if sentence_buf.strip():
            sentence_idx += 1
            await ctx.emit(
                Event(
                    type=LLM_TEXT_DELTA,
                    session_id=ctx.session_id,
                    source="llm.openai-compatible",
                    run_id=ctx.run_id,
                    payload={
                        "text": "",
                        "sentence_index": sentence_idx - 1,
                        "is_sentence_end": True,
                    },
                )
            )

        await ctx.emit(
            Event(
                type=LLM_TEXT_DONE,
                session_id=ctx.session_id,
                source="llm.openai-compatible",
                run_id=ctx.run_id,
                payload={"full_text": full_text, "finish_reason": "stop"},
            )
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_env(name: str) -> str:
    import os

    return os.environ.get(name, "")


def ResourceRequirements_stub():  # type: ignore[no-redef]
    """避免顶部 import 循环，惰性取 ResourceRequirements。"""
    from avatarloom_sdk import ResourceRequirements

    return ResourceRequirements()


def _build_messages(system_prompt: str, user_text: str) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": user_text})
    return msgs


def _extract_delta(chunk: dict) -> str:
    """从 SSE chunk 提取 text delta。兼容 OpenAI / DeepSeek 等。"""
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    # 某些推理模型把内容放 reasoning_content，这里只取 content
    return delta.get("content") or ""


def _has_sentence_end(text: str) -> bool:
    return bool(_SENTENCE_END_RE.search(text))


def _split_sentence(text: str) -> tuple[str, str]:
    """在第一个句末标点后切分。返回 (前句含标点, 剩余)。"""
    m = _SENTENCE_END_RE.search(text)
    if not m:
        return text, ""
    return text[: m.end()], text[m.end() :]
