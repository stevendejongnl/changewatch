import asyncio
import pytest
from playwright.async_api import async_playwright

from app.helpers import Monitor
from app.runner import Runner
from app.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "runner.db"))
    await database.init()
    yield database
    await database.close()


@pytest.fixture
async def browser():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        yield b
        await b.close()


async def test_runner_records_successful_run(db, browser):
    ran = []
    m = Monitor(name="test_mon", schedule="*/5 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        ran.append(True)

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    assert ran == [True]
    runs = await db.get_recent_runs("test_mon")
    assert runs[0]["status"] == "ok"


async def test_runner_records_error_on_exception(db, browser):
    m = Monitor(name="error_mon", schedule="*/5 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        raise ValueError("something broke")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    runs = await db.get_recent_runs("error_mon")
    assert runs[0]["status"] == "error"
    assert "something broke" in runs[0]["error"]


async def test_runner_provides_page_and_ctx(db, browser):
    received = {}
    m = Monitor(name="ctx_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        received["has_page"] = page is not None
        received["has_logger"] = ctx.logger is not None
        received["monitor_name"] = ctx.monitor_name
        received["has_db"] = ctx.db is not None

    runner = Runner(db=db, browser=browser)
    await runner.run(m)
    assert received["has_page"] is True
    assert received["has_logger"] is True
    assert received["monitor_name"] == "ctx_mon"
    assert received["has_db"] is True


async def test_runner_records_duration(db, browser):
    m = Monitor(name="slow_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        await asyncio.sleep(0.01)

    runner = Runner(db=db, browser=browser)
    await runner.run(m)
    runs = await db.get_recent_runs("slow_mon")
    assert runs[0]["duration_ms"] >= 10


async def test_runner_notifies_on_failure(db, browser):
    class StubApprise:
        def __init__(self):
            self.calls: list[dict] = []

        async def notify(self, title, body, tags=None):
            self.calls.append({"title": title, "body": body, "tags": tags})

    stub = StubApprise()
    m = Monitor(name="fail_mon", schedule="*/5 * * * *", notify_channels=["telegram"])

    @m.check
    async def check(page, ctx):
        raise RuntimeError("boom")

    runner = Runner(db=db, browser=browser, apprise=stub)
    await runner.run(m)

    runs = await db.get_recent_runs("fail_mon")
    assert runs[0]["status"] == "error"
    assert len(stub.calls) == 1
    assert "fail_mon" in stub.calls[0]["title"]
    assert stub.calls[0]["tags"] == ["telegram"]


async def test_runner_swallows_notify_exception_on_failure(db, browser):
    class BrokenApprise:
        async def notify(self, title, body, tags=None):
            raise ConnectionError("apprise unreachable")

    m = Monitor(name="nf_mon", schedule="*/5 * * * *", notify_channels=["telegram"])

    @m.check
    async def check(page, ctx):
        raise RuntimeError("original error")

    runner = Runner(db=db, browser=browser, apprise=BrokenApprise())
    await runner.run(m)  # must not raise

    runs = await db.get_recent_runs("nf_mon")
    assert runs[0]["status"] == "error"
    assert "original error" in runs[0]["error"]


async def test_runner_does_not_notify_when_no_channels(db, browser):
    class StubApprise:
        def __init__(self):
            self.calls: list[dict] = []

        async def notify(self, title, body, tags=None):  # pragma: no cover
            self.calls.append({"title": title})

    stub = StubApprise()
    m = Monitor(name="silent_mon", schedule="*/5 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        raise RuntimeError("error without channels")

    runner = Runner(db=db, browser=browser, apprise=stub)
    await runner.run(m)
    assert stub.calls == []


async def test_runner_captures_log_output(db, browser):
    m = Monitor(name="log_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        ctx.logger.info("step 1 complete")
        ctx.logger.warning("step 2 warning")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    runs = await db.get_recent_runs("log_mon")
    run_id = runs[0]["id"]
    logs = await db.get_run_logs(run_id)
    assert len(logs) == 2
    assert logs[0]["level"] == "INFO"
    assert "step 1 complete" in logs[0]["message"]
    assert logs[1]["level"] == "WARNING"
    assert "step 2 warning" in logs[1]["message"]


async def test_runner_captures_logs_on_error(db, browser):
    m = Monitor(name="err_log_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        ctx.logger.info("before crash")
        raise ValueError("crash")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    runs = await db.get_recent_runs("err_log_mon")
    run_id = runs[0]["id"]
    logs = await db.get_run_logs(run_id)
    assert len(logs) == 1
    assert "before crash" in logs[0]["message"]


async def test_runner_records_changed_status_when_value_differs(db, browser):
    from app.db import Database
    await db.set_value("chg_mon", "old_value")
    m = Monitor(name="chg_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        await ctx.db.set_value("chg_mon", "new_value")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    runs = await db.get_recent_runs("chg_mon")
    assert runs[0]["status"] == "changed"
    assert runs[0]["last_value"] == "new_value"


async def test_runner_records_ok_when_value_unchanged(db, browser):
    await db.set_value("same_mon", "same_value")
    m = Monitor(name="same_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        await ctx.db.set_value("same_mon", "same_value")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    runs = await db.get_recent_runs("same_mon")
    assert runs[0]["status"] == "ok"


async def test_runner_records_ok_on_first_run_with_no_prior_value(db, browser):
    m = Monitor(name="new_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        await ctx.db.set_value("new_mon", "first_value")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    runs = await db.get_recent_runs("new_mon")
    assert runs[0]["status"] == "ok"


async def test_runner_does_not_mutate_shared_logger_level(db, browser):
    import logging
    shared = logging.getLogger("changewatch.level_test_mon")
    shared.setLevel(logging.WARNING)
    m = Monitor(name="level_test_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        ctx.logger.info("this should be captured")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    assert shared.level == logging.WARNING  # unchanged
    runs = await db.get_recent_runs("level_test_mon")
    run_id = runs[0]["id"]
    logs = await db.get_run_logs(run_id)
    assert any("this should be captured" in l["message"] for l in logs)
