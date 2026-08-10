"""兼容 shim——内容已下沉到 avatarloom_sdk.avatar_state。

保留此文件仅为不破坏现有 `from runtime.orchestrator.avatar_state import ...` 引用；
逻辑权威定义在 SDK 层（blocks 也从 SDK 导入，避免反向依赖 runtime 核心）。
"""

from __future__ import annotations

from avatarloom_sdk.avatar_state import AvatarState, transition_avatar_state

__all__ = ["AvatarState", "transition_avatar_state"]
