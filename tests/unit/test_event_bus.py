"""EventBus 测试。"""

from __future__ import annotations

import asyncio

import pytest
from avatarloom_protocol import Event

from runtime.event_bus import BackpressurePolicy, EventBus


class TestEventBusBasic:
    async def test_subscribe_and_publish(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        sub = await bus.subscribe("test.*", handler)
        await bus.publish(Event(type="test.foo", session_id="s", source="b"))
        # 给 consumer 时间处理
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].type == "test.foo"
        await bus.unsubscribe(sub)
        await bus.close()

    async def test_pattern_matching_glob(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def handler(e: Event) -> None:
            received.append(e.type)

        await bus.subscribe("transcript.*", handler)
        await bus.publish(Event(type="transcript.completed", session_id="s", source="b"))
        await bus.publish(Event(type="transcript.partial", session_id="s", source="b"))
        await bus.publish(Event(type="llm.text.delta", session_id="s", source="b"))
        await asyncio.sleep(0.05)

        assert sorted(received) == ["transcript.completed", "transcript.partial"]
        await bus.close()

    async def test_wildcard_subscribe_all(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def handler(e: Event) -> None:
            received.append(e.type)

        await bus.subscribe("*", handler)
        await bus.publish(Event(type="a.b", session_id="s", source="b"))
        await bus.publish(Event(type="c.d", session_id="s", source="b"))
        await asyncio.sleep(0.05)

        assert len(received) == 2
        await bus.close()

    async def test_multiple_subscribers(self) -> None:
        bus = EventBus()
        a: list[Event] = []
        b: list[Event] = []

        async def ha(e: Event) -> None:
            a.append(e)

        async def hb(e: Event) -> None:
            b.append(e)

        await bus.subscribe("x.*", ha)
        await bus.subscribe("x.y", hb)  # 精确订阅
        await bus.publish(Event(type="x.y", session_id="s", source="b"))
        await bus.publish(Event(type="x.z", session_id="s", source="b"))
        await asyncio.sleep(0.05)

        assert len(a) == 2  # 通配符收到两次
        assert len(b) == 1  # 精确只收到一次
        await bus.close()

    async def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        sub = await bus.subscribe("x", handler)
        await bus.publish(Event(type="x", session_id="s", source="b"))
        await asyncio.sleep(0.05)
        assert len(received) == 1

        await bus.unsubscribe(sub)
        await bus.publish(Event(type="x", session_id="s", source="b"))
        await asyncio.sleep(0.05)
        assert len(received) == 1  # 取消后不再收到
        await bus.close()


class TestBackpressure:
    async def test_drop_oldest(self) -> None:
        """drop_oldest 策略：队列满丢最旧。"""
        bus = EventBus(default_queue_size=1)
        processed: list[int] = []
        slow_started = asyncio.Event()

        async def slow_handler(e: Event) -> None:
            await slow_started.wait()
            processed.append(e.sequence)

        sub = await bus.subscribe(
            "*",
            slow_handler,
            queue_size=2,
            policy=BackpressurePolicy.DROP_OLDEST,
        )
        # 快速发 5 个，handler 还没处理（卡在 wait）
        for i in range(5):
            await bus.publish(Event(type="x", session_id="s", source="b", sequence=i))

        # 队列容量 2，前 3 个应被丢
        slow_started.set()
        await asyncio.sleep(0.1)

        # 至少处理了一些（drop_oldest 保证最新两个在队列）
        assert len(processed) >= 1
        await bus.unsubscribe(sub)
        await bus.close()

    async def test_block_policy_waits(self) -> None:
        """block 策略：队列满时阻塞生产者。"""
        bus = EventBus()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            await asyncio.sleep(0.01)
            received.append(e)

        sub = await bus.subscribe(
            "*",
            handler,
            queue_size=1,
            policy=BackpressurePolicy.BLOCK,
        )
        # 发 3 个，handler 慢，应全部处理（block 等待）
        for i in range(3):
            await bus.publish(Event(type="x", session_id="s", source="b", sequence=i))
        await asyncio.sleep(0.2)

        assert len(received) == 3
        await bus.unsubscribe(sub)
        await bus.close()

    async def test_block_policy_times_out_and_drops(self) -> None:
        """block 策略有总超时：订阅者不消费时 publish 不无限挂起，超时丢事件。"""
        bus = EventBus(block_max_wait_s=0.2)
        received: list[Event] = []

        async def stalled_handler(e: Event) -> None:
            await asyncio.sleep(10)  # 模拟不消费
            received.append(e)

        sub = await bus.subscribe(
            "*",
            stalled_handler,
            queue_size=1,
            policy=BackpressurePolicy.BLOCK,
        )
        # 首事件填满队列（handler 卡住），第二个事件应在 ~0.2s 后超时丢弃而非挂起
        await bus.publish(Event(type="x", session_id="s", source="b", sequence=1))
        await asyncio.wait_for(
            bus.publish(Event(type="x", session_id="s", source="b", sequence=2)),
            timeout=2.0,
        )
        await bus.unsubscribe(sub)
        await bus.close()


class TestEventBusLifecycle:
    async def test_close_cancels_subscriptions(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        await bus.subscribe("*", handler)
        await bus.close()
        # close 后 publish 抛 RuntimeError
        with pytest.raises(RuntimeError):
            await bus.publish(Event(type="x", session_id="s", source="b"))

    async def test_subscribe_after_close_raises(self) -> None:
        bus = EventBus()
        await bus.close()
        with pytest.raises(RuntimeError):

            async def h(e: Event) -> None:
                pass

            await bus.subscribe("*", h)

    async def test_subscriber_count(self) -> None:
        bus = EventBus()

        async def h(e: Event) -> None:
            pass

        assert bus.subscriber_count == 0
        sub = await bus.subscribe("*", h)
        assert bus.subscriber_count == 1
        await bus.unsubscribe(sub)
        assert bus.subscriber_count == 0
        await bus.close()
