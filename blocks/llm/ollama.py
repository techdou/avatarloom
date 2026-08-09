"""Ollama LLM Block。

本地 Ollama 服务（OpenAI 兼容模式）。

不依赖云 API——本地部署的 LLM（llama/qwen/deepseek 等）。
"""

from __future__ import annotations

import contextlib

from avatarloom_protocol import (
    LLM_REQUEST,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements

from blocks.llm.openai_compatible import OpenAILlmBlock


class OllamaLlmBlock(Block):
    """Ollama 本地 LLM（OpenAI 兼容）。"""

    _base_url: str = "http://127.0.0.1:11434/v1"
    _model: str = "qwen2.5:7b"

    def __init__(self) -> None:
        super().__init__()
        self._delegate: OpenAILlmBlock | None = None

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="llm.ollama",
            name="Ollama LLM",
            category="llm",
            runtime_type="http_remote",
            capabilities=Capability(streaming=True, interruption=True),
            inputs=[LLM_REQUEST],
            outputs=[LLM_TEXT_DELTA, LLM_TEXT_DONE],
            resources=ResourceRequirements(),
            config_schema={
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string", "default": "http://127.0.0.1:11434/v1"},
                    "model": {"type": "string", "default": "qwen2.5:7b"},
                },
            },
            install_extras=["ollama"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._base_url = str(cfg.get("baseUrl") or "http://127.0.0.1:11434/v1")
        self._model = str(cfg.get("model") or "qwen2.5:7b")
        # 重 setup（fallback 重建/热切换）时先销毁旧 delegate，避免用陈旧配置
        if self._delegate is not None:
            with contextlib.suppress(Exception):
                await self._delegate.shutdown()
            self._delegate = None
        self._mark_ready()
        await ctx.logger.ainfo("llm.ollama ready", base_url=self._base_url, model=self._model)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        """复用 OpenAI-compatible 逻辑——Ollama 走 OpenAI 兼容接口。

        实际实现把 process 委托给 OpenAILlmBlock（同接口）。
        """
        # 惰性创建共享实例
        if self._delegate is None:
            self._delegate = OpenAILlmBlock()
            delegate_ctx = BlockContext(
                session_id=ctx.session_id,
                run_id=ctx.run_id,
                workspace_root=ctx.workspace_root,
                config={
                    "baseUrl": self._base_url,
                    "apiKey": "ollama",  # Ollama 不校验 key
                    "model": self._model,
                },
            )
            await self._delegate.setup(delegate_ctx)

        # 注入 emit
        self._delegate._api_key = "ollama"
        await self._delegate.process(ctx, event)

    async def reset(self, session_id: str) -> None:
        """透传打断/重置到 delegate——否则旧 run 的 HTTP 流不关闭，token 继续吐。"""
        if self._delegate is not None:
            await self._delegate.reset(session_id)

    async def shutdown(self) -> None:
        """透传 shutdown 到 delegate，释放 HTTP 连接池。"""
        if self._delegate is not None:
            await self._delegate.shutdown()
            self._delegate = None
