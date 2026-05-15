import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

from app.apprise_client import AppriseClient
from app.db import Database
from app.git_sync import GitSync
from app.scheduler import Scheduler, discover_monitors

MONITORS_REPO_URL = os.getenv("MONITORS_REPO_URL", "")
MONITORS_REPO_TOKEN = os.getenv("MONITORS_REPO_TOKEN", "")
MONITORS_REPO_SYNC_INTERVAL = os.getenv("MONITORS_REPO_SYNC_INTERVAL", "0 * * * *")

DB_PATH = os.getenv("DB_PATH", "/data/state.db")
DISPLAY_TZ = os.getenv("TZ", "Europe/Amsterdam")

if MONITORS_REPO_URL:  # pragma: no cover
    MONITORS_DIR = Path(DB_PATH).parent / "monitors-repo"
else:
    MONITORS_DIR = Path(os.getenv("MONITORS_DIR", Path(__file__).parent.parent / "monitors"))

_db: Database | None = None
_scheduler: Scheduler | None = None
_browser = None
_git_sync: GitSync | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover
    global _db, _scheduler, _browser, _git_sync
    _db = Database(DB_PATH)
    await _db.init()
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch()

    if MONITORS_REPO_URL:
        _git_sync = GitSync(repo_url=MONITORS_REPO_URL, clone_path=MONITORS_DIR, token=MONITORS_REPO_TOKEN)
        await _git_sync.sync()

    _scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db, apprise=AppriseClient())
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
    await _db.close()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _to_local(dt_str: Optional[str]) -> str:
    if not dt_str:
        return ""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo(DISPLAY_TZ)).strftime("%Y-%m-%d %H:%M:%S")


templates.env.filters["localtime"] = _to_local


async def get_db() -> Database:  # pragma: no cover
    assert _db is not None, "DB not initialised"
    return _db


async def get_scheduler() -> Optional[Scheduler]:  # pragma: no cover
    return _scheduler


async def get_git_sync() -> Optional[GitSync]:  # pragma: no cover
    return _git_sync


DbDep = Annotated[Database, Depends(get_db)]
SchedulerDep = Annotated[Optional[Scheduler], Depends(get_scheduler)]
GitSyncDep = Annotated[Optional[GitSync], Depends(get_git_sync)]


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: DbDep, git_sync: GitSyncDep):
    monitors = await db.get_all_monitor_states()
    known = discover_monitors(MONITORS_DIR)
    all_names = {m.name for m in known}
    if "example_price" not in all_names and all_names:
        monitors = [m for m in monitors if m["monitor_name"] != "example_price"]
    seen = {m["monitor_name"] for m in monitors}
    for name in sorted(all_names - seen):
        monitors.append({"monitor_name": name, "status": "pending", "last_value": None,
                         "error": None, "duration_ms": 0, "ran_at": None})
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
async def api_monitor_runs(name: str, db: DbDep) -> list[dict]:
    return await db.get_runs_with_logs(name)


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


@app.get("/monitors/{name}", response_class=HTMLResponse)
async def monitor_detail(name: str, request: Request, db: DbDep):
    known = {m.name: m for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    monitor = known[name]
    runs = await db.get_runs_with_logs(name)
    current_status = runs[0]["status"] if runs else "pending"
    return templates.TemplateResponse(
        request, "monitor_detail.html", {
            "monitor_name": name,
            "schedule": monitor.schedule,
            "current_status": current_status,
            "runs": runs,
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
