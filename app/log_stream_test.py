import asyncio
import logging

from app.log_stream import AppLogBuffer, get_log_buffer


def _make_record(msg: str, level: str = "INFO") -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=getattr(logging, level),
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    return record


def test_emit_stores_in_history():
    buf = AppLogBuffer(maxlen=10)
    buf.emit(_make_record("hello"))
    history = buf.get_history()
    assert len(history) == 1
    assert history[0]["message"] == "hello"
    assert history[0]["level"] == "INFO"
    assert history[0]["logger"] == "test.logger"
    assert isinstance(history[0]["ts"], float)


def test_history_respects_maxlen():
    buf = AppLogBuffer(maxlen=3)
    for i in range(5):
        buf.emit(_make_record(f"msg{i}"))
    history = buf.get_history()
    assert len(history) == 3
    assert history[0]["message"] == "msg2"
    assert history[-1]["message"] == "msg4"


def test_get_history_returns_snapshot():
    buf = AppLogBuffer()
    buf.emit(_make_record("a"))
    snapshot = buf.get_history()
    buf.emit(_make_record("b"))
    assert len(snapshot) == 1  # snapshot not affected by later emit


async def test_subscribe_receives_emitted_record():
    buf = AppLogBuffer()
    q = buf.subscribe()
    buf.emit(_make_record("streamed"))
    await asyncio.sleep(0)  # yield so call_soon_threadsafe executes
    entry = await asyncio.wait_for(q.get(), timeout=1.0)
    assert entry["message"] == "streamed"


async def test_unsubscribe_stops_delivery():
    buf = AppLogBuffer()
    q = buf.subscribe()
    buf.unsubscribe(q)
    buf.emit(_make_record("after-unsub"))
    assert q.empty()


def test_get_log_buffer_returns_singleton():
    a = get_log_buffer()
    b = get_log_buffer()
    assert a is b


async def test_emit_silently_drops_when_subscriber_queue_full():
    from app.log_stream import _safe_put
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    await q.put({"level": "INFO", "logger": "x", "message": "first", "ts": 0.0})
    # queue is now full — _safe_put must not raise
    _safe_put(q, {"level": "INFO", "logger": "x", "message": "overflow", "ts": 1.0})
    assert q.qsize() == 1  # overflow was silently dropped


def test_emit_calls_safe_put_directly_when_loop_not_set():
    """Cover the else branch (line 34) in emit() when loop is not set."""
    buf = AppLogBuffer()
    # Don't call subscribe(), so _loop remains None
    q = asyncio.Queue()
    buf._queues.add(q)
    buf.emit(_make_record("test"))
    # Message was put directly into queue (else branch at line 34)
    assert q.qsize() == 1
    entry = q.get_nowait()
    assert entry["message"] == "test"
