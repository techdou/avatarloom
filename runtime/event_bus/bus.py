"""EventBus 实现。

订阅模型：
- subscribe("transcript.*", handler)  通配符订阅
- subscribe("transcript.completed", handler)  精确订阅
- subscribe("*", handler)  全部订阅（Recorder 用）

每个订阅有独立队列 + 独立消费任务。队列满按 policy 处理。
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from avatarloom_protocol import Event

from runtime.event_bus.policy import BackpressurePolicy

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]


@dataclass
class Subscription:
    """事件订阅句柄。"""

    sub_id: str
    pattern: str
    handler: EventHandler
    queue: asyncio.Queue[Event]
    policy: BackpressurePolicy
    _consumer_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)

    @property
    def is_closed(self) -> bool:
        return self._closed


class EventBus:
    """asyncio 内存事件总线。

    用法：
        bus = EventBus()
        sub = await bus.subscribe("transcript.*", my_handler)
        await bus.publish(event)
        await sub.unsubscribe()
    """

    def __init__(
        self,
        *,
        default_queue_size: int = 256,
        default_policy: BackpressurePolicy = BackpressurePolicy.BLOCK,
    ) -> None:
        self._subs: dict[str, Subscription] = {}
        self._default_queue_size = default_queue_size
        self._default_policy = default_policy
        self._sub_counter = 0
        self._lock = asyncio.Lock()
        self._closed = False

    async def subscribe(
        self,
        pattern: str,
        handler: EventHandler,
        *,
        queue_size: int | None = None,
        policy: BackpressurePolicy | None = None,
    ) -> Subscription:
        """订阅事件。

        Args:
            pattern: 事件类型 glob 模式。"transcript.*" 匹配所有 transcript 前缀；
                     "*" 匹配所有事件。
            handler: async (event) -> None
            queue_size: 此订阅的队列容量。None 用默认值。
            policy: 队列满策略。None 用默认值。
        """
        async with self._lock:
            if self._closed:
                raise RuntimeError("EventBus is closed")
            self._sub_counter += 1
            sub_id = f"sub_{self._sub_counter}"
            q: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size or self._default_queue_size)
            sub = Subscription(
                sub_id=sub_id,
                pattern=pattern,
                handler=handler,
                queue=q,
                policy=policy or self._default_policy,
            )
            # 启消费任务
            sub._consumer_task = asyncio.create_task(self._consumer(sub), name=f"ebus:{sub_id}")
            self._subs[sub_id] = sub
            logger.debug("EventBus subscribe %s -> %s", pattern, sub_id)
            return sub

    async def unsubscribe(self, sub: Subscription) -> None:
        """取消订阅。"""
        async with self._lock:
            if sub.sub_id not in self._subs:
                return
            sub._closed = True
            stored = self._subs.pop(sub.sub_id, None)
        if stored and stored._consumer_task:
            stored._consumer_task.cancel()
            try:
                await stored._consumer_task
            except asyncio.CancelledError:
                pass

    async def publish(self, event: Event) -> None:
        """发布事件到所有匹配订阅。

        匹配失败的订阅不影响其他订阅。
        队列满按各订阅的 policy 处理。
        """
        if self._closed:
            raise RuntimeError("EventBus is closed")

        # 快照订阅避免持锁 await
        matched: list[Subscription] = []
        async with self._lock:
            for sub in self._subs.values():
                if sub._closed:
                    continue
                if self._matches(sub.pattern, event.type):
                    matched.append(sub)

        for sub in matched:
            await self._enqueue(sub, event)

    async def close(self) -> None:
        """关闭总线，取消所有订阅。"""
        async with self._lock:
            self._closed = True
            subs = list(self._subs.values())
            self._subs.clear()
        for sub in subs:
            sub._closed = True
            if sub._consumer_task:
                sub._consumer_task.cancel()
        for sub in subs:
            if sub._consumer_task:
                try:
                    await sub._consumer_task
                except asyncio.CancelledError:
                    pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    # ---- 内部 ----

    @staticmethod
    def _matches(pattern: str, event_type: str) -> bool:
        """glob 匹配。'transcript.*' 匹配 'transcript.completed'。"""
        return fnmatch.fnmatchcase(event_type, pattern)

    async def _enqueue(self, sub: Subscription, event: Event) -> None:
        """按 policy 入队。

        BLOCK 策略不能无限 await q.put——快照（publish 持锁阶段）到 enqueue
        之间，订阅可能被 unsubscribe/close 取消了 consumer。此时队列满时 put
        永远等不到空位，publisher（往往是另一个订阅的 consumer 任务）会
        静默挂死。用"put_nowait → QueueFull 时短超时等待 + 复查 closed"循环解决。
        """
        q = sub.queue
        try:
            if sub.policy == BackpressurePolicy.BLOCK:
                # 先尝试无阻塞入队
                try:
                    q.put_nowait(event)
                    return
                except asyncio.QueueFull:
                    pass
                # 队满——短超时轮询等待空位，每次复查 sub 是否已关闭
                while not sub._closed:
                    try:
                        await asyncio.wait_for(q.put(event), timeout=0.1)
                        return
                    except TimeoutError:
                        continue
                    except asyncio.QueueFull:
                        continue
                # sub 已关闭——丢弃事件（消费者已不在，入队无意义）
                return
            elif sub.policy == BackpressurePolicy.DROP_OLDEST:
                if q.full():
                    # 丢最旧的一个——并发场景下可能已被取走，QueueEmpty 忽略
                    with contextlib.suppress(asyncio.QueueEmpty):
                        q.get_nowait()
                    logger.debug("EventBus drop_oldest for %s", sub.sub_id)
                await q.put(event)
            elif sub.policy == BackpressurePolicy.DROP_NEWEST:
                if q.full():
                    logger.debug("EventBus drop_newest for %s", sub.sub_id)
                    return
                await q.put(event)
        except asyncio.CancelledError:
            raise

    async def _consumer(self, sub: Subscription) -> None:
        """消费循环：从队列取事件调 handler。"""
        try:
            while not sub._closed:
                event = await sub.queue.get()
                try:
                    await sub.handler(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "EventBus handler error in sub %s for event %s",
                        sub.sub_id,
                        event.type,
                    )
                finally:
                    sub.queue.task_done()
        except asyncio.CancelledError:
            pass
