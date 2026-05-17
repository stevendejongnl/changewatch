import asyncio


class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        return q

    async def publish(self, event: dict) -> None:
        for q in list(self._queues):
            await q.put(event)

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
