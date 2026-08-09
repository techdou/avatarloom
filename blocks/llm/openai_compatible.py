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

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from avatarloom_protocol import (
    LLM_REQUEST,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    Event,
)
from avatarloom_sdk import (
    Block,
    BlockContext,
    BlockManifest,
    Capability,
    ResourceRequirements,
)

# 中文/英文句末标点
_SENTENCE_END_RE = re.compile(r"[。！？!?\.…\n]")
_RETRYABLE_HTTP_ERRORS = (
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


@dataclass
class _LlmStreamState:
    full_text: str = ""
    sentence_buf: str = ""
    sentence_idx: int = 0
    interrupted: bool = False


class OpenAILlmBlock(Block):
    """OpenAI-compatible chat-completions LLM。"""

    _base_url: str = "https://api.openai.com/v1"
    _api_key: str = ""
    _model: str = "gpt-4o-mini"
    _timeout: float = 30.0
    _max_tokens: int = 512
    _temperature: float = 0.7
    _disable_thinking: bool = False  # DeepSeek 等推理模型用

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="llm.openai-compatible",
            name="OpenAI-compatible LLM",
            category="llm",
            runtime_type="http_remote",
            capabilities=Capability(streaming=True, interruption=True),
            inputs=[LLM_REQUEST],
            outputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            resources=ResourceRequirements(),
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
        self._base_url = str(cfg.get("baseUrl") or "https://api.openai.com/v1")
        # apiKeyEnv 指向环境变量名；apiKey 直接给值（二选一）
        api_key_env = str(cfg.get("apiKeyEnv") or "LLM_API_KEY")
        self._api_key = str(cfg.get("apiKey") or _read_env(api_key_env))
        self._model = str(cfg.get("model") or "gpt-4o-mini")
        self._max_tokens = int(cfg.get("maxTokens", 512))
        self._temperature = float(cfg.get("temperature", 0.7))
        self._disable_thinking = bool(cfg.get("disableThinking", False))
        # 请求超时（秒）——云端 LLM 首 token 可能慢，可配置防误时
        self._timeout = float(cfg.get("timeoutS", self._timeout))
        # 打断协作状态（AL-P1-006）——实例级，不能放类属性（可变对象跨实例共享）
        self._interrupted_run_ids: set[str] = set()
        self._active_run_id: str | None = None
        self._active_resp: httpx.Response | None = None
        self._mark_ready()
        await ctx.logger.ainfo(
            "llm.openai-compatible ready",
            base_url=self._base_url,
            model=self._model,
            has_key=bool(self._api_key),
        )

    async def reset(self, session_id: str) -> None:
        """打断（AL-P1-006）：标记当前 run 为 interrupted 并立即关闭 HTTP 流。

        双保险：aclose() 让阻塞中的 aiter_lines 立刻解脱（抛 StreamError），
        标记检查让流式循环走可控 break 路径。旧 run 不再产生后续 delta。
        """
        if self._active_run_id is not None:
            self._interrupted_run_ids.add(self._active_run_id)
        resp = self._active_resp
        if resp is not None:
            # 关闭失败无所谓——标记已生效，流式循环会走打断检查退出
            import contextlib

            with contextlib.suppress(Exception):
                await resp.aclose()

    async def _emit_done(self, ctx: BlockContext, full_text: str, finish_reason: str) -> None:
        """收尾事件统一出口——error 路径也必须发 DONE，否则下游（TTS）永远等不到收尾。"""
        await ctx.emit(
            Event(
                type=LLM_TEXT_DONE,
                session_id=ctx.session_id,
                source="llm.openai-compatible",
                run_id=ctx.run_id,
                payload={
                    "full_text": full_text,
                    "finish_reason": finish_reason,
                    "first_token_ms": None,
                },
            )
        )

    async def process(self, ctx: BlockContext, event: Event) -> None:
        # 只消费 llm.request（Orchestrator 完成 Vision 同轮编排后发出）。
        # 不再兼容 transcript.completed——AL-P1-002 后 transcript 由 Orchestrator 决策。
        if self._should_skip_request(ctx, event):
            return

        user_text = str(event.payload.get("text", ""))
        messages = _build_messages(_system_prompt(ctx), user_text)
        state = _LlmStreamState()
        self._active_run_id = ctx.run_id

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            ) as client:
                await self._stream_with_retries(ctx, client, messages, state)

        except httpx.HTTPStatusError as e:
            await self._emit_done(ctx, state.full_text, "error")
            raise RuntimeError(
                # 不拼接上游响应体——可能回显 prompt/密钥，进日志即泄露
                f"LLM HTTP error {e.response.status_code}"
            ) from e
        finally:
            self._active_run_id = None

        # 被打断：不发句尾剩余，直接以 interrupted 收尾（AL-P1-006）
        if state.interrupted:
            await self._emit_done(ctx, state.full_text, "interrupted")
            return

        # 句尾剩余
        if state.sentence_buf.strip():
            state.sentence_idx += 1
            await self._emit_sentence_end(ctx, state.sentence_idx - 1)

        await self._emit_done(ctx, state.full_text, "stop")

    def _should_skip_request(self, ctx: BlockContext, event: Event) -> bool:
        if event.type != LLM_REQUEST:
            return True
        user_text = event.payload.get("text", "")
        if not str(user_text).strip():
            return True
        # 打断后迟到的 request（旧 run）不再生成——新 run 的 request run_id 不同，不受影响
        return ctx.run_id is not None and ctx.run_id in self._interrupted_run_ids

    def _request_payload(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        # DeepSeek 等推理模型：关 thinking。必须是顶层 thinking 字段——
        # DeepSeek 官方 API 只认顶层（extra_body 嵌套会被忽略，思考照跑，
        # 思考 token 挤占 max_tokens 时偶发 content 全空 → TTS 零产出）
        if self._disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        return payload

    async def _stream_with_retries(
        self,
        ctx: BlockContext,
        client: httpx.AsyncClient,
        messages: list[dict[str, str]],
        state: _LlmStreamState,
    ) -> None:
        payload = self._request_payload(messages)
        for attempt in range(3):
            try:
                completed = await self._stream_once(ctx, client, payload, state, attempt)
            except _RETRYABLE_HTTP_ERRORS:
                if await self._sleep_before_retry(ctx, state.full_text, attempt):
                    continue
                await self._emit_done(ctx, state.full_text, "error")
                raise
            if not completed and state.interrupted:
                break
            if not completed:
                continue
            if state.interrupted:
                break
            if await self._sleep_before_retry(ctx, state.full_text, attempt):
                continue
            break

    async def _stream_once(
        self,
        ctx: BlockContext,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        state: _LlmStreamState,
        attempt: int,
    ) -> bool:
        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            self._active_resp = resp
            try:
                await self._consume_stream_lines(ctx, resp, state)
            except httpx.StreamError as exc:
                if await self._handle_stream_error(ctx, state, attempt):
                    return False
                raise exc
            finally:
                self._active_resp = None
        return True

    async def _consume_stream_lines(
        self,
        ctx: BlockContext,
        resp: httpx.Response,
        state: _LlmStreamState,
    ) -> None:
        async for line in resp.aiter_lines():
            if ctx.run_id is not None and ctx.run_id in self._interrupted_run_ids:
                state.interrupted = True
                break
            data = _sse_data(line)
            if data is None:
                continue
            if data == "[DONE]":
                break
            delta = _delta_from_sse_data(data)
            if not delta:
                continue
            await self._emit_text_delta(ctx, delta, state)

    async def _handle_stream_error(
        self,
        ctx: BlockContext,
        state: _LlmStreamState,
        attempt: int,
    ) -> bool:
        # reset() 里 resp.aclose() 会让 aiter_lines 抛 StreamError
        if ctx.run_id is not None and ctx.run_id in self._interrupted_run_ids:
            state.interrupted = True
            return True
        if not state.full_text and attempt < 2:
            # 无产出断流——重试（有产出不重试，避免内容重复）
            await asyncio.sleep(0.5 * (attempt + 1))
            return True
        # 重试耗尽/已有产出断流——必须补发 DONE(error) 收尾，
        # 否则 TTS 收不到 DONE 不吐 completed，前端永远停在"思考中"
        await self._emit_done(ctx, state.full_text, "error")
        return False

    async def _sleep_before_retry(
        self,
        ctx: BlockContext,
        full_text: str,
        attempt: int,
    ) -> bool:
        if attempt >= 2 or full_text:
            return False
        if ctx.run_id is not None and ctx.run_id in self._interrupted_run_ids:
            return False
        # 成功完成但零产出 / 连接层未产出失败：退避后重试。
        await asyncio.sleep(0.5 * (attempt + 1))
        return True

    async def _emit_text_delta(
        self,
        ctx: BlockContext,
        delta: str,
        state: _LlmStreamState,
    ) -> None:
        state.full_text += delta
        state.sentence_buf += delta
        await ctx.emit(
            Event(
                type=LLM_TEXT_DELTA,
                session_id=ctx.session_id,
                source="llm.openai-compatible",
                run_id=ctx.run_id,
                payload={
                    "text": delta,
                    "sentence_index": state.sentence_idx,
                    "is_sentence_end": False,
                },
            )
        )
        while _has_sentence_end(state.sentence_buf):
            _unused, state.sentence_buf = _split_sentence(state.sentence_buf)
            state.sentence_idx += 1
            await self._emit_sentence_end(ctx, state.sentence_idx - 1)

    async def _emit_sentence_end(self, ctx: BlockContext, sentence_idx: int) -> None:
        await ctx.emit(
            Event(
                type=LLM_TEXT_DELTA,
                session_id=ctx.session_id,
                source="llm.openai-compatible",
                run_id=ctx.run_id,
                payload={
                    "text": "",
                    "sentence_index": sentence_idx,
                    "is_sentence_end": True,
                },
            )
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_env(name: str) -> str:
    import os

    return os.environ.get(name, "")


def _build_messages(system_prompt: str, user_text: str) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": user_text})
    return msgs


def _system_prompt(ctx: BlockContext) -> str:
    system_prompt = ctx.persona_instructions or str(ctx.config.get("systemPrompt") or "")
    # 视觉感知注入：最近一次摄像头帧描述（若有）
    if ctx.vision_description:
        system_prompt += (
            "\n\n【视觉感知】用户刚刚让你看的画面："
            f"{ctx.vision_description}。请自然地基于此回应。"
        )
    return system_prompt


def _sse_data(line: str) -> str | None:
    if not line or not line.startswith("data: "):
        return None
    return line[6:].strip()


def _delta_from_sse_data(data: str) -> str:
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return ""
    return _extract_delta(chunk)


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
