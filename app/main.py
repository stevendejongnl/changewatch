import importlib.util
import json as _json
import logging as _logging
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Optional
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from cron_descriptor import get_description as _cron_get_description
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright
from pydantic import BaseModel

from app.apprise_client import AppriseClient
from app.db import Database
from app.events import EventBus, get_event_bus
from app.influx import InfluxClient
from app.log_stream import AppLogBuffer, get_log_buffer
from app.git_editor import GitEditor, SaveResult as _SaveResult
from app.git_sync import GitSync
from app.helpers import Monitor
from app.monitor_parser import generate_monitor, parse_monitor, slugify
from app.scheduler import Scheduler, discover_monitors

MONITORS_REPO_URL = os.getenv("MONITORS_REPO_URL", "")
MONITORS_REPO_TOKEN = os.getenv("MONITORS_REPO_TOKEN", "")
MONITORS_REPO_SYNC_INTERVAL = os.getenv("MONITORS_REPO_SYNC_INTERVAL", "0 * * * *")

DB_PATH = os.getenv("DB_PATH", "/data/state.db")
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "Europe/Amsterdam")

if MONITORS_REPO_URL:  # pragma: no cover
    MONITORS_DIR = Path(DB_PATH).parent / "monitors-repo"
else:
    MONITORS_DIR = Path(os.getenv("MONITORS_DIR", Path(__file__).parent.parent / "monitors"))

_db: Database | None = None
_scheduler: Scheduler | None = None
_browser = None
_git_sync: GitSync | None = None
_git_editor: GitEditor | None = None
_apprise: AppriseClient | None = None
_influx: InfluxClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover
    global _db, _scheduler, _browser, _git_sync, _git_editor, _apprise, _influx
    _db = Database(DB_PATH)
    await _db.init()
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch()

    if MONITORS_REPO_URL:
        _git_sync = GitSync(repo_url=MONITORS_REPO_URL, clone_path=MONITORS_DIR, token=MONITORS_REPO_TOKEN)
        await _git_sync.sync()
        _git_editor = GitEditor(monitors_dir=MONITORS_DIR)

    _apprise = AppriseClient()
    INFLUXDB_URL = os.getenv("INFLUXDB_URL", "")
    INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
    INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "")
    INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "")
    if INFLUXDB_URL and INFLUXDB_TOKEN and INFLUXDB_ORG and INFLUXDB_BUCKET:
        _influx = InfluxClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, bucket=INFLUXDB_BUCKET)
    _lb = get_log_buffer()
    _lb.setLevel(_logging.INFO)
    _logging.getLogger().addHandler(_lb)
    _scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db, apprise=_apprise, timezone=DISPLAY_TZ, event_bus=get_event_bus())
    await _scheduler.start(_browser)

    if MONITORS_REPO_URL and _git_sync is not None:
        async def _periodic_sync():  # pragma: no cover
            await _git_sync.sync()
            await _scheduler.reload()

        _scheduler._scheduler.add_job(
            _periodic_sync,
            CronTrigger.from_crontab(MONITORS_REPO_SYNC_INTERVAL),
            id="__git_sync__",
            name="git sync",
            misfire_grace_time=60,
            replace_existing=True,
        )

    yield

    await _scheduler.stop()
    await _browser.close()
    await _pw.stop()
    if _influx is not None:
        _influx.close()
    await _db.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["editor_version"] = int(
    (Path(__file__).parent / "static" / "editor.js").stat().st_mtime
)
templates.env.globals["chart_version"] = int(
    (Path(__file__).parent / "static" / "chart.js").stat().st_mtime
    if (Path(__file__).parent / "static" / "chart.js").exists()
    else 0
)


def _to_local(dt_str: Optional[str]) -> str:
    if not dt_str:
        return ""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo(DISPLAY_TZ)).strftime("%Y-%m-%d %H:%M:%S")


def _humanize_cron(cron: str) -> str:
    try:
        return _cron_get_description(cron).lower()
    except Exception:
        return cron


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 8:
        return "****"
    return "****..." + url[-8:]


templates.env.filters["localtime"] = _to_local
templates.env.filters["humanize_cron"] = _humanize_cron


