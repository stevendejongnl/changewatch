import sys
import types
import pytest
from pathlib import Path

from app.helpers import Monitor
from app.scheduler import discover_monitors, Scheduler
from app.db import Database


@pytest.fixture
def monitors_dir(tmp_path):
    return tmp_path / "monitors"


def _make_monitor_module(monitors_dir: Path, name: str, schedule: str = "*/5 * * * *") -> Path:
    monitors_dir.mkdir(exist_ok=True)
    code = f"""
from app.helpers import Monitor

monitor = Monitor(name="{name}", schedule="{schedule}", notify_channels=["telegram"])

@monitor.check
async def check(page, ctx):
    pass
"""
    path = monitors_dir / f"{name}.py"
    path.write_text(code)
    return path


def test_discover_monitors_finds_python_files(monitors_dir):
    _make_monitor_module(monitors_dir, "price_check")
    monitors = discover_monitors(monitors_dir)
    assert any(m.name == "price_check" for m in monitors)


def test_discover_monitors_returns_monitor_with_schedule(monitors_dir):
    _make_monitor_module(monitors_dir, "stock_check", schedule="0 * * * *")
    monitors = discover_monitors(monitors_dir)
    m = next(m for m in monitors if m.name == "stock_check")
    assert m.schedule == "0 * * * *"


def test_discover_monitors_ignores_non_python_files(monitors_dir):
    monitors_dir.mkdir(exist_ok=True)
    (monitors_dir / "readme.txt").write_text("not a monitor")
    monitors = discover_monitors(monitors_dir)
    assert not any(m.name == "readme" for m in monitors)


def test_discover_monitors_ignores_files_without_monitor_object(monitors_dir):
    monitors_dir.mkdir(exist_ok=True)
    (monitors_dir / "helper_funcs.py").write_text("def helper(): pass")
    monitors = discover_monitors(monitors_dir)
    assert not any(m.name == "helper_funcs" for m in monitors)


def test_discover_monitors_empty_dir_returns_empty_list(monitors_dir):
    monitors_dir.mkdir()
    monitors = discover_monitors(monitors_dir)
    assert monitors == []


def test_discover_monitors_nonexistent_dir_returns_empty_list(tmp_path):
    missing = tmp_path / "does_not_exist"
    assert discover_monitors(missing) == []


async def test_scheduler_starts_and_stops_cleanly(monitors_dir, tmp_path):
    _make_monitor_module(monitors_dir, "noop")
    db = Database(str(tmp_path / "sched.db"))
    await db.init()
    scheduler = Scheduler(monitors_dir=monitors_dir, db=db)
    await scheduler.start()
    assert scheduler.running
    await scheduler.stop()
    assert not scheduler.running
    await db.close()


async def test_scheduler_registers_one_job_per_monitor(monitors_dir, tmp_path):
    _make_monitor_module(monitors_dir, "mon_a")
    _make_monitor_module(monitors_dir, "mon_b")
    db = Database(str(tmp_path / "sched2.db"))
    await db.init()
    scheduler = Scheduler(monitors_dir=monitors_dir, db=db)
    await scheduler.start()
    jobs = scheduler.list_jobs()
    await scheduler.stop()
    await db.close()
    assert len(jobs) == 2
    job_names = {j["name"] for j in jobs}
    assert job_names == {"mon_a", "mon_b"}


def test_discover_monitors_skips_file_with_syntax_error(monitors_dir):
    monitors_dir.mkdir(exist_ok=True)
    (monitors_dir / "broken.py").write_text("this is not valid python !!!")
    monitors = discover_monitors(monitors_dir)
    assert not any(m.name == "broken" for m in monitors)


async def test_scheduler_trigger_runs_monitor(monitors_dir, tmp_path):
    from playwright.async_api import async_playwright
    _make_monitor_module(monitors_dir, "trigger_mon")
    db = Database(str(tmp_path / "trigger.db"))
    await db.init()
    scheduler = Scheduler(monitors_dir=monitors_dir, db=db)
    await scheduler.start()
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        await scheduler.trigger("trigger_mon", browser)
        await browser.close()
    runs = await db.get_recent_runs("trigger_mon")
    await scheduler.stop()
    await db.close()
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"


async def test_scheduler_trigger_raises_for_unknown_monitor(monitors_dir, tmp_path):
    import pytest
    db = Database(str(tmp_path / "trig2.db"))
    await db.init()
    monitors_dir.mkdir(exist_ok=True)
    scheduler = Scheduler(monitors_dir=monitors_dir, db=db)
    await scheduler.start()
    with pytest.raises(KeyError, match="no_such_monitor"):
        await scheduler.trigger("no_such_monitor", None)
    await scheduler.stop()
    await db.close()


def test_discover_monitors_hides_example_when_others_exist(monitors_dir):
    _make_monitor_module(monitors_dir, "example_price")
    _make_monitor_module(monitors_dir, "real_monitor")
    monitors = discover_monitors(monitors_dir)
    names = [m.name for m in monitors]
    assert "example_price" not in names
    assert "real_monitor" in names


def test_discover_monitors_shows_example_when_it_is_the_only_monitor(monitors_dir):
    _make_monitor_module(monitors_dir, "example_price")
    monitors = discover_monitors(monitors_dir)
    assert len(monitors) == 1
    assert monitors[0].name == "example_price"


async def test_scheduler_reload_adds_new_monitor(monitors_dir, tmp_path):
    _make_monitor_module(monitors_dir, "original")
    db = Database(str(tmp_path / "reload1.db"))
    await db.init()
    scheduler = Scheduler(monitors_dir=monitors_dir, db=db)
    await scheduler.start()
    assert len(scheduler.list_jobs()) == 1

    _make_monitor_module(monitors_dir, "added")
    await scheduler.reload()

    jobs = scheduler.list_jobs()
    await scheduler.stop()
    await db.close()
    assert {j["name"] for j in jobs} == {"original", "added"}


async def test_scheduler_reload_removes_deleted_monitor(monitors_dir, tmp_path):
    _make_monitor_module(monitors_dir, "keep")
    path_to_delete = _make_monitor_module(monitors_dir, "delete_me")
    db = Database(str(tmp_path / "reload2.db"))
    await db.init()
    scheduler = Scheduler(monitors_dir=monitors_dir, db=db)
    await scheduler.start()
    assert len(scheduler.list_jobs()) == 2

    path_to_delete.unlink()
    await scheduler.reload()

    jobs = scheduler.list_jobs()
    await scheduler.stop()
    await db.close()
    assert {j["name"] for j in jobs} == {"keep"}


async def test_scheduler_reload_preserves_dunder_jobs(monitors_dir, tmp_path):
    """reload() must not remove internal jobs whose IDs are prefixed with __."""
    from apscheduler.triggers.cron import CronTrigger

    _make_monitor_module(monitors_dir, "mon")
    db = Database(str(tmp_path / "reload3.db"))
    await db.init()
    scheduler = Scheduler(monitors_dir=monitors_dir, db=db)
    await scheduler.start()

    async def _noop():  # pragma: no cover
        pass

    scheduler._scheduler.add_job(
        _noop,
        CronTrigger.from_crontab("0 * * * *"),
        id="__internal__",
        name="internal",
        replace_existing=True,
    )
    assert any(j.id == "__internal__" for j in scheduler._scheduler.get_jobs())

    await scheduler.reload()

    assert any(j.id == "__internal__" for j in scheduler._scheduler.get_jobs()), (
        "reload() must not remove internal __ jobs"
    )
    await scheduler.stop()
    await db.close()
