"""AvatarLoom Block SDK.

提供开发新 Block 所需的基类、Context、Manifest 和健康检查协议。
"""

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
    StreamingBlock,
    Timer,
    create_block,
    now_ms,
)

__all__ = [
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
    "StreamingBlock",
    "Timer",
    "create_block",
    "now_ms",
]

__version__ = "0.1.0"
