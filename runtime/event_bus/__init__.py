"""AvatarLoom 内存事件总线。

设计：
- asyncio.Queue based，每订阅者独立队列
- 背压保护：队列满时按策略处理（drop_oldest / drop_new / block）
- 支持通配订阅（按事件分类前缀）
- 不保证跨进程（生产可换 Redis Streams / Kafka）

参考 VoxEMW orchestrator.py 的 asyncio.Queue(maxsize=25) 模式。
"""

from runtime.event_bus.bus import EventBus, Subscription
from runtime.event_bus.policy import BackpressurePolicy

__all__ = ["EventBus", "Subscription", "BackpressurePolicy"]
