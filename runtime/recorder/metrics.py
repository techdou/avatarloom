"""Run 性能指标。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunMetrics(BaseModel):
    """单轮 Run 的性能指标。

    所有 *_ms 字段是从 Run 开始计的相对毫秒数。
    None 表示未采集到（如该事件没发生）。
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str
    profile_id: str
    persona_id: str | None = None
    started_at_ms: int
    ended_at_ms: int | None = None

    # 关键延迟指标
    first_text_ms: int | None = Field(
        default=None, description="从 Run 开始到 LLM 首个 text delta 的毫秒数"
    )
    first_audio_ms: int | None = Field(
        default=None, description="从 Run 开始到 TTS 首个 audio delta 的毫秒数"
    )
    first_frame_ms: int | None = Field(
        default=None, description="从 Run 开始到 Avatar 首个 frame 的毫秒数"
    )
    total_duration_ms: int | None = None

    # 可靠性指标
    interruptions: int = 0
    degradations: int = 0
    errors: int = 0
    cancelled: bool = False

    # 对话内容统计
    user_text: str = ""
    assistant_text: str = ""
    user_audio_samples: int = 0
    assistant_audio_samples: int = 0
    avatar_frames: int = 0

    # 元数据
    block_versions: dict[str, str] = Field(default_factory=dict)
    degraded_blocks: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
