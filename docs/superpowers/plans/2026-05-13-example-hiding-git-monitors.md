# Example Hiding + Git-Backed Monitors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide `example_price` from the dashboard and scheduler when real monitors exist, and enable loading monitors from a private Gitea repo with startup clone, periodic pull, and a manual "Sync monitors" button on the dashboard.

**Architecture:** A new `GitSync` class handles clone/pull by calling git as a subprocess (via `asyncio.create_subprocess_exec`, which uses separate args and is safe from shell injection); the Scheduler gains a `reload()` method that re-discovers and re-schedules monitors after a sync; `main.py` wires git sync into the lifespan and exposes a `POST /sync` endpoint using the same dependency-injection pattern as the existing scheduler.

**Tech Stack:** Python 3.12, FastAPI, APScheduler, asyncio subprocesses (git), Jinja2, pytest-asyncio.

---

## File Map

| File | Change |
|------|--------|
| `app/scheduler.py` | Filter `example_price`; add `self._browser`, `start(browser)`, `reload()` |
| `app/scheduler_test.py` | Tests for example filtering and `reload()` |
| `app/git_sync.py` | New — `GitSync` class |
| `app/git_sync_test.py` | New — tests using a local tmp git repo |
| `app/main.py` | Add `_git_sync` singleton, `get_git_sync` dep, `POST /sync`, pass `git_sync_enabled` to template, fix `scheduler.start(_browser)` |
| `app/main_test.py` | Tests for `POST /sync` (503 and 202) |
| `app/templates/dashboard.html` | Add "Sync monitors" button and inline JS |

---

## Task 1: Hide example_price when other monitors exist

**Files:**
- Modify: `app/scheduler.py` — filter in `discover_monitors`
- Modify: `app/scheduler_test.py` — two new tests

- [ ] **Step 1: Write the failing tests**

Add to `app/scheduler_test.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/scheduler_test.py::test_discover_monitors_hides_example_when_others_exist app/scheduler_test.py::test_discover_monitors_shows_example_when_it_is_the_only_monitor --no-cov -x -v
```

Expected: both FAIL (currently `example_price` is never filtered).

- [ ] **Step 3: Implement the filter in `discover_monitors`**

In `app/scheduler.py`, add two lines at the end of `discover_monitors`, just before `return monitors`:

```python
    if len(monitors) > 1:
        monitors = [m for m in monitors if m.name != "example_price"]
    return monitors
```

The full updated function:

```python
def discover_monitors(monitors_dir: Path) -> list[Monitor]:
    if not monitors_dir.is_dir():
        return []
    monitors = []
    for path in sorted(monitors_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue
        monitor = getattr(module, "monitor", None)
        if isinstance(monitor, Monitor):
            monitors.append(monitor)
    if len(monitors) > 1:
        monitors = [m for m in monitors if m.name != "example_price"]
    return monitors
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/scheduler_test.py --no-cov -x -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py app/scheduler_test.py
git commit -m "feat: hide example_price monitor when other monitors exist"
```

---

## Task 2: GitSync class

**Files:**
- Create: `app/git_sync.py`
- Create: `app/git_sync_test.py`

Note: `GitSync._run` uses `asyncio.create_subprocess_exec` which passes args as a list (not a shell string), preventing shell injection. It is the Python equivalent of Node's `execFile`.

- [ ] **Step 1: Write the failing tests**

Create `app/git_sync_test.py`:

