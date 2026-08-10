"""StaticAvatar Block。

最简单的真实 Avatar——一张静态肖像图。

策略：
- setup 时加载 portrait.png（JPEG/PNG），转 base64 缓存
- 收到 tts.audio.delta 时 emit speech frame（复用同一张 portrait）
- 收到 tts.audio.completed 时 emit idle frame
- 可选：嘴型动画——根据 PCM 能量微调（v0.1 占位，不真做图像处理）

不依赖 GPU/Docker，任何环境都能跑。
是其他 Avatar Adapter（MuseTalk/FlashHead）的降级目标。
"""

from __future__ import annotations

import base64
from pathlib import Path

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements


class StaticAvatarBlock(Block):
    """静态肖像 Avatar。"""

    def __init__(self) -> None:
        super().__init__()
        self._portrait_b64: str = ""
        self._portrait_path: str = ""
        self._frame_index: int = 0
        self._width: int = 1280
        self._height: int = 720

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="avatar.static",
            name="Static Avatar (Portrait)",
            category="avatar",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=True),
            inputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            outputs=[AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME],
            resources=ResourceRequirements(),
            config_schema={
                "type": "object",
                "properties": {
                    "portrait": {"type": "string", "description": "肖像图路径（PNG/JPEG）"},
                    "width": {"type": "integer", "default": 1280},
                    "height": {"type": "integer", "default": 720},
                },
                "required": ["portrait"],
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        portrait_path = str(cfg.get("portrait", ""))
        self._width = int(cfg.get("width", 1280))
        self._height = int(cfg.get("height", 720))

        if not portrait_path:
            # 无配置——用 1x1 透明像素占位（降级模式）
            self._portrait_b64 = _TRANSPARENT_PIXEL_JPEG
            await ctx.logger.awarning("avatar.static: no portrait configured, using placeholder")
        else:
            # 解析路径（相对 workspace_root）
            p = Path(portrait_path)
            if not p.is_absolute():
                p = Path(ctx.workspace_root) / p
            if not p.exists():
                await ctx.logger.awarning(
                    "avatar.static: portrait not found, using placeholder", path=str(p)
                )
                self._portrait_b64 = _TRANSPARENT_PIXEL_JPEG
            else:
                raw = p.read_bytes()
                self._portrait_b64 = base64.b64encode(raw).decode("ascii")
                self._portrait_path = str(p)
                await ctx.logger.ainfo("avatar.static ready", portrait=str(p), size_bytes=len(raw))

        self._frame_index = 0
        self._mark_ready()

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type == TTS_AUDIO_DELTA:
            await self._emit_frame(ctx, is_speech=True)
        elif event.type == TTS_AUDIO_COMPLETED:
            await self._emit_frame(ctx, is_speech=False)

    async def _emit_frame(self, ctx: BlockContext, is_speech: bool) -> None:
        event_type = AVATAR_SPEECH_FRAME if is_speech else AVATAR_IDLE_FRAME
        await ctx.emit(
            Event(
                type=event_type,
                session_id=ctx.session_id,
                source="avatar.static",
                run_id=ctx.run_id,
                payload={
                    "frame_b64": self._portrait_b64,
                    "width": self._width,
                    "height": self._height,
                    "format": "jpeg",
                    "frame_index": self._frame_index,
                    "is_speech": is_speech,
                },
            )
        )
        self._frame_index += 1

    async def reset(self, session_id: str) -> None:
        self._frame_index = 0


# 1x1 透明 JPEG（无 portrait 配置时的降级占位）
_TRANSPARENT_PIXEL_JPEG = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDA"
    "FAPEBAQEBAPFBEAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQ"
    "EBAPFBAQEBAPFBAQEBAPFBAQEBAPF/Z"
)
