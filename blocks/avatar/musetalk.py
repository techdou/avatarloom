"""MuseTalk Avatar Block。

基于 MuseTalk 的实时口型驱动数字人。

输入：参考肖像图 + TTS 音频流
输出：JPEG 帧流（音画同步）

重依赖：torch + opencv + imageio（extras=musetalk）。
GPU 实机未验证——单测覆盖帧索引、JPEG 编码逻辑。
"""

from __future__ import annotations

import base64
from typing import Any

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)
from avatarloom_sdk import (
    Block,
    BlockContext,
    BlockManifest,
    BlockSetupError,
    Capability,
    ResourceRequirements,
)


class MuseTalkAvatarBlock(Block):
    """MuseTalk——参考图 + 音频驱动口型。"""

    _model: Any = None
    _device: str = "cuda"
    _portrait: bytes = b""
    _frame_index: int = 0

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="avatar.musetalk",
            name="MuseTalk Avatar",
            category="avatar",
            runtime_type="python_inproc",
            capabilities=Capability(streaming=True),
            inputs=[TTS_AUDIO_DELTA, TTS_AUDIO_COMPLETED],
            outputs=[AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME],
            resources=ResourceRequirements(
                accelerator=["cuda"],
                estimated_vram_mb=5000,
                pip_extras=["musetalk"],
            ),
            config_schema={
                "type": "object",
                "properties": {
                    "device": {"type": "string", "default": "cuda"},
                    "portrait": {"type": "string"},
                    "fps": {"type": "integer", "default": 25},
                },
            },
            install_extras=["musetalk"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._device = str(cfg.get("device", "cuda"))
        portrait_path = cfg.get("portrait")
        if portrait_path:
            from pathlib import Path

            p = Path(str(portrait_path))
            if not p.is_absolute():
                p = Path(ctx.workspace_root) / p
            if p.exists():
                self._portrait = p.read_bytes()

        try:
            self._model = self._load_model(self._device)
        except ImportError as e:
            raise BlockSetupError(
                "avatar.musetalk",
                f"musetalk 依赖未安装: {e}. 运行 `uv sync --extra musetalk`",
            ) from e
        except Exception as e:
            raise BlockSetupError("avatar.musetalk", f"加载失败: {e}") from e

        self._frame_index = 0
        self._mark_ready()
        await ctx.logger.ainfo("avatar.musetalk ready", device=self._device)

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type == TTS_AUDIO_DELTA:
            pcm_b64 = event.payload.get("pcm_b64", "")
            if pcm_b64:
                await self._drive_frame(ctx, pcm_b64, is_speech=True)
        elif event.type == TTS_AUDIO_COMPLETED:
            await self._emit_idle(ctx)

    async def _drive_frame(self, ctx: BlockContext, pcm_b64: str, is_speech: bool) -> None:
        try:
            jpeg = self._infer(pcm_b64)
        except Exception as e:
            await ctx.logger.aerror("musetalk infer error", error=str(e))
            return
        await ctx.emit(
            Event(
                type=AVATAR_SPEECH_FRAME,
                session_id=ctx.session_id,
                source="avatar.musetalk",
                run_id=ctx.run_id,
                payload={
                    "frame_b64": base64.b64encode(jpeg).decode("ascii"),
                    "width": 1280,
                    "height": 720,
                    "format": "jpeg",
                    "frame_index": self._frame_index,
                    "is_speech": is_speech,
                },
            )
        )
        self._frame_index += 1

    async def _emit_idle(self, ctx: BlockContext) -> None:
        await ctx.emit(
            Event(
                type=AVATAR_IDLE_FRAME,
                session_id=ctx.session_id,
                source="avatar.musetalk",
                run_id=ctx.run_id,
                payload={
                    "frame_b64": base64.b64encode(self._portrait or b"").decode("ascii"),
                    "frame_index": self._frame_index,
                    "is_speech": False,
                },
            )
        )

    async def reset(self, session_id: str) -> None:
        self._frame_index = 0

    # ---- 重依赖 ----

    def _load_model(self, device: str) -> Any:
        # 真实实现：from musetalk.models import MuseTalk; ...
        # 这里只占位，实际加载逻辑按 MuseTalk 官方 demo
        import torch  # noqa: F401  确认 torch 可用

        return {"device": device, "_loaded": True}

    def _infer(self, pcm_b64: str) -> bytes:
        """从音频 chunk 生成 JPEG 帧。"""
        import cv2  # type: ignore
        import numpy as np

        # 占位：返回 portrait 的 JPEG 编码
        if self._portrait:
            return self._portrait
        # 无 portrait：生成 1x1 黑帧
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        _, jpeg = cv2.imencode(".jpg", img)
        return jpeg.tobytes()
