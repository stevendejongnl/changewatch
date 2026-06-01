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


async def test_delete_monitor_removes_monitor_config(db):
    await db.set_paused("gone", True)
    config_before = await db.get_config("gone")
    assert config_before["paused"] == 1

    await db.delete_monitor("gone")

    config_after = await db.get_config("gone")
    assert config_after["paused"] == 0  # default when row absent


async def test_init_creates_monitor_config_table(db):
    async with db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_config'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_get_config_returns_defaults_when_missing(db):
    config = await db.get_config("nonexistent")
    assert config["paused"] == 0
    assert config["changed_at"] is None


async def test_get_config_returns_row_when_exists(db):
    await db.set_paused("mon", True)
    config = await db.get_config("mon")
    assert config["monitor_name"] == "mon"
    assert config["paused"] == 1


async def test_set_paused_creates_row(db):
    await db.set_paused("mon", True)
    config = await db.get_config("mon")
    assert config["paused"] == 1


async def test_set_paused_updates_existing_row(db):
    await db.set_paused("mon", True)
    await db.set_paused("mon", False)
    config = await db.get_config("mon")
    assert config["paused"] == 0


async def test_set_changed_at_populates_field(db):
    await db.set_changed_at("mon")
    config = await db.get_config("mon")
    assert config["changed_at"] is not None


async def test_set_changed_at_updates_on_repeated_call(db):
    await db.set_changed_at("mon")
    first = (await db.get_config("mon"))["changed_at"]
    await db.set_changed_at("mon")
    second = (await db.get_config("mon"))["changed_at"]
    assert second >= first


async def test_get_all_configs_returns_keyed_dict(db):
    await db.set_paused("a", True)
    await db.set_paused("b", False)
    configs = await db.get_all_configs()
    assert "a" in configs
    assert "b" in configs
    assert configs["a"]["paused"] == 1
    assert configs["b"]["paused"] == 0


async def test_get_all_monitor_states_includes_paused_and_changed_at(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=10)
    await db.set_paused("mon", True)
    await db.set_changed_at("mon")
    states = await db.get_all_monitor_states()
    mon = next(s for s in states if s["monitor_name"] == "mon")
    assert mon["paused"] == 1
    assert mon["changed_at"] is not None


async def test_get_all_monitor_states_paused_defaults_to_zero(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=10)
    states = await db.get_all_monitor_states()
    mon = next(s for s in states if s["monitor_name"] == "mon")
    assert mon["paused"] == 0


async def test_get_avg_duration_returns_none_when_no_runs(db):
    result = await db.get_avg_duration("nonexistent")
    assert result is None


async def test_get_avg_duration_returns_rounded_integer(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=100)
    await db.record_run("mon", status="ok", last_value="2", error=None, duration_ms=200)
    result = await db.get_avg_duration("mon")
    assert result == 150


async def test_get_runs_with_logs_offset_returns_second_page(db):
    for i in range(5):
        await db.record_run("mon", status="ok", last_value=str(i), error=None, duration_ms=i * 10)
    page1 = await db.get_runs_with_logs("mon", limit=3, offset=0)
    page2 = await db.get_runs_with_logs("mon", limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2
    ids_page1 = {r["id"] for r in page1}
    ids_page2 = {r["id"] for r in page2}
    assert ids_page1.isdisjoint(ids_page2)


async def test_get_stats_returns_zero_counts_on_empty_db(db):
    stats = await db.get_stats()
    assert stats["runs"] == 0
    assert stats["run_logs"] == 0
    assert stats["state"] == 0
    assert stats["monitor_config"] == 0
    assert stats["oldest_run"] is None
    assert stats["newest_run"] is None
    assert isinstance(stats["db_size_bytes"], int)


async def test_get_stats_counts_runs_correctly(db):
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    await db.record_run("mon_a", status="ok", last_value="v2", error=None, duration_ms=20)
    stats = await db.get_stats()
    assert stats["runs"] == 2
    assert stats["oldest_run"] is not None
    assert stats["newest_run"] is not None


async def test_get_stats_counts_state_and_config(db):
    await db.set_value("mon", "42")
    await db.set_paused("mon", True)
    stats = await db.get_stats()
    assert stats["state"] == 1
    assert stats["monitor_config"] == 1


async def test_get_stats_db_size_returns_zero_on_oserror(db, monkeypatch):
    def _raise(_path):
        raise OSError("no file")
    monkeypatch.setattr("app.db.os.path.getsize", _raise)
    stats = await db.get_stats()
    assert stats["db_size_bytes"] == 0
