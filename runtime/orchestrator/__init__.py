"""AvatarLoom Orchestrator — Block 编排核心。

职责（docs/00 第 3 节 Runtime Plane）：
- 从 Profile 装配 Block 实例（VAD/STT/LLM/TTS/Avatar/Vision）
- 把 EventBus 订阅连成主链路：audio → VAD → STT → LLM → TTS → Avatar → browser
- 驱动 Session 状态机
- 处理打断、取消、降级
- 双写：TTS audio delta 一路给浏览器、一路给 Avatar
- 可选 Block（Vision）缺席时不阻断

参考 VoxEMW orchestrator 的双写和降级模式。
"""

from runtime.orchestrator.orchestrator import Orchestrator, OrchestratorConfig

__all__ = ["Orchestrator", "OrchestratorConfig"]
