"""Orchestrator 配置模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BlockRef(BaseModel):
    """Profile 里对一个 Block 的引用。"""

    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Block ID，如 'vad.mock'")
    deployment: Literal[
        "local", "cpu-local", "cuda-local", "remote", "remote-api", "mac-mlx", "nvidia-cuda", "mock"
    ] = "local"
    config: dict[str, Any] = Field(default_factory=dict)
    optional: bool = Field(default=False, description="此 Block 可缺席")
    fallback: str | None = Field(default=None, description="失败时降级到的 Block ID")


class SyncConfig(BaseModel):
    """音画同步配置。"""

    model_config = ConfigDict(extra="forbid")

    audio_delay_ms: int = Field(default=600, ge=0)
    video_lag_frames: int = Field(default=0, ge=0)
    max_video_behind_ms: int = Field(default=1000, ge=0)
    drop_policy: Literal["drop_oldest_video", "drop_newest_video", "block"] = "drop_oldest_video"


class OrchestratorConfig(BaseModel):
    """Orchestrator 配置——对应 RuntimeProfile + avatarloom.yaml。"""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = "mock"
    blocks: dict[str, BlockRef] = Field(
        default_factory=dict,
        description="category -> BlockRef，如 {'vad': BlockRef(id='vad.mock')}",
    )
    sync: SyncConfig = Field(default_factory=SyncConfig)
    allow_interruption: bool = True
    event_log: bool = True
    session_mode: Literal["single", "multi"] = "single"
    vision_timeout_s: float = Field(
        default=8.0,
        gt=0,
        description="触发词命中后等待 vision.result 的最长秒数，超时降级为无视觉回答",
    )
