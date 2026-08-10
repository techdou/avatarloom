"""AvatarLoom Block SDK.

提供开发新 Block 所需的基类、Context、Manifest 和健康检查协议，
以及 avatar 状态推导纯函数（下沉自 runtime.orchestrator.avatar_state）。
"""

from avatarloom_sdk.avatar_state import AvatarState, transition_avatar_state
from avatarloom_sdk.base import (
    Block,
    BlockCancelledError,
    BlockContext,
    BlockError,
    BlockManifest,
    BlockNotReadyError,
    BlockSetupError,
    Capability,
    HealthStatus,
    ResourceRequirements,
    Timer,
    create_block,
    now_ms,
)

__all__ = [
    "AvatarState",
    "Block",
    "BlockCancelledError",
    "BlockContext",
    "BlockError",
    "BlockManifest",
    "BlockNotReadyError",
    "BlockSetupError",
    "Capability",
    "HealthStatus",
    "ResourceRequirements",
    "Timer",
    "create_block",
    "now_ms",
    "transition_avatar_state",
]

__version__ = "0.1.0"