```python
import subprocess
from pathlib import Path

import pytest

from app.git_sync import GitSync


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "monitor.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="remote", schedule="* * * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_authenticated_url_injects_token():
    gs = GitSync(repo_url="https://git.example.com/org/repo.git", clone_path=Path("/tmp/x"), token="mytoken")
    assert gs._authenticated_url() == "https://mytoken@git.example.com/org/repo.git"


def test_authenticated_url_no_token_unchanged():
    gs = GitSync(repo_url="https://git.example.com/org/repo.git", clone_path=Path("/tmp/x"), token="")
    assert gs._authenticated_url() == "https://git.example.com/org/repo.git"


async def test_sync_clones_on_first_call(source_repo, tmp_path):
    clone_path = tmp_path / "clone"
    gs = GitSync(repo_url=str(source_repo), clone_path=clone_path, token="")
    await gs.sync()
    assert (clone_path / "monitor.py").exists()


async def test_sync_pulls_on_subsequent_call(source_repo, tmp_path):
    clone_path = tmp_path / "clone"
    gs = GitSync(repo_url=str(source_repo), clone_path=clone_path, token="")
    await gs.sync()

    (source_repo / "new_monitor.py").write_text("x = 1")
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add"], cwd=source_repo, check=True, capture_output=True)

    await gs.sync()
    assert (clone_path / "new_monitor.py").exists()


async def test_sync_raises_on_invalid_repo(tmp_path):
    clone_path = tmp_path / "clone"
    gs = GitSync(repo_url=str(tmp_path / "nonexistent"), clone_path=clone_path, token="")
    with pytest.raises(RuntimeError, match="git"):
        await gs.sync()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/git_sync_test.py --no-cov -x -v
```

Expected: all FAIL with `ModuleNotFoundError: No module named 'app.git_sync'`.

- [ ] **Step 3: Create `app/git_sync.py`**

```python
import asyncio
from pathlib import Path


class GitSync:
    def __init__(self, repo_url: str, clone_path: Path, token: str) -> None:
        self._repo_url = repo_url
        self._clone_path = clone_path
        self._token = token

    def _authenticated_url(self) -> str:
        if not self._token:
            return self._repo_url
        scheme, rest = self._repo_url.split("://", 1)
        return f"{scheme}://{self._token}@{rest}"

    async def _run(self, *args: str) -> None:
        # Uses create_subprocess_exec (list args, no shell) — safe from injection
        import asyncio as _asyncio
        proc = await _asyncio.create_subprocess_exec(
            *args,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git failed: {args[0]}\n{stderr.decode()}")

    async def sync(self) -> None:
        url = self._authenticated_url()
        if not self._clone_path.exists():
            self._clone_path.parent.mkdir(parents=True, exist_ok=True)
            await self._run("git", "clone", url, str(self._clone_path))
        else:
            await self._run("git", "-C", str(self._clone_path), "pull", url)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/git_sync_test.py --no-cov -x -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add app/git_sync.py app/git_sync_test.py
git commit -m "feat: add GitSync class for cloning and pulling monitor repos"
```

---

## Task 3: Scheduler browser injection + reload()

The existing `start()` creates `Runner(browser=None)` which crashes on any cron-fired monitor execution. Fix by accepting `browser` in `start()`, storing it, and using it in `reload()`.

**Files:**
- Modify: `app/scheduler.py` — add `self._browser`, update `start(browser=None)`, add `reload()`
- Modify: `app/scheduler_test.py` — two new tests for `reload()`

- [ ] **Step 1: Write the failing tests**

Add to `app/scheduler_test.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/scheduler_test.py::test_scheduler_reload_adds_new_monitor app/scheduler_test.py::test_scheduler_reload_removes_deleted_monitor --no-cov -x -v
```

Expected: both FAIL with `AttributeError: 'Scheduler' object has no attribute 'reload'`.

- [ ] **Step 3: Update `Scheduler` in `app/scheduler.py`**

Full replacement of the `Scheduler` class:

