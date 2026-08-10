"""Mock Avatar Block。

收到 tts.audio.delta 时 emit avatar.speech_frame（Mock JPEG——用纯色占位）。

策略：
- v0.1 不真渲染——生成 1x1 像素 JPEG 占位（或可配置颜色块）
- 按 TTS chunk 节奏 emit frame（演示音画同步协议）
- TTS completed 时切回 idle frame

这样前端能演示音画同步消费逻辑，无需真实 GPU 渲染。
"""

from __future__ import annotations

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability

# 1x1 像素 JPEG（最小占位图，base64）
# 真实场景由 StaticAvatar/MuseTalk 产 JPEG；Mock 用这个让前端管线能跑通
_PLACEHOLDER_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDA"
    "FAPEBAQEBAPFBEAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQEBAPFBAQ"
    "EBAPFBAQEBAPFBAQEBAPFBAQEBAPF/Z"
)


class MockAvatarBlock(Block):
    """Mock Avatar — 占位 JPEG 帧。"""

    def __init__(self) -> None:
        super().__init__()
        self._frame_index: int = 0
        self._is_speaking: bool = False

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="avatar.mock",
            name="Mock Avatar (Placeholder)",
            category="avatar",
            runtime_type="mock",
            capabilities=Capability(streaming=True),
            inputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            outputs=[AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME],
            config_schema={"type": "object"},
        )

    async def setup(self, ctx: BlockContext) -> None:
        self._frame_index = 0
        self._is_speaking = False
        self._mark_ready()
        await ctx.logger.ainfo("avatar.mock ready")

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type == TTS_AUDIO_DELTA:
            self._is_speaking = True
            await self._emit_frame(ctx, is_speech=True)
        elif event.type == TTS_AUDIO_COMPLETED:
            self._is_speaking = False
            await self._emit_frame(ctx, is_speech=False)

    async def _emit_frame(self, ctx: BlockContext, is_speech: bool) -> None:
        event_type = AVATAR_SPEECH_FRAME if is_speech else AVATAR_IDLE_FRAME
        await ctx.emit(
            Event(
                type=event_type,
                session_id=ctx.session_id,
                source="avatar.mock",
                run_id=ctx.run_id,
                payload={
                    "frame_b64": _PLACEHOLDER_JPEG_B64,
                    "width": 1280,
                    "height": 720,
                    "format": "jpeg",
                    "frame_index": self._frame_index,
                    "is_speech": is_speech,
                },
            )
        )
        self._frame_index += 1

    async def reset(self, session_id: str) -> None:
        self._is_speaking = False
        self._frame_index = 0
