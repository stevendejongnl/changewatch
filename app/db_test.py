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


async def test_record_run_returns_int(db):
    run_id = await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=100)
    assert isinstance(run_id, int)
    assert run_id > 0


async def test_write_and_get_run_logs(db):
    run_id = await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=100)
    await db.write_run_logs(run_id, [("INFO", "hello"), ("ERROR", "world")])
    logs = await db.get_run_logs(run_id)
    assert len(logs) == 2
    assert logs[0]["level"] == "INFO"
    assert logs[0]["message"] == "hello"
    assert logs[1]["level"] == "ERROR"
    assert logs[1]["message"] == "world"


async def test_write_run_logs_noop_when_empty(db):
    run_id = await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=100)
    await db.write_run_logs(run_id, [])
    assert await db.get_run_logs(run_id) == []


async def test_get_runs_with_logs_includes_log_lines(db):
    run_id = await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=100)
    await db.write_run_logs(run_id, [("INFO", "ran ok")])
    runs = await db.get_runs_with_logs("mon")
    assert len(runs) == 1
    assert runs[0]["id"] == run_id
    assert len(runs[0]["logs"]) == 1
    assert runs[0]["logs"][0]["message"] == "ran ok"


async def test_get_runs_with_logs_empty_logs(db):
    await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=100)
    runs = await db.get_runs_with_logs("mon")
    assert runs[0]["logs"] == []


async def test_get_runs_with_logs_limit(db):
    for i in range(60):
        await db.record_run("mon", status="ok", last_value=str(i), error=None, duration_ms=10)
    runs = await db.get_runs_with_logs("mon", limit=50)
    assert len(runs) == 50


async def test_get_all_runs_returns_all_monitors(db):
    await db.record_run("mon_a", status="ok", last_value="1", error=None, duration_ms=10)
    await db.record_run("mon_b", status="error", last_value=None, error="boom", duration_ms=20)
    runs = await db.get_all_runs()
    names = {r["monitor_name"] for r in runs}
    assert "mon_a" in names
    assert "mon_b" in names


async def test_get_all_runs_ordered_newest_first(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=10)
    await db.record_run("mon", status="error", last_value=None, error="e", duration_ms=20)
    runs = await db.get_all_runs()
    assert runs[0]["status"] == "error"


async def test_get_all_runs_offset(db):
    for i in range(3):
        await db.record_run("mon", status="ok", last_value=str(i), error=None, duration_ms=10)
    page1 = await db.get_all_runs(limit=2, offset=0)
    page2 = await db.get_all_runs(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1


async def test_get_run_logs_isolated_by_run_id(db):
    run_id_a = await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=10)
    run_id_b = await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=10)
    await db.write_run_logs(run_id_a, [("INFO", "from a")])
    await db.write_run_logs(run_id_b, [("INFO", "from b")])
    logs_a = await db.get_run_logs(run_id_a)
    logs_b = await db.get_run_logs(run_id_b)
    assert len(logs_a) == 1 and logs_a[0]["message"] == "from a"
    assert len(logs_b) == 1 and logs_b[0]["message"] == "from b"


async def test_delete_monitor_removes_state_runs_and_logs(db):
    await db.set_value("gone", "v")
    run_id = await db.record_run("gone", status="ok", last_value="v", error=None, duration_ms=10)
    await db.write_run_logs(run_id, [("INFO", "hello")])
    # control — should survive
    await db.set_value("keep", "v")
    await db.record_run("keep", status="ok", last_value="v", error=None, duration_ms=10)

    await db.delete_monitor("gone")

    assert await db.get_last_value("gone") is None
    assert await db.get_runs_with_logs("gone") == []
    async with db.conn.execute("SELECT id FROM run_logs WHERE run_id = ?", (run_id,)) as cur:
        assert await cur.fetchone() is None
    assert await db.get_last_value("keep") == "v"


async def test_delete_monitor_noop_when_not_exists(db):
    await db.delete_monitor("never_existed")