```python
class Scheduler:
    def __init__(self, monitors_dir: Path, db: Database) -> None:
        self._monitors_dir = monitors_dir
        self._db = db
        self._browser: Any = None
        self._scheduler = AsyncIOScheduler()
        self._monitors: list[Monitor] = []

    @property
    def running(self) -> bool:
        return self._scheduler.running

    async def start(self, browser: Any = None) -> None:
        self._browser = browser
        self._monitors = discover_monitors(self._monitors_dir)
        runner = Runner(db=self._db, browser=self._browser)
        for monitor in self._monitors:
            self._scheduler.add_job(
                runner.run,
                CronTrigger.from_crontab(monitor.schedule),
                args=[monitor],
                id=monitor.name,
                name=monitor.name,
                misfire_grace_time=60,
                replace_existing=True,
            )
        self._scheduler.start()

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        await asyncio.sleep(0)

    def list_jobs(self) -> list[dict[str, Any]]:
        return [{"name": job.name, "id": job.id} for job in self._scheduler.get_jobs()]

    async def reload(self) -> None:
        new_monitors = discover_monitors(self._monitors_dir)
        new_ids = {m.name for m in new_monitors}
        old_ids = {job.id for job in self._scheduler.get_jobs()}
        runner = Runner(db=self._db, browser=self._browser)
        for job_id in old_ids - new_ids:
            self._scheduler.remove_job(job_id)
        for monitor in new_monitors:
            self._scheduler.add_job(
                runner.run,
                CronTrigger.from_crontab(monitor.schedule),
                args=[monitor],
                id=monitor.name,
                name=monitor.name,
                misfire_grace_time=60,
                replace_existing=True,
            )
        self._monitors = new_monitors

    async def trigger(self, monitor_name: str, browser: Any) -> None:
        monitor = next((m for m in self._monitors if m.name == monitor_name), None)
        if monitor is None:
            raise KeyError(f"No monitor named {monitor_name!r}")
        runner = Runner(db=self._db, browser=browser)
        await runner.run(monitor)
```

- [ ] **Step 4: Run all scheduler tests**

```bash
uv run pytest app/scheduler_test.py --no-cov -x -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py app/scheduler_test.py
git commit -m "feat: add Scheduler.reload() and fix browser injection in start()"
```

---

## Task 4: POST /sync endpoint and lifespan wiring

**Files:**
- Modify: `app/main.py` — `_git_sync` singleton, `get_git_sync` dep, `POST /sync`, pass `git_sync_enabled` to dashboard, update `scheduler.start(_browser)`
- Modify: `app/main_test.py` — tests for `POST /sync`

New env vars:
- `MONITORS_REPO_URL` — if set, enables git sync
- `MONITORS_REPO_TOKEN` — HTTP token for Gitea auth
- `MONITORS_REPO_SYNC_INTERVAL` — cron string, default `0 * * * *` (hourly)

When `MONITORS_REPO_URL` is set, `MONITORS_DIR` is overridden to `Path(DB_PATH).parent / "monitors-repo"`.

- [ ] **Step 1: Write the failing tests**

Update the import line in `app/main_test.py`:
```python
from app.main import app, get_db, get_scheduler, get_git_sync
```

Add these tests to `app/main_test.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/main_test.py::test_sync_returns_503_when_git_sync_not_configured app/main_test.py::test_sync_returns_202_when_configured --no-cov -x -v
```

Expected: both FAIL with `ImportError: cannot import name 'get_git_sync'`.

- [ ] **Step 3: Replace `app/main.py`**

```python
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

from app.db import Database
from app.git_sync import GitSync
from app.scheduler import Scheduler, discover_monitors

MONITORS_REPO_URL = os.getenv("MONITORS_REPO_URL", "")
MONITORS_REPO_TOKEN = os.getenv("MONITORS_REPO_TOKEN", "")
MONITORS_REPO_SYNC_INTERVAL = os.getenv("MONITORS_REPO_SYNC_INTERVAL", "0 * * * *")

DB_PATH = os.getenv("DB_PATH", "/data/state.db")

if MONITORS_REPO_URL:
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

    _scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db)
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


@app.post("/sync", status_code=202)
async def sync_monitors(git_sync: GitSyncDep, scheduler: SchedulerDep):
    if git_sync is None:
        raise HTTPException(status_code=503, detail="Git sync not configured")
    await git_sync.sync()
    if scheduler is not None:
        await scheduler.reload()
    return {"synced": True}
```

- [ ] **Step 4: Run all main tests**

```bash
uv run pytest app/main_test.py --no-cov -x -v
```

