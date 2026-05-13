import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

from app.db import Database
from app.scheduler import Scheduler, discover_monitors

MONITORS_DIR = Path(os.getenv("MONITORS_DIR", Path(__file__).parent.parent / "monitors"))
DB_PATH = os.getenv("DB_PATH", "/data/state.db")

_db: Database | None = None
_scheduler: Scheduler | None = None
_browser = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover
    global _db, _scheduler, _browser
    _db = Database(DB_PATH)
    await _db.init()
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch()
    _scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db)
    await _scheduler.start()
    yield
    await _scheduler.stop()
    await _browser.close()
    await _pw.stop()
    await _db.close()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


async def get_db() -> Database:  # pragma: no cover
    assert _db is not None, "DB not initialised"
    return _db


async def get_scheduler() -> Optional[Scheduler]:  # pragma: no cover
    return _scheduler


DbDep = Annotated[Database, Depends(get_db)]
SchedulerDep = Annotated[Optional[Scheduler], Depends(get_scheduler)]


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: DbDep):
    monitors = await db.get_all_monitor_states()
    known = discover_monitors(MONITORS_DIR)
    all_names = {m.name for m in known}
    # Merge: known monitors not yet run show with no state
    seen = {m["monitor_name"] for m in monitors}
    for name in sorted(all_names - seen):
        monitors.append({"monitor_name": name, "status": "pending", "last_value": None,
                         "error": None, "duration_ms": 0, "ran_at": None})
    return templates.TemplateResponse(
        request, "dashboard.html", {"monitors": monitors}
    )


@app.get("/api/monitors")
async def api_monitors(db: DbDep):
    return await db.get_all_monitor_states()


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
