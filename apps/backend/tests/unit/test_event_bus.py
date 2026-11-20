"""进程内事件总线测试（E1-T09-UT-001…003 / IT-001）。"""

from __future__ import annotations

import pytest

from core.errors import StartupError
from core.events.bus import EventBus
from core.events.model import Event
from core.events.registry import EventRegistry


async def test_publish_delivers_to_subscriber() -> None:
    registry = EventRegistry()
    bus = EventBus(registry)
    received: list[Event] = []

    registry.register("task.created", received.append, consumer_id="collector")
    results = await bus.publish(Event.create("task.created", {"task_id": "t1"}))

    assert [result.status for result in results] == ["delivered"]
    assert received[0].payload == {"task_id": "t1"}


async def test_only_matching_event_type_is_delivered() -> None:
    registry = EventRegistry()
    bus = EventBus(registry)
    received: list[Event] = []

    registry.register("task.created", received.append, consumer_id="collector")
    results = await bus.publish(Event.create("task.updated", {}))

    assert results == ()
    assert received == []


async def test_duplicate_events_are_delivered_each_time() -> None:
    registry = EventRegistry()
    bus = EventBus(registry)
    received: list[Event] = []

    registry.register("task.created", received.append, consumer_id="collector")
    event = Event.create("task.created", {})
    await bus.publish(event)
    await bus.publish(event)

    # 总线不做去重；重复投递由 Inbox 保证幂等
    assert len(received) == 2


async def test_failure_does_not_block_other_subscribers() -> None:
    registry = EventRegistry()
    bus = EventBus(registry)
    received: list[Event] = []

    def broken(_event: Event) -> None:
        raise RuntimeError("handler boom")

    registry.register("task.created", broken, consumer_id="broken")
    registry.register("task.created", received.append, consumer_id="healthy")

    results = await bus.publish(Event.create("task.created", {}))

    assert [(result.consumer_id, result.status) for result in results] == [
        ("broken", "failed"),
        ("healthy", "delivered"),
    ]
    assert len(received) == 1


def test_duplicate_consumer_id_is_rejected() -> None:
    registry = EventRegistry()
    registry.register("task.created", lambda _event: None, consumer_id="same")

    with pytest.raises(StartupError):
        registry.register("task.created", lambda _event: None, consumer_id="same")