Expected: all pass. The existing `test_run_now_queues_known_monitor` uses the real `monitors/` dir which has only `example_price.py` — still discovered (only monitor, filter doesn't apply).

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat: add POST /sync endpoint and git sync lifespan wiring"
```

---

## Task 5: Dashboard sync button

**Files:**
- Modify: `app/templates/dashboard.html`

- [ ] **Step 1: Replace `app/templates/dashboard.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>changewatch</title>
  <meta http-equiv="refresh" content="30">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #0f1117; color: #e2e8f0; padding: 2rem; }
    .header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
    h1 { font-size: 1.5rem; color: #f8fafc; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th { text-align: left; padding: 0.5rem 1rem; border-bottom: 1px solid #1e293b; color: #94a3b8; font-weight: 500; }
    td { padding: 0.6rem 1rem; border-bottom: 1px solid #1e293b; vertical-align: top; }
    tr:hover td { background: #1e293b; }
    .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
    .ok      { background: #14532d; color: #86efac; }
    .error   { background: #7f1d1d; color: #fca5a5; }
    .changed { background: #78350f; color: #fde68a; }
    .pending { background: #1e293b; color: #94a3b8; }
    .error-msg { color: #fca5a5; font-size: 0.75rem; max-width: 30ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    form { display: inline; }
    button { background: #334155; border: none; color: #e2e8f0; padding: 0.25rem 0.75rem;
             border-radius: 4px; cursor: pointer; font-size: 0.75rem; }
    button:hover { background: #475569; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #sync-error { color: #fca5a5; font-size: 0.75rem; }
  </style>
</head>
<body>
  <div class="header">
    <h1>changewatch</h1>
    {% if git_sync_enabled %}
    <button id="sync-btn" onclick="syncMonitors()">Sync monitors</button>
    <span id="sync-error"></span>
    {% endif %}
  </div>
  <table>
    <thead>
      <tr>
        <th>Monitor</th>
        <th>Status</th>
        <th>Last value</th>
        <th>Last run</th>
        <th>Duration</th>
        <th>Error</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for m in monitors %}
      <tr>
        <td>{{ m.monitor_name }}</td>
        <td><span class="badge {{ m.status }}">{{ m.status }}</span></td>
        <td>{{ m.last_value or "—" }}</td>
        <td>{{ m.ran_at or "never" }}</td>
        <td>{{ m.duration_ms }}ms</td>
        <td>
          {% if m.error %}
          <span class="error-msg" title="{{ m.error }}">{{ m.error }}</span>
          {% endif %}
        </td>
        <td>
          <form method="post" action="/monitors/{{ m.monitor_name }}/run">
            <button type="submit">Run now</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="7" style="text-align:center;color:#475569;padding:2rem">No monitors yet.</td></tr>
      {% endfor %}
    </tbody>
  </table>
  {% if git_sync_enabled %}
  <script>
    async function syncMonitors() {
      const btn = document.getElementById('sync-btn');
      const err = document.getElementById('sync-error');
      btn.disabled = true;
      btn.textContent = 'Syncing…';
      err.textContent = '';
      try {
        const res = await fetch('/sync', { method: 'POST' });
        if (res.ok) {
          location.reload();
        } else {
          const data = await res.json().catch(() => ({}));
          err.textContent = data.detail || 'Sync failed';
          btn.disabled = false;
          btn.textContent = 'Sync monitors';
        }
      } catch (e) {
        err.textContent = 'Network error';
        btn.disabled = false;
        btn.textContent = 'Sync monitors';
      }
    }
  </script>
  {% endif %}
</body>
</html>
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest --no-cov -x -v
```

Expected: all tests pass.

- [ ] **Step 3: Run with coverage**

```bash
uv run pytest
```

Expected: 100% coverage. If `_periodic_sync` inner function in `main.py` causes a miss, it already has `# pragma: no cover` in Task 4's code.

- [ ] **Step 4: Commit**

```bash
git add app/templates/dashboard.html
git commit -m "feat: add sync monitors button to dashboard"
```

---

## Verification

1. `uv run pytest` — full suite, 100% coverage.
2. `uv run uvicorn app.main:app --reload` — open `http://localhost:8000`. Only `example_price` in local `monitors/` — it appears (single monitor case).
3. Create `monitors/real_monitor.py` with a valid `Monitor`, restart — `example_price` disappears, only `real_monitor` shows.
4. Set `MONITORS_REPO_URL=https://git.madebysteven.nl/steven/monitors.git` and `MONITORS_REPO_TOKEN=<token>`, restart — "Sync monitors" button appears in the header; clicking it triggers a pull and reloads the page.
