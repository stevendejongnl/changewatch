import asyncio
import collections
import logging
from typing import Any


def _safe_put(q: asyncio.Queue, entry: dict[str, Any]) -> None:
    try:
        q.put_nowait(entry)
    except asyncio.QueueFull:
        pass


class AppLogBuffer(logging.Handler):
    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._history: collections.deque[dict[str, Any]] = collections.deque(maxlen=maxlen)
        self._queues: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def emit(self, record: logging.LogRecord) -> None:
        entry: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "ts": record.created,
        }
        self._history.append(entry)
        loop = self._loop
        for q in list(self._queues):
            if loop and loop.is_running():
                loop.call_soon_threadsafe(_safe_put, q, entry)
            else:
                _safe_put(q, entry)

    def subscribe(self) -> asyncio.Queue:
        self._loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._history)


_buf = AppLogBuffer()


def get_log_buffer() -> AppLogBuffer:
    return _buf
