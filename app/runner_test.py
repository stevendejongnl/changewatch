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
