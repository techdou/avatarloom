"""Ollama LLM Block。

本地 Ollama 服务（OpenAI 兼容模式）。

不依赖云 API——本地部署的 LLM（llama/qwen/deepseek 等）。
"""

from __future__ import annotations

from avatarloom_protocol import LLM_TEXT_DELTA, LLM_TEXT_DONE, TRANSCRIPT_COMPLETED, Event
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements


class OllamaLlmBlock(Block):
    """Ollama 本地 LLM（OpenAI 兼容）。"""

    _base_url: str = "http://127.0.0.1:11434/v1"
    _model: str = "qwen2.5:7b"

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="llm.ollama",
            name="Ollama LLM",
            category="llm",
            runtime_type="http_remote",
            capabilities=Capability(streaming=True, interruption=True),
            inputs=[TRANSCRIPT_COMPLETED],
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
        self._mark_ready()
        await ctx.logger.ainfo("llm.ollama ready", base_url=self._base_url, model=self._model)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        """复用 OpenAI-compatible 逻辑——Ollama 走 OpenAI 兼容接口。

        实际实现把 process 委托给 OpenAILlmBlock（同接口）。
        """
        from blocks.llm.openai_compatible import OpenAILlmBlock

        # 惰性创建共享实例
        if not hasattr(self, "_delegate"):
            self._delegate = OpenAILlmBlock()  # type: ignore[attr-defined]
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
            await self._delegate.setup(delegate_ctx)  # type: ignore[attr-defined]

        # 注入 emit
        self._delegate._api_key = "ollama"  # type: ignore[attr-defined]
        await self._delegate.process(ctx, event)  # type: ignore[attr-defined]
