"""FlashHead Avatar Block（占位）。

SoulX-FlashHead-1_3B——预留 Adapter，v0.1 仅声明 manifest，不实装推理。

真实实现需独立 Python 环境（py310/torch2.7.1/transformers4.57.3），
与主项目依赖冲突，通过远程服务或容器隔离。
"""

from __future__ import annotations

from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements


class FlashHeadAvatarBlock(Block):
    """FlashHead Avatar——预留。"""

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="avatar.flashhead",
            name="FlashHead Avatar (stub)",
            category="avatar",
            runtime_type="http_remote",  # 通过远程服务
            capabilities=Capability(streaming=True),
            resources=ResourceRequirements(
                accelerator=["cuda"],
                estimated_vram_mb=6000,
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string", "description": "FlashHead 服务 URL"},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        from avatarloom_sdk import BlockSetupError

        raise BlockSetupError(
            "avatar.flashhead",
            "FlashHead 需独立环境（py310/torch2.7.1/transformers4.57.3），"
            "通过远程服务接入。本 Adapter 是预留占位，v0.1 未实装推理。",
        )

    async def process(self, ctx: BlockContext, event: object) -> None:
        raise NotImplementedError("FlashHead 推理未实装")
