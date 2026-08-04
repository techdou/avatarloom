"""OpenAI-compatible Vision Block。

基于多模态 LLM 的视觉感知（GPT-4o / Gemini / Qwen-VL 等）。

可缺席——不订阅主链路事件，通过 Control API 显式触发。
"""

from __future__ import annotations

import httpx
from avatarloom_protocol import VISION_RESULT, Event
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements


class OpenAIVisionBlock(Block):
    """OpenAI-compatible Vision——多模态图像描述。"""

    _base_url: str = "https://api.openai.com/v1"
    _api_key: str = ""
    _model: str = "gpt-4o"
    _timeout: float = 30.0

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="vision.openai-compatible",
            name="OpenAI-compatible Vision",
            category="vision",
            runtime_type="http_remote",
            capabilities=Capability(optional=True),
            inputs=[],
            outputs=[VISION_RESULT],
            resources=ResourceRequirements(),
            config_schema={
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string"},
                    "apiKeyEnv": {"type": "string", "default": "VISION_API_KEY"},
                    "model": {"type": "string", "default": "gpt-4o"},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._base_url = str(cfg.get("baseUrl") or "https://api.openai.com/v1")
        import os

        api_key_env = str(cfg.get("apiKeyEnv") or "VISION_API_KEY")
        self._api_key = str(cfg.get("apiKey") or os.environ.get(api_key_env, ""))
        self._model = str(cfg.get("model") or "gpt-4o")
        self._mark_ready()
        await ctx.logger.ainfo("vision.openai-compatible ready", model=self._model)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        """不订阅主链路——通过 describe_frame 显式调用。"""
        pass

    async def describe_frame(
        self, ctx: BlockContext, image_b64: str, prompt: str = "描述这张图片"
    ) -> Event:
        """显式触发——发送图片到多模态 LLM 描述。"""
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            ) as client:
                payload = {
                    "model": self._model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                                },
                            ],
                        }
                    ],
                    "max_tokens": 300,
                }
                resp = await client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                result = resp.json()
                description = result["choices"][0]["message"]["content"]
        except Exception as e:
            await ctx.logger.aerror("vision error", error=str(e))
            description = "（视觉感知失败）"

        event = Event(
            type=VISION_RESULT,
            session_id=ctx.session_id,
            source="vision.openai-compatible",
            run_id=ctx.run_id,
            payload={"description": description, "objects": [], "confidence": 0.9},
        )
        await ctx.emit(event)
        return event
