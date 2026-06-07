import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock

from app.db import Database
from app.git_editor import GitEditor, SaveResult
from app.main import app, get_db, get_scheduler, get_git_sync, get_git_editor, get_browser, get_imap_watcher, _to_local, _humanize_cron, _mask_url
from app.scheduler import Scheduler


def test_to_local_returns_empty_string_for_none():
    assert _to_local(None) == ""


def test_to_local_returns_empty_string_for_empty_string():
    assert _to_local("") == ""


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


async def test_metrics_endpoint_no_influx(client):
    """Returns empty list when influx not configured."""
    resp = await client.get("/api/monitors/example_price/metrics")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_metrics_endpoint_unknown_monitor(client):
    resp = await client.get("/api/monitors/nonexistent_monitor/metrics")
    assert resp.status_code == 404


async def test_metrics_endpoint_with_influx(db, tmp_path, monkeypatch):
    import app.main as main_module
    from app.main import get_influx
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    (monitors_dir / "met_mon.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="met_mon", schedule="0 8 * * *", metric="met_mon_price", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    fake_influx = MagicMock()
    fake_influx.query = AsyncMock(return_value=[{"t": "2026-01-01T00:00:00Z", "v": 1.0}])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    app.dependency_overrides[get_influx] = lambda: fake_influx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/monitors/met_mon/metrics")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == [{"t": "2026-01-01T00:00:00Z", "v": 1.0}]
    fake_influx.query.assert_called_once_with("met_mon_price", hours=48)


async def test_api_monitor_runs_supports_offset(client, db):
    for i in range(5):
        await db.record_run("mon", status="ok", last_value=str(i), error=None, duration_ms=i * 10)
    page1 = await client.get("/api/monitors/mon/runs?limit=3&offset=0")
    page2 = await client.get("/api/monitors/mon/runs?limit=3&offset=3")
    assert page1.status_code == 200
    assert page2.status_code == 200
    ids1 = {r["id"] for r in page1.json()}
    ids2 = {r["id"] for r in page2.json()}
    assert ids1.isdisjoint(ids2)


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


async def test_dashboard_has_monitor_name_links(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    (monitors_dir / "link_mon.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="link_mon", schedule="0 8 * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    await db.record_run("link_mon", status="ok", last_value="test", error=None, duration_ms=100)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert 'href="/monitors/link_mon"' in response.text


async def test_dashboard_has_activity_link(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert 'href="/activity"' in response.text


def _make_monitor_file(monitors_dir, name):
    (monitors_dir / f"{name}.py").write_text(
        f'from app.helpers import Monitor\n'
        f'monitor = Monitor(name="{name}", schedule="0 8 * * *", notify_channels=[])\n'
        f'@monitor.check\nasync def check(page, ctx): pass\n'
    )


async def test_dashboard_hides_example_price_when_real_monitors_exist(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    _make_monitor_file(monitors_dir, "real_mon")
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    await db.record_run("example_price", status="ok", last_value="99", error=None, duration_ms=10)
    await db.record_run("real_mon", status="ok", last_value="42", error=None, duration_ms=10)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/")
    app.dependency_overrides.clear()
    assert "example_price" not in response.text
    assert "real_mon" in response.text


async def test_dashboard_shows_example_price_when_only_monitor(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    _make_monitor_file(monitors_dir, "example_price")
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    await db.record_run("example_price", status="ok", last_value="99", error=None, duration_ms=10)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/")
    app.dependency_overrides.clear()
    assert "example_price" in response.text


async def test_api_events_streams_published_event():
    import asyncio
    import json
    from app.events import EventBus, get_event_bus
    from app.main import _event_stream

    bus = EventBus()
    app.dependency_overrides[get_event_bus] = lambda: bus

    lines: list[str] = []

    async def consume():
        async for raw in _event_stream(bus):
            if raw.startswith("data:"):
                lines.append(raw)
                return

    try:
        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        await bus.publish({"monitor_name": "test_mon", "status": "ok", "ran_at": "2026-01-01 00:00:00"})
        await asyncio.wait_for(consumer, timeout=2.0)
    finally:
        app.dependency_overrides.clear()

    assert len(lines) == 1
    payload = json.loads(lines[0][len("data: "):])
    assert payload["monitor_name"] == "test_mon"
    assert payload["status"] == "ok"


async def test_api_events_endpoint_returns_streaming_response():
    from fastapi.responses import StreamingResponse
    from app.events import EventBus, get_event_bus
    from app.main import events as events_endpoint

    bus = EventBus()
    response = await events_endpoint(bus)
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    # Clean up: close the generator to avoid resource leak
    await response.body_iterator.aclose()


async def test_dashboard_has_no_meta_refresh(client):
    response = await client.get("/")
    assert 'http-equiv="refresh"' not in response.text


async def test_dashboard_has_eventsource_script(client):
    response = await client.get("/")
    assert "new EventSource('/api/events')" in response.text


async def test_dashboard_subtitle_does_not_mention_auto_refresh(client):
    response = await client.get("/")
    assert "auto-refresh" not in response.text


async def test_activity_has_eventsource_script(client):
    response = await client.get("/activity")
    assert "EventSource" in response.text


async def test_pause_monitor_sets_paused_flag(client, db):
    from unittest.mock import patch
    from app.helpers import Monitor
    mon = Monitor(name="price", schedule="*/5 * * * *", notify_channels=[])
    with patch("app.main.discover_monitors", return_value=[mon]):
        response = await client.post("/monitors/price/pause")
    assert response.status_code == 204
    config = await db.get_config("price")
    assert config["paused"] == 1


async def test_pause_monitor_returns_404_for_unknown(client):
    from unittest.mock import patch
    with patch("app.main.discover_monitors", return_value=[]):
        response = await client.post("/monitors/nonexistent/pause")
    assert response.status_code == 404


async def test_resume_monitor_clears_paused_flag(client, db):
    from unittest.mock import patch
    from app.helpers import Monitor
    mon = Monitor(name="price", schedule="*/5 * * * *", notify_channels=[])
    await db.set_paused("price", True)
    with patch("app.main.discover_monitors", return_value=[mon]):
        response = await client.post("/monitors/price/resume")
    assert response.status_code == 204
    config = await db.get_config("price")
    assert config["paused"] == 0


async def test_resume_monitor_returns_404_for_unknown(client):
    from unittest.mock import patch
    with patch("app.main.discover_monitors", return_value=[]):
        response = await client.post("/monitors/nonexistent/resume")
    assert response.status_code == 404


def test_humanize_cron_returns_human_string_for_common_pattern():
    result = _humanize_cron("*/30 * * * *")
    assert "30" in result.lower()


def test_humanize_cron_returns_input_on_invalid_cron():
    result = _humanize_cron("not-a-cron")
    assert result == "not-a-cron"


# ── Editor routes ────────────────────────────────────────────────────────────

async def test_get_monitors_new(client):
    resp = await client.get("/monitors/new")
    assert resp.status_code == 200


async def test_get_monitors_edit(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    source = 'from app.helpers import Monitor\nmonitor = Monitor(name="test", schedule="* * * * *", notify_channels=[])\n'
    (tmp_path / "test.py").write_text(source)
    resp = await client.get("/monitors/test/edit")
    assert resp.status_code == 200


async def test_get_monitors_edit_custom_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    (tmp_path / "custom.py").write_text("# custom file with no Monitor constructor\n")
    resp = await client.get("/monitors/custom/edit")
    assert resp.status_code == 200


async def test_get_monitors_edit_not_found(client):
    resp = await client.get("/monitors/nonexistent_xyz/edit")
    assert resp.status_code == 404


async def test_api_monitor_source(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    (tmp_path / "mysource.py").write_text("# hello")
    resp = await client.get("/api/monitors/mysource/source")
    assert resp.status_code == 200
    assert resp.json()["source"] == "# hello"


async def test_api_monitor_source_not_found(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    resp = await client.get("/api/monitors/no_such_mon/source")
    assert resp.status_code == 404


async def test_api_monitor_save(client):
    mock_editor = MagicMock()
    mock_editor.save = AsyncMock(return_value=SaveResult(status="ok"))
    app.dependency_overrides[get_git_editor] = lambda: mock_editor
    try:
        resp = await client.post("/api/monitors/mymon/save", json={"source": "# test"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_save_conflict(client):
    mock_editor = MagicMock()
    mock_editor.save = AsyncMock(return_value=SaveResult(status="conflict", diff="--- a\n+++ b"))
    app.dependency_overrides[get_git_editor] = lambda: mock_editor
    try:
        resp = await client.post("/api/monitors/mymon/save", json={"source": "# test"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "conflict"
        assert resp.json()["diff"] is not None
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_save_no_git_editor(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    app.dependency_overrides[get_git_editor] = lambda: None
    try:
        resp = await client.post("/api/monitors/plain/save", json={"source": "# plain"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert (tmp_path / "plain.py").read_text() == "# plain"
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_force_push_no_git_editor(client):
    app.dependency_overrides[get_git_editor] = lambda: None
    try:
        resp = await client.post("/api/monitors/mymon/force-push", json={"source": "# test"})
        assert resp.status_code == 503
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_force_push_ok(client):
    mock_editor = MagicMock()
    mock_editor._run = AsyncMock(return_value=(0, "", ""))
    app.dependency_overrides[get_git_editor] = lambda: mock_editor
    try:
        resp = await client.post("/api/monitors/mymon/force-push", json={"source": "# test"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_force_push_fails(client):
    mock_editor = MagicMock()
    mock_editor._run = AsyncMock(return_value=(1, "", "push failed"))
    app.dependency_overrides[get_git_editor] = lambda: mock_editor
    try:
        resp = await client.post("/api/monitors/mymon/force-push", json={"source": "# test"})
        assert resp.status_code == 500
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_discard_no_git_editor(client):
    app.dependency_overrides[get_git_editor] = lambda: None
    try:
        resp = await client.post("/api/monitors/mymon/discard")
        assert resp.status_code == 503
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_discard_ok(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    (tmp_path / "mymon.py").write_text("# current source")
    mock_editor = MagicMock()
    mock_editor._run = AsyncMock(side_effect=[
        (0, "", ""),           # git fetch origin
        (0, "main\n", ""),     # git branch --show-current
        (0, "", ""),           # git reset --hard origin/main
    ])
    app.dependency_overrides[get_git_editor] = lambda: mock_editor
    try:
        resp = await client.post("/api/monitors/mymon/discard")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["source"] == "# current source"
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_discard_reset_fails(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    mock_editor = MagicMock()
    mock_editor._run = AsyncMock(side_effect=[
        (0, "", ""),           # git fetch origin
        (0, "main\n", ""),     # git branch --show-current
        (1, "", "conflict"),   # git reset --hard fails
    ])
    app.dependency_overrides[get_git_editor] = lambda: mock_editor
    try:
        resp = await client.post("/api/monitors/mymon/discard")
        assert resp.status_code == 500
    finally:
        del app.dependency_overrides[get_git_editor]


async def test_api_monitor_dry_run(client):
    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_page.close = AsyncMock()
    mock_context.close = AsyncMock()

    app.dependency_overrides[get_browser] = lambda: mock_browser
    try:
        source = (
            'from app.helpers import Monitor, set_value\n'
            'monitor = Monitor(name="dry_test", schedule="* * * * *", notify_channels=[])\n'
            '@monitor.check\n'
            'async def check(page, ctx):\n'
            '    await set_value(ctx.db, "dry_test", "val")\n'
        )
        resp = await client.post("/api/monitors/dry_test/dry-run", json={"source": source})
        assert resp.status_code == 200
        assert "lines" in resp.json()
    finally:
        del app.dependency_overrides[get_browser]


async def test_api_monitor_dry_run_no_browser(client):
    app.dependency_overrides[get_browser] = lambda: None
    try:
        source = '# minimal'
        resp = await client.post("/api/monitors/dry_test/dry-run", json={"source": source})
        assert resp.status_code == 503
    finally:
        del app.dependency_overrides[get_browser]


async def test_api_monitor_dry_run_invalid_source(client):
    mock_browser = MagicMock()
    app.dependency_overrides[get_browser] = lambda: mock_browser
    try:
        resp = await client.post("/api/monitors/dry_test/dry-run", json={"source": "x = 1"})
        assert resp.status_code == 422
    finally:
        del app.dependency_overrides[get_browser]


async def test_api_monitor_dry_run_syntax_error(client):
    mock_browser = MagicMock()
    app.dependency_overrides[get_browser] = lambda: mock_browser
    try:
        resp = await client.post("/api/monitors/dry_test/dry-run", json={"source": "def ("})
        assert resp.status_code == 422
    finally:
        del app.dependency_overrides[get_browser]


async def test_api_monitor_delete_not_found(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    app.dependency_overrides[get_git_editor] = lambda: None
    app.dependency_overrides[get_scheduler] = lambda: None
    try:
        resp = await client.delete("/api/monitors/nonexistent")
        assert resp.status_code == 404
    finally:
        del app.dependency_overrides[get_git_editor]
        del app.dependency_overrides[get_scheduler]


async def test_api_monitor_delete_no_git_editor(client, tmp_path, monkeypatch, db):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    (tmp_path / "mymon.py").write_text("# monitor")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_git_editor] = lambda: None
    app.dependency_overrides[get_scheduler] = lambda: None
    try:
        resp = await client.delete("/api/monitors/mymon")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert not (tmp_path / "mymon.py").exists()
    finally:
        del app.dependency_overrides[get_db]
        del app.dependency_overrides[get_git_editor]
        del app.dependency_overrides[get_scheduler]


async def test_api_monitor_delete_with_git_editor(client, tmp_path, monkeypatch, db):
    monkeypatch.setattr("app.main.MONITORS_DIR", tmp_path)
    (tmp_path / "mymon.py").write_text("# monitor")
    mock_editor = MagicMock()
    mock_editor.delete = AsyncMock(return_value=SaveResult(status="ok"))
    mock_scheduler = MagicMock()
    mock_scheduler.reload = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_git_editor] = lambda: mock_editor
    app.dependency_overrides[get_scheduler] = lambda: mock_scheduler
    try:
        resp = await client.delete("/api/monitors/mymon")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_editor.delete.assert_called_once_with("mymon")
        mock_scheduler.reload.assert_called_once()
    finally:
        del app.dependency_overrides[get_db]
        del app.dependency_overrides[get_git_editor]
        del app.dependency_overrides[get_scheduler]


def test_mask_url_empty_string_returns_empty():
    assert _mask_url("") == ""


def test_mask_url_short_url_returns_masked():
    assert _mask_url("abc") == "****"


def test_mask_url_long_url_shows_last_8_chars():
    result = _mask_url("https://github.com/user/secret-repo")
    assert result == "****...ret-repo"


async def test_api_debug_config_returns_expected_keys(client):
    response = await client.get("/api/debug/config")
    assert response.status_code == 200
    data = response.json()
    for key in ("display_tz", "monitors_dir", "db_path", "git_repo_url",
                "git_sync_interval", "git_enabled", "channels"):
        assert key in data, f"missing key: {key}"
    assert isinstance(data["channels"], list)
    assert isinstance(data["git_enabled"], bool)


async def test_api_debug_notify_test_returns_404_for_unknown_channel(db):
    from app.main import get_apprise
    from unittest.mock import MagicMock
    from app.apprise_client import AppriseClient
    mock = MagicMock(spec=AppriseClient)
    mock.resolved_channels.return_value = {}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_apprise] = lambda: mock
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/api/debug/notify-test/nonexistent")
    app.dependency_overrides.pop(get_apprise, None)
    app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 404


async def test_api_debug_notify_test_sends_notification_and_returns_ok(db):
    from app.main import get_apprise
    from unittest.mock import MagicMock, AsyncMock
    from app.apprise_client import AppriseClient
    mock = MagicMock(spec=AppriseClient)
    mock.resolved_channels.return_value = {"telegram": "tgram://token/chat"}
    mock.notify = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_apprise] = lambda: mock
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/api/debug/notify-test/telegram")
    app.dependency_overrides.pop(get_apprise, None)
    app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock.notify.assert_called_once_with(
        title="changewatch test",
        body="Notification channel is working.",
        tags=["telegram"],
    )


async def test_api_debug_notify_test_returns_error_on_exception(db):
    from app.main import get_apprise
    from unittest.mock import MagicMock, AsyncMock
    from app.apprise_client import AppriseClient
    mock = MagicMock(spec=AppriseClient)
    mock.resolved_channels.return_value = {"telegram": "tgram://token/chat"}
    mock.notify = AsyncMock(side_effect=RuntimeError("send failed"))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_apprise] = lambda: mock
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/api/debug/notify-test/telegram")
    app.dependency_overrides.pop(get_apprise, None)
    app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200
    assert response.json() == {"status": "error", "detail": "send failed"}


async def test_api_debug_db_stats_returns_expected_keys(client, db):
    response = await client.get("/api/debug/db-stats")
    assert response.status_code == 200
    data = response.json()
    for key in ("runs", "run_logs", "state", "monitor_config", "db_size_bytes", "oldest_run", "newest_run"):
        assert key in data, f"missing key: {key}"


async def test_api_debug_db_stats_counts_reflect_data(client, db):
    await db.record_run("mon", status="ok", last_value="v", error=None, duration_ms=10)
    response = await client.get("/api/debug/db-stats")
    assert response.status_code == 200
    assert response.json()["runs"] == 1


async def test_api_debug_log_stream_returns_history_as_sse(db):
    import json as _json_mod
    import logging as _stdlib_logging
    import app.main as main_module
    from app.log_stream import AppLogBuffer
    from app.main import get_log_buf, get_db as _get_db

    buf = AppLogBuffer()
    record = _stdlib_logging.LogRecord(
        name="t", level=_stdlib_logging.INFO, pathname="", lineno=0,
        msg="hello-sse", args=(), exc_info=None,
    )
    buf.emit(record)
    history = buf.get_history()

    async def _finite(b):
        for entry in history:
            yield f"data: {_json_mod.dumps(entry)}\n\n"

    original_gen = main_module._log_stream_generator
    main_module._log_stream_generator = _finite
    app.dependency_overrides[_get_db] = lambda: db
    app.dependency_overrides[get_log_buf] = lambda: buf
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/debug/log-stream")
    app.dependency_overrides.pop(get_log_buf, None)
    app.dependency_overrides.pop(_get_db, None)
    main_module._log_stream_generator = original_gen

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "hello-sse" in response.text


async def test_log_stream_generator_yields_history_then_streams(db):
    import asyncio
    import logging as _stdlib_logging
    from app.log_stream import AppLogBuffer
    from app.main import _log_stream_generator

    buf = AppLogBuffer()
    record = _stdlib_logging.LogRecord(
        name="t", level=_stdlib_logging.INFO, pathname="", lineno=0,
        msg="gen-test", args=(), exc_info=None,
    )
    buf.emit(record)

    chunks = []
    gen = _log_stream_generator(buf)
    # skip the initial flush padding comment
    await gen.__anext__()
    # get history chunk (exhausts the for-loop)
    chunk = await gen.__anext__()
    chunks.append(chunk)

    # The generator is now past the history loop. Emit a live entry so the
    # while-loop body (subscribe + q.get + yield + finally unsubscribe) runs.
    async def _emit_after_delay():
        await asyncio.sleep(0.01)
        live_record = _stdlib_logging.LogRecord(
            name="t", level=_stdlib_logging.INFO, pathname="", lineno=0,
            msg="live-entry", args=(), exc_info=None,
        )
        buf.emit(live_record)

    task = asyncio.create_task(_emit_after_delay())
    # advance into the while loop: subscribe() runs, q.get() returns the live entry
    live_chunk = await gen.__anext__()
    chunks.append(live_chunk)
    await task
    # close generator (exercises finally: buf.unsubscribe)
    await gen.aclose()

    assert any("gen-test" in c for c in chunks)
    assert any("live-entry" in c for c in chunks)


async def test_settings_returns_200(client):
    response = await client.get("/settings")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Settings" in response.text


# ── HA sensors endpoint ──────────────────────────────────────────────────────

async def test_ha_sensors_empty_returns_zeros(client):
    response = await client.get("/ha/sensors")
    assert response.status_code == 200
    data = response.json()
    assert data["monitors_total"] == 0
    assert data["monitors_ok"] == 0
    assert data["monitors_changed"] == 0
    assert data["monitors_error"] == 0
    assert data["monitors_paused"] == 0
    assert data["monitors"] == []


async def test_ha_sensors_returns_aggregates(client, db):
    await db.record_run("mon_a", status="ok", last_value="100", error=None, duration_ms=500)
    await db.record_run("mon_b", status="changed", last_value="200", error=None, duration_ms=600)
    await db.record_run("mon_c", status="error", last_value=None, error="boom", duration_ms=100)
    response = await client.get("/ha/sensors")
    assert response.status_code == 200
    data = response.json()
    assert data["monitors_total"] == 3
    assert data["monitors_ok"] == 1
    assert data["monitors_changed"] == 1
    assert data["monitors_error"] == 1
    assert data["monitors_paused"] == 0
    names = {m["name"] for m in data["monitors"]}
    assert names == {"mon_a", "mon_b", "mon_c"}


async def test_ha_sensors_counts_paused_monitors(client, db):
    await db.record_run("paused_mon", status="ok", last_value="42", error=None, duration_ms=200)
    await db.set_paused("paused_mon", True)
    response = await client.get("/ha/sensors")
    assert response.status_code == 200
    data = response.json()
    assert data["monitors_paused"] == 1
    monitor = next(m for m in data["monitors"] if m["name"] == "paused_mon")
    assert monitor["paused"] is True


# ── Monitor.tags field ───────────────────────────────────────────────────────

def test_monitor_tags_default_empty():
    from app.helpers import Monitor
    m = Monitor(name="test", schedule="* * * * *", notify_channels=[])
    assert m.tags == []


def test_monitor_tags_can_be_set():
    from app.helpers import Monitor
    m = Monitor(name="test", schedule="* * * * *", notify_channels=[], tags=["findthatproduct"])
    assert m.tags == ["findthatproduct"]


def test_monitor_tags_multiple_values():
    from app.helpers import Monitor
    m = Monitor(name="test", schedule="* * * * *", notify_channels=[], tags=["foo", "bar"])
    assert m.tags == ["foo", "bar"]


# ── GET /api/monitors?tag= filter ───────────────────────────────────────────

async def test_api_monitors_tag_filter_returns_matching(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    (monitors_dir / "tagged_mon.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="tagged_mon", schedule="0 8 * * *", notify_channels=[], tags=["findthatproduct"])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    (monitors_dir / "other_mon.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="other_mon", schedule="0 8 * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    await db.record_run("tagged_mon", status="ok", last_value="1", error=None, duration_ms=10)
    await db.record_run("other_mon", status="ok", last_value="2", error=None, duration_ms=10)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/monitors?tag=findthatproduct")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    names = [m["monitor_name"] for m in data]
    assert "tagged_mon" in names
    assert "other_mon" not in names


async def test_api_monitors_tag_filter_no_match_returns_empty(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    (monitors_dir / "untagged_mon.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="untagged_mon", schedule="0 8 * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    await db.record_run("untagged_mon", status="ok", last_value="1", error=None, duration_ms=10)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/monitors?tag=nonexistent_tag")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == []


async def test_api_monitors_tag_filter_excludes_monitors_without_file(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    # Record a run for a monitor that has no corresponding .py file
    await db.record_run("ghost_mon", status="ok", last_value="1", error=None, duration_ms=10)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/monitors?tag=anything")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == []


async def test_api_monitors_no_tag_returns_all(db, tmp_path, monkeypatch):
    import app.main as main_module
    monitors_dir = tmp_path / "mons"
    monitors_dir.mkdir()
    monkeypatch.setattr(main_module, "MONITORS_DIR", monitors_dir)
    await db.record_run("mon_a", status="ok", last_value="1", error=None, duration_ms=10)
    await db.record_run("mon_b", status="ok", last_value="2", error=None, duration_ms=10)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scheduler] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/monitors")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    names = {m["monitor_name"] for m in response.json()}
    assert names == {"mon_a", "mon_b"}


# ── Tag management API ───────────────────────────────────────────────────────

async def test_get_api_tags_empty(client):
    response = await client.get("/api/tags")
    assert response.status_code == 200
    assert response.json() == []


async def test_post_api_tags_returns_ok(client):
    response = await client.post("/api/tags", json={"tag": "electronics"})
    assert response.status_code == 201
    assert response.json()["tag"] == "electronics"


async def test_post_api_tags_persists_to_vocab(client, db):
    await client.post("/api/tags", json={"tag": "electronics"})
    tags = await db.get_all_tags()
    assert any(t["tag"] == "electronics" for t in tags)


async def test_post_api_tags_creates_tag(client, db):
    await db.set_tags("mon_a", ["electronics"])
    response = await client.get("/api/tags")
    assert response.status_code == 200
    tags = response.json()
    assert any(t["tag"] == "electronics" for t in tags)


async def test_get_monitor_tags(client, db):
    await db.set_tags("mon_a", ["electronics", "weekly"])
    response = await client.get("/api/monitors/mon_a/tags")
    assert response.status_code == 200
    assert sorted(response.json()["tags"]) == ["electronics", "weekly"]


async def test_post_monitor_tags_sets_tags(client, db):
    response = await client.post(
        "/api/monitors/mon_a/tags", json={"tags": ["gadgets", "daily"]}
    )
    assert response.status_code == 200
    result = await db.get_tags("mon_a")
    assert sorted(result) == ["daily", "gadgets"]


async def test_delete_api_tag_removes_it(client, db):
    await db.set_tags("mon_a", ["electronics"])
    response = await client.delete("/api/tags/electronics")
    assert response.status_code == 204
    assert await db.get_tags("mon_a") == []


async def test_put_api_tag_renames_it(client, db):
    await db.set_tags("mon_a", ["electronics"])
    response = await client.put("/api/tags/electronics", json={"new_tag": "gadgets"})
    assert response.status_code == 200
    assert "gadgets" in await db.get_tags("mon_a")


# ── Favorite toggle endpoint ─────────────────────────────────────────────────

async def test_post_favorite_toggles_on(client, db, tmp_path):
    monitors_dir = tmp_path / "monitors"
    monitors_dir.mkdir(exist_ok=True)
    (monitors_dir / "mon_a.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="mon_a", schedule="*/30 * * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    import app.main as main_mod
    orig = main_mod.MONITORS_DIR
    main_mod.MONITORS_DIR = monitors_dir
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    try:
        response = await client.post("/monitors/mon_a/favorite")
        assert response.status_code == 204
        config = await db.get_config("mon_a")
        assert config["favorite"] == 1
    finally:
        main_mod.MONITORS_DIR = orig


async def test_post_favorite_toggles_off(client, db, tmp_path):
    monitors_dir = tmp_path / "monitors"
    monitors_dir.mkdir(exist_ok=True)
    (monitors_dir / "mon_a.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="mon_a", schedule="*/30 * * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    import app.main as main_mod
    orig = main_mod.MONITORS_DIR
    main_mod.MONITORS_DIR = monitors_dir
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    await db.set_favorite("mon_a", True)
    try:
        response = await client.post("/monitors/mon_a/favorite")
        assert response.status_code == 204
        config = await db.get_config("mon_a")
        assert config["favorite"] == 0
    finally:
        main_mod.MONITORS_DIR = orig


async def test_post_favorite_404_unknown(client):
    response = await client.post("/monitors/nonexistent/favorite")
    assert response.status_code == 404


async def test_monitor_edit_page_includes_tags_data(client, db, tmp_path):
    monitors_dir = tmp_path / "monitors"
    monitors_dir.mkdir(exist_ok=True)
    monitor_file = monitors_dir / "price_check.py"
    monitor_file.write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="price_check", schedule="*/30 * * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    import app.main as main_mod
    orig = main_mod.MONITORS_DIR
    main_mod.MONITORS_DIR = monitors_dir
    await db.set_tags("price_check", ["electronics"])
    try:
        response = await client.get("/monitors/price_check/edit")
        assert response.status_code == 200
        assert "electronics" in response.text
    finally:
        main_mod.MONITORS_DIR = orig


async def test_dashboard_favorites_mode_when_favorites_exist(client, db):
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    await db.record_run("mon_b", status="ok", last_value="v", error=None, duration_ms=10)
    await db.set_favorite("mon_a", True)
    response = await client.get("/")
    assert response.status_code == 200
    assert "favorites" in response.text.lower()


async def test_dashboard_shows_all_when_no_favorites(client, db):
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    await db.record_run("mon_b", status="ok", last_value="v", error=None, duration_ms=10)
    response = await client.get("/")
    assert response.status_code == 200
    assert "mon_a" in response.text
    assert "mon_b" in response.text


# ── Tag pages ────────────────────────────────────────────────────────────────

async def test_tags_overview_returns_200(client):
    response = await client.get("/tags")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_tags_overview_shows_tag_names(client, db):
    await db.set_tags("mon_a", ["electronics"])
    response = await client.get("/tags")
    assert "electronics" in response.text


async def test_tag_detail_returns_200(client, db):
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    await db.set_tags("mon_a", ["electronics"])
    response = await client.get("/tags/electronics")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_tag_detail_shows_monitors_with_tag(client, db):
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    await db.record_run("mon_b", status="ok", last_value="v", error=None, duration_ms=10)
    await db.set_tags("mon_a", ["electronics"])
    response = await client.get("/tags/electronics")
    assert "mon_a" in response.text
    assert "mon_b" not in response.text


async def test_tag_detail_404_unknown_tag(client):
    response = await client.get("/tags/nonexistent")
    assert response.status_code == 404


async def test_get_imap_watcher_returns_none_by_default():
    result = await get_imap_watcher()
    assert result is None