async def get_db() -> Database:  # pragma: no cover
    assert _db is not None, "DB not initialised"
    return _db


async def get_scheduler() -> Optional[Scheduler]:  # pragma: no cover
    return _scheduler


async def get_git_sync() -> Optional[GitSync]:  # pragma: no cover
    return _git_sync


async def get_git_editor() -> GitEditor | None:  # pragma: no cover
    return _git_editor


async def get_apprise() -> AppriseClient:  # pragma: no cover
    return _apprise or AppriseClient()


async def get_influx() -> "InfluxClient | None":  # pragma: no cover
    return _influx


def get_log_buf() -> AppLogBuffer:  # pragma: no cover
    return get_log_buffer()


async def get_browser():  # pragma: no cover
    return _browser


DbDep = Annotated[Database, Depends(get_db)]
SchedulerDep = Annotated[Optional[Scheduler], Depends(get_scheduler)]
GitSyncDep = Annotated[Optional[GitSync], Depends(get_git_sync)]
GitEditorDep = Annotated[GitEditor | None, Depends(get_git_editor)]
AppraiseDep = Annotated[AppriseClient, Depends(get_apprise)]
InfluxDep = Annotated[Optional[Any], Depends(get_influx)]
LogBufDep = Annotated[AppLogBuffer, Depends(get_log_buf)]
BrowserDep = Annotated[Any, Depends(get_browser)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


class _SaveBody(BaseModel):
    source: str


class _DryRunBody(BaseModel):
    source: str


async def _load_monitor_from_source(source: str, name: str) -> Monitor:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(source)
        tmp_path = f.name
    try:
        spec = importlib.util.spec_from_file_location(name, tmp_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid source: {exc}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    monitor = getattr(module, "monitor", None)
    if monitor is None or not isinstance(monitor, Monitor):
        raise HTTPException(status_code=422, detail="No valid monitor instance found in source")
    return monitor


async def _event_stream(bus: EventBus):
    queue = bus.subscribe()
    try:
        while True:
            event = await queue.get()
            if "ran_at" in event:
                event = {**event, "ran_at": _to_local(event["ran_at"])}
            yield f"data: {_json.dumps(event)}\n\n"
    finally:
        bus.unsubscribe(queue)


@app.get("/api/events")
async def events(bus: EventBusDep):
    return StreamingResponse(
        _event_stream(bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/debug/config")
async def api_debug_config():
    return {
        "display_tz": DISPLAY_TZ,
        "monitors_dir": str(MONITORS_DIR),
        "db_path": DB_PATH,
        "git_repo_url": _mask_url(MONITORS_REPO_URL),
        "git_sync_interval": MONITORS_REPO_SYNC_INTERVAL,
        "git_enabled": bool(MONITORS_REPO_URL),
        "channels": _available_channels(),
    }


@app.post("/api/debug/notify-test/{channel}")
async def api_debug_notify_test(channel: str, apprise: AppraiseDep):
    channels = apprise.resolved_channels()
    if channel not in channels:
        raise HTTPException(status_code=404, detail=f"Channel {channel!r} not configured")
    try:
        await apprise.notify(
            title="changewatch test",
            body="Notification channel is working.",
            tags=[channel],
        )
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/api/debug/db-stats")
async def api_debug_db_stats(db: DbDep):
    return await db.get_stats()


async def _log_stream_generator(buf: AppLogBuffer):
    for entry in buf.get_history():
        yield f"data: {_json.dumps(entry)}\n\n"
    q = buf.subscribe()
    try:
        while True:
            entry = await q.get()
            yield f"data: {_json.dumps(entry)}\n\n"
    finally:
        buf.unsubscribe(q)


@app.get("/api/debug/log-stream")
async def api_debug_log_stream(buf: LogBufDep):
    return StreamingResponse(
        _log_stream_generator(buf),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {})


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: DbDep, git_sync: GitSyncDep):
    monitors = await db.get_all_monitor_states()
    known = discover_monitors(MONITORS_DIR)
    all_names = {m.name for m in known}
    metric_map = {m.name: m.metric for m in known}
    if "example_price" not in all_names and all_names:
        monitors = [m for m in monitors if m["monitor_name"] != "example_price"]
    seen = {m["monitor_name"] for m in monitors}
    for name in sorted(all_names - seen):
        monitors.append({
            "monitor_name": name,
            "status": "pending",
            "last_value": None,
            "error": None,
            "duration_ms": 0,
            "ran_at": None,
            "paused": 0,
            "changed_at": None,
        })
    for m in monitors:
        m["metric"] = metric_map.get(m["monitor_name"])
    return templates.TemplateResponse(
        request, "dashboard.html", {
            "monitors": monitors,
            "git_sync_enabled": git_sync is not None,
        }
    )


@app.get("/api/monitors")
async def api_monitors(db: DbDep):
    return await db.get_all_monitor_states()


@app.get("/api/monitors/{name}/runs")
async def api_monitor_runs(name: str, db: DbDep, limit: int = 50, offset: int = 0) -> list[dict]:
    runs = await db.get_runs_with_logs(name, limit=limit, offset=offset)
    for run in runs:
        run["ran_at"] = _to_local(run.get("ran_at"))
    return runs


@app.get("/api/monitors/{name}/metrics")
async def monitor_metrics(name: str, influx: InfluxDep, hours: int = 48):
    known = {m.name: m for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    monitor = known[name]
    if influx is None or not monitor.metric:
        return []
    return await influx.query(monitor.metric, hours=hours)


@app.post("/api/monitors/{name}/backfill")
async def monitor_backfill(name: str, db: DbDep, influx: InfluxDep):
    known = {m.name: m for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    monitor = known[name]
    if influx is None:
        raise HTTPException(status_code=503, detail="InfluxDB not configured")
    if not monitor.metric:
        raise HTTPException(status_code=400, detail=f"Monitor {name!r} has no metric field")
    from datetime import datetime, timezone
    runs = await db.get_all_runs_for_monitor(name)
    written = 0
    skipped = 0
    for run in runs:
        try:
            v = float(run["last_value"].replace("€", "").replace("$", "").replace(" ", "").replace(",", ".").strip())
            ts = int(datetime.strptime(run["ran_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except (ValueError, AttributeError):
            skipped += 1
            continue
        await influx.write(monitor.metric, v, timestamp=ts, monitor=name, source="backfill")
        written += 1
    return {"written": written, "skipped": skipped}


@app.post("/monitors/{name}/run", status_code=202)
async def run_now(name: str, db: DbDep, scheduler: SchedulerDep):
    known = {m.name for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    import asyncio
    asyncio.create_task(scheduler.trigger(name, _browser))
    return {"queued": name}


@app.post("/monitors/{name}/pause", status_code=204)
async def pause_monitor(name: str, db: DbDep, bus: EventBusDep):
    known = {m.name for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    await db.set_paused(name, True)
    await bus.publish({"event": "paused", "monitor_name": name, "paused": True})


@app.post("/monitors/{name}/resume", status_code=204)
async def resume_monitor(name: str, db: DbDep, bus: EventBusDep):
    known = {m.name for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    await db.set_paused(name, False)
    await bus.publish({"event": "paused", "monitor_name": name, "paused": False})


def _available_channels() -> list[str]:
    prefix = "APPRISE_URL_"
    return sorted(key[len(prefix):].lower() for key in os.environ if key.startswith(prefix))


@app.get("/monitors/new", response_class=HTMLResponse)
async def monitor_new(request: Request):
    return templates.TemplateResponse(
        request, "monitor_editor.html", {
            "mode": "new",
            "monitor_name": "",
            "source": "",
            "available_channels": _available_channels(),
            "selected_channels": [],
            "custom_file": False,
        }
    )


@app.get("/monitors/{name}/edit", response_class=HTMLResponse)
async def monitor_edit(name: str, request: Request):
    path = MONITORS_DIR / f"{name}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    source = path.read_text()
    config = parse_monitor(source)
    if config is None:
        custom_file = True
    else:
        custom_file = source.strip() != generate_monitor(config).strip()
    return templates.TemplateResponse(
        request, "monitor_editor.html", {
            "mode": "edit",
            "monitor_name": name,
            "source": source,
            "available_channels": _available_channels(),
            "selected_channels": config.notify_channels if config else [],
            "custom_file": custom_file,
        }
    )


@app.get("/api/monitors/{name}/source")
async def api_monitor_source(name: str):
    path = MONITORS_DIR / f"{name}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    return {"source": path.read_text()}


@app.post("/api/monitors/{name}/save")
async def api_monitor_save(name: str, body: _SaveBody, git_editor: GitEditorDep):
    slug = slugify(name)
    if git_editor is None:
        path = MONITORS_DIR / f"{slug}.py"
        path.write_text(body.source)
        return {"status": "ok"}
    result = await git_editor.save(slug, body.source)
    return {"status": result.status, "diff": result.diff, "message": result.message}


@app.post("/api/monitors/{name}/force-push")
async def api_monitor_force_push(name: str, body: _SaveBody, git_editor: GitEditorDep):
    if git_editor is None:
        raise HTTPException(status_code=503, detail="Git editor not configured")
    rc, _, stderr = await git_editor._run("git", "push", "--force-with-lease")
    if rc != 0:
        raise HTTPException(status_code=500, detail=stderr)
    return {"status": "ok"}


@app.post("/api/monitors/{name}/discard")
async def api_monitor_discard(name: str, git_editor: GitEditorDep):
    if git_editor is None:
        raise HTTPException(status_code=503, detail="Git editor not configured")
    await git_editor._run("git", "fetch", "origin")
    _, branch, _ = await git_editor._run("git", "branch", "--show-current")
    branch = branch.strip() or "main"
    rc, _, stderr = await git_editor._run("git", "reset", "--hard", f"origin/{branch}")
    if rc != 0:
        raise HTTPException(status_code=500, detail=stderr)
    path = MONITORS_DIR / f"{name}.py"
    source = path.read_text() if path.exists() else ""
    return {"status": "ok", "source": source}


@app.delete("/api/monitors/{name}")
async def api_monitor_delete(name: str, db: DbDep, git_editor: GitEditorDep, scheduler: SchedulerDep):
    path = MONITORS_DIR / f"{name}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    if git_editor is not None:
        await git_editor.delete(name)
    else:
        path.unlink(missing_ok=True)
    await db.delete_monitor(name)
    if scheduler is not None:
        await scheduler.reload()
    return {"status": "ok"}


@app.post("/api/monitors/{name}/dry-run")
async def api_monitor_dry_run(name: str, body: _DryRunBody, browser: BrowserDep, db: DbDep):
    if browser is None:
        raise HTTPException(status_code=503, detail="Browser not available")
    monitor = await _load_monitor_from_source(body.source, name)
    from app.runner import Runner
    runner = Runner(db=db, browser=browser)
    lines = await runner.run(monitor, dry_run=True)
    return {"lines": [{"level": level, "message": msg} for level, msg in lines]}


@app.get("/monitors/{name}", response_class=HTMLResponse)
async def monitor_detail(name: str, request: Request, db: DbDep):
    known = {m.name: m for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    monitor = known[name]
    runs = await db.get_runs_with_logs(name)
    current_status = runs[0]["status"] if runs else "pending"
    config = await db.get_config(name)
    avg_duration = await db.get_avg_duration(name)
    return templates.TemplateResponse(
        request, "monitor_detail.html", {
            "monitor_name": name,
            "schedule": monitor.schedule,
            "current_status": current_status,
            "runs": runs,
            "paused": config["paused"],
            "changed_at": config["changed_at"],
            "avg_duration": avg_duration,
            "metric": monitor.metric,
        }
    )


@app.get("/activity", response_class=HTMLResponse)
async def activity_feed(request: Request, db: DbDep, limit: int = 50, offset: int = 0):
    runs = await db.get_all_runs(limit=limit, offset=offset)
    monitor_names = sorted({r["monitor_name"] for r in runs})
    has_more = len(runs) == limit
    return templates.TemplateResponse(
        request, "activity.html", {
            "runs": runs,
            "monitor_names": monitor_names,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }
    )


@app.post("/sync", status_code=202)
async def sync_monitors(git_sync: GitSyncDep, scheduler: SchedulerDep):
    if git_sync is None:
        raise HTTPException(status_code=503, detail="Git sync not configured")
    await git_sync.sync()
    if scheduler is not None:
        await scheduler.reload()
    return {"synced": True}
