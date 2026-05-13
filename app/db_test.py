import pytest
import aiosqlite
from pathlib import Path

from app.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


async def test_init_creates_state_table(db):
    async with db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='state'") as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_init_creates_runs_table(db):
    async with db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'") as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_get_last_value_returns_none_when_missing(db):
    result = await db.get_last_value("nonexistent_monitor")
    assert result is None


async def test_set_value_stores_and_retrieves(db):
    await db.set_value("price_monitor", "42.50")
    result = await db.get_last_value("price_monitor")
    assert result == "42.50"


async def test_set_value_upserts_on_second_call(db):
    await db.set_value("price_monitor", "42.50")
    await db.set_value("price_monitor", "39.99")
    result = await db.get_last_value("price_monitor")
    assert result == "39.99"


async def test_record_run_stores_a_row(db):
    await db.record_run("my_monitor", status="ok", last_value="99", error=None, duration_ms=123)
    async with db.conn.execute("SELECT monitor_name, status FROM runs") as cur:
        row = await cur.fetchone()
    assert row["monitor_name"] == "my_monitor"
    assert row["status"] == "ok"


async def test_get_recent_runs_returns_latest_first(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=10)
    await db.record_run("mon", status="error", last_value=None, error="timeout", duration_ms=0)
    runs = await db.get_recent_runs("mon", limit=5)
    assert runs[0]["status"] == "error"
    assert runs[1]["status"] == "ok"


async def test_get_all_monitor_states_returns_latest_per_monitor(db):
    await db.record_run("a", status="ok", last_value="1", error=None, duration_ms=10)
    await db.record_run("b", status="error", last_value=None, error="fail", duration_ms=0)
    states = await db.get_all_monitor_states()
    names = {s["monitor_name"] for s in states}
    assert names == {"a", "b"}
