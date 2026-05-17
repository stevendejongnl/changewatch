import asyncio
import pytest
from app.events import EventBus


async def test_subscribe_returns_queue():
    bus = EventBus()
    q = bus.subscribe()
    assert isinstance(q, asyncio.Queue)


async def test_publish_puts_event_on_all_queues():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    event = {"monitor_name": "mon", "status": "ok"}
    await bus.publish(event)
    assert q1.get_nowait() == event
    assert q2.get_nowait() == event


async def test_unsubscribe_removes_queue():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    await bus.publish({"x": 1})
    assert q.empty()


async def test_publish_with_no_subscribers_does_not_raise():
    bus = EventBus()
    await bus.publish({"x": 1})  # must not raise


async def test_unsubscribe_unknown_queue_does_not_raise():
    bus = EventBus()
    q = asyncio.Queue()
    bus.unsubscribe(q)  # must not raise


def test_get_event_bus_returns_singleton():
    from app.events import get_event_bus

    bus1 = get_event_bus()
    bus2 = get_event_bus()
    assert bus1 is bus2
