import pytest
from httpx import AsyncClient, ASGITransport

from app.db import Database
from app.main import app, get_db, get_scheduler, get_git_sync
from app.scheduler import Scheduler


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "main_test.db"))
    await database.init()
    yield database
    await database.close()


@pytest.fixture
async def scheduler(db, tmp_path):
    monitors_dir = tmp_path / "monitors"
    monitors_dir.mkdir()
    sched = Scheduler(monitors_dir=monitors_dir, db=db)
    await sched.start()
    yield sched
    await sched.stop()


@pytest.fixture
async def client(db, scheduler):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: scheduler
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_dashboard_returns_200(client):
    response = await client.get("/")
    assert response.status_code == 200


async def test_dashboard_renders_html(client):
    response = await client.get("/")
    assert "text/html" in response.headers["content-type"]


async def test_dashboard_shows_no_monitors_when_empty(client):
    response = await client.get("/")
    assert response.status_code == 200


async def test_activity_returns_200(client):
    response = await client.get("/activity")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_activity_shows_runs_from_all_monitors(client, db):
    await db.record_run("mon_a", status="ok", last_value="1", error=None, duration_ms=10)
    await db.record_run("mon_b", status="error", last_value=None, error="boom", duration_ms=20)
    response = await client.get("/activity")
    assert "mon_a" in response.text
    assert "mon_b" in response.text


async def test_activity_offset_pagination(client, db):
    # Insert 4 runs with distinct monitor names so we can verify the slice.
    # ORDER BY id DESC means newest first: mon_d, mon_c, mon_b, mon_a
    for name in ["mon_a", "mon_b", "mon_c", "mon_d"]:
        await db.record_run(name, status="ok", last_value=None, error=None, duration_ms=10)
    response = await client.get("/activity?offset=2&limit=2")
    assert response.status_code == 200
    # offset=2 skips mon_d and mon_c (the two most-recent runs),
    # so the response should contain mon_b and mon_a
    assert "mon_b" in response.text
    assert "mon_a" in response.text
    # The first-page runs should NOT appear on this offset page
    assert "mon_d" not in response.text
    assert "mon_c" not in response.text


async def test_api_monitors_returns_json(client, db):
    await db.record_run("price_check", status="ok", last_value="42.50", error=None, duration_ms=200)
    response = await client.get("/api/monitors")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["monitor_name"] == "price_check"
    assert data[0]["status"] == "ok"


async def test_api_monitors_empty_returns_empty_list(client):
    response = await client.get("/api/monitors")
    assert response.status_code == 200
    assert response.json() == []


async def test_run_now_queues_known_monitor(db, tmp_path):
    import asyncio
    from app.helpers import Monitor

    monitors_dir = tmp_path / "monitors"
    monitors_dir.mkdir()
    sched = Scheduler(monitors_dir=monitors_dir, db=db)
    await sched.start()

    m = Monitor(name="example_price", schedule="*/5 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        pass

    await check(None, None)
    sched._monitors.append(m)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: sched

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/monitors/example_price/run")

    await asyncio.sleep(0.05)
    app.dependency_overrides.clear()
    await sched.stop()

    assert response.status_code == 202


async def test_run_now_returns_404_for_unknown_monitor(client):
    response = await client.post("/monitors/does_not_exist_xyz/run")
    assert response.status_code == 404


async def test_run_now_returns_503_when_scheduler_not_ready(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/monitors/example_price/run")
    app.dependency_overrides.clear()
    assert response.status_code == 503


async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_sync_returns_503_when_git_sync_not_configured(db, scheduler):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: scheduler
    app.dependency_overrides[get_git_sync] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/sync")
    app.dependency_overrides.clear()
    assert response.status_code == 503


async def test_sync_returns_202_when_configured(db, scheduler):
    from unittest.mock import AsyncMock
    mock_gs = AsyncMock()
    mock_gs.sync = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: scheduler
    app.dependency_overrides[get_git_sync] = lambda: mock_gs
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/sync")
    app.dependency_overrides.clear()
    assert response.status_code == 202
    assert response.json() == {"synced": True}
    mock_gs.sync.assert_called_once()


async def test_api_monitor_runs_returns_json_with_logs(client, db):
    run_id = await db.record_run("weather", status="ok", last_value="14°C", error=None, duration_ms=500)
    await db.write_run_logs(run_id, [("INFO", "fetched ok")])
    response = await client.get("/api/monitors/weather/runs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["status"] == "ok"
    assert data[0]["logs"][0]["message"] == "fetched ok"


async def test_api_monitor_runs_empty_returns_empty_list(client):
    response = await client.get("/api/monitors/no_runs_here/runs")
    assert response.status_code == 200
    assert response.json() == []


async def test_monitor_detail_returns_404_for_unknown_monitor(client):
    response = await client.get("/monitors/does_not_exist_xyz")
    assert response.status_code == 404


async def test_monitor_detail_returns_200_for_known_monitor(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    (monitors_dir / "my_mon.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="my_mon", schedule="0 8 * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/monitors/my_mon")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "my_mon" in response.text
    assert "0 8 * * *" in response.text
