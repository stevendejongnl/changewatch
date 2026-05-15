# Debug / Activity Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-monitor detail page (`/monitors/{name}`) and global activity feed (`/activity`) backed by per-run log capture in a new `run_logs` SQLite table.

**Architecture:** `Runner` attaches a custom `logging.Handler` before each monitor run, buffers log lines in memory, then flushes them to `run_logs` (keyed by `run_id`) after the run completes. Three new FastAPI routes serve server-rendered Jinja2 pages and a JSON polling endpoint. Dashboard gets clickable monitor name links and an Activity header link.

**Tech Stack:** FastAPI, Jinja2, aiosqlite, Python `logging`, vanilla JS (trigger-and-poll, client-side filter)

---

## File Map

| File | Change |
|------|--------|
| `app/db.py` | Add `run_logs` table; `record_run` returns `int`; add `write_run_logs`, `get_run_logs`, `get_runs_with_logs`, `get_all_runs` |
| `app/db_test.py` | Tests for all new DB methods |
| `app/runner.py` | Add `_RunLogBuffer` handler; attach/detach around each run; write logs after run |
| `app/runner_test.py` | Tests for log capture on success and error |
| `app/main.py` | Add `GET /monitors/{name}`, `GET /activity`, `GET /api/monitors/{name}/runs` |
| `app/main_test.py` | Route tests for all three new endpoints + dashboard link presence |
| `app/templates/monitor_detail.html` | New per-monitor detail template |
| `app/templates/activity.html` | New global activity feed template |
| `app/templates/dashboard.html` | Monitor name → link; Activity link in header |

---

### Task 1: `run_logs` schema + new DB methods

**Files:**
- Modify: `app/db.py`
- Modify: `app/db_test.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `app/db_test.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/db_test.py -x -q --no-cov
```

Expected: multiple FAIL — `record_run` returns `None`, new methods don't exist.

- [ ] **Step 3: Add `run_logs` table to `db.py::init()`**

In `app/db.py`, extend the `executescript` in `init()` to add the new table after the existing `runs` table creation:

```python
await self.conn.executescript("""
    CREATE TABLE IF NOT EXISTS state (
        monitor_name TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        monitor_name TEXT NOT NULL,
        status TEXT NOT NULL,
        last_value TEXT,
        error TEXT,
        duration_ms INTEGER NOT NULL,
        ran_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS run_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES runs(id),
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        logged_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
""")
```

- [ ] **Step 4: Change `record_run` to return `int`**

Replace the existing `record_run` method in `app/db.py`:

```python
async def record_run(
    self,
    monitor_name: str,
    status: str,
    last_value: Optional[str],
    error: Optional[str],
    duration_ms: int,
) -> int:
    async with self.conn.execute(
        """INSERT INTO runs (monitor_name, status, last_value, error, duration_ms)
           VALUES (?, ?, ?, ?, ?)""",
        (monitor_name, status, last_value, error, duration_ms),
    ) as cur:
        await self.conn.commit()
        return cur.lastrowid
```

- [ ] **Step 5: Add the four new DB methods**

Add after `record_run` in `app/db.py`:

```python
async def write_run_logs(self, run_id: int, lines: list[tuple[str, str]]) -> None:
    if not lines:
        return
    await self.conn.executemany(
        "INSERT INTO run_logs (run_id, level, message) VALUES (?, ?, ?)",
        [(run_id, level, msg) for level, msg in lines],
    )
    await self.conn.commit()

async def get_run_logs(self, run_id: int) -> list[dict]:
    async with self.conn.execute(
        "SELECT level, message, logged_at FROM run_logs WHERE run_id = ? ORDER BY id",
        (run_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]

async def get_runs_with_logs(self, monitor_name: str, limit: int = 50) -> list[dict]:
    async with self.conn.execute(
        "SELECT * FROM runs WHERE monitor_name = ? ORDER BY id DESC LIMIT ?",
        (monitor_name, limit),
    ) as cur:
        run_rows = await cur.fetchall()
    runs = []
    for row in run_rows:
        run = dict(row)
        run["logs"] = await self.get_run_logs(run["id"])
        runs.append(run)
    return runs

async def get_all_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
    async with self.conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest app/db_test.py -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/db.py app/db_test.py
git commit -m "feat: add run_logs table and DB methods for log capture"
```

---

### Task 2: Log capture in `Runner`

**Files:**
- Modify: `app/runner.py`
- Modify: `app/runner_test.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `app/runner_test.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/runner_test.py::test_runner_captures_log_output app/runner_test.py::test_runner_captures_logs_on_error -x -q --no-cov
```

Expected: FAIL — `db.get_run_logs` returns `[]`.

- [ ] **Step 3: Add `_RunLogBuffer` handler and update `Runner.run`**

Replace the contents of `app/runner.py` with:

```python
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from app.db import Database
from app.helpers import Monitor, notify

if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.influx import InfluxClient


@dataclass
class RunContext:
    monitor_name: str
    logger: logging.Logger
    db: Database
    apprise: Optional["AppriseClient"] = None
    influx: Optional["InfluxClient"] = None


class _RunLogBuffer(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((record.levelname, record.getMessage()))


class Runner:
    def __init__(
        self,
        db: Database,
        browser: Any,
        apprise: Optional["AppriseClient"] = None,
        influx: Optional["InfluxClient"] = None,
    ) -> None:
        self._db = db
        self._browser = browser
        self._apprise = apprise
        self._influx = influx

    async def run(self, monitor: Monitor) -> None:
        logger = logging.getLogger(f"changewatch.{monitor.name}")
        ctx = RunContext(
            monitor_name=monitor.name,
            logger=logger,
            db=self._db,
            apprise=self._apprise,
            influx=self._influx,
        )
        log_buffer = _RunLogBuffer()
        logger.addHandler(log_buffer)
        start = time.monotonic()
        page = None
        try:
            context = await self._browser.new_context()
            page = await context.new_page()
            await monitor.fn(page, ctx)
            duration_ms = int((time.monotonic() - start) * 1000)
            last_value = await self._db.get_last_value(monitor.name)
            run_id = await self._db.record_run(
                monitor_name=monitor.name,
                status="ok",
                last_value=last_value,
                error=None,
                duration_ms=duration_ms,
            )
            await self._db.write_run_logs(run_id, log_buffer.lines)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            run_id = await self._db.record_run(
                monitor_name=monitor.name,
                status="error",
                last_value=None,
                error=str(exc),
                duration_ms=duration_ms,
            )
            await self._db.write_run_logs(run_id, log_buffer.lines)
            if self._apprise is not None and monitor.notify_channels:
                # TODO(user): customize title/body — terse vs rich, every-failure vs transition-only
                try:
                    await notify(
                        self._apprise,
                        title=f"[changewatch] {monitor.name} failed",
                        body=str(exc),
                        tags=monitor.notify_channels,
                    )
                except Exception:
                    pass
        finally:
            logger.removeHandler(log_buffer)
            if page is not None:
                await page.close()
                await page.context.close()
```

- [ ] **Step 4: Run all runner tests**

```bash
uv run pytest app/runner_test.py -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/runner.py app/runner_test.py
git commit -m "feat: capture ctx.logger output per run into run_logs table"
```

---

### Task 3: JSON API endpoint `/api/monitors/{name}/runs`

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `app/main_test.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/main_test.py::test_api_monitor_runs_returns_json_with_logs app/main_test.py::test_api_monitor_runs_empty_returns_empty_list -x -q --no-cov
```

Expected: FAIL with 404 (route doesn't exist).

- [ ] **Step 3: Add the route to `app/main.py`**

Add after the existing `/api/monitors` route:

```python
@app.get("/api/monitors/{name}/runs")
async def api_monitor_runs(name: str, db: DbDep) -> list[dict]:
    return await db.get_runs_with_logs(name)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest app/main_test.py::test_api_monitor_runs_returns_json_with_logs app/main_test.py::test_api_monitor_runs_empty_returns_empty_list -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat: add GET /api/monitors/{name}/runs JSON endpoint"
```

---

### Task 4: Per-monitor detail page

**Files:**
- Modify: `app/main.py`
- Create: `app/templates/monitor_detail.html`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `app/main_test.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/main_test.py::test_monitor_detail_returns_404_for_unknown_monitor app/main_test.py::test_monitor_detail_returns_200_for_known_monitor -x -q --no-cov
```

Expected: FAIL with 404/422 (route doesn't exist).

- [ ] **Step 3: Add the route to `app/main.py`**

Add after the `/api/monitors/{name}/runs` route:

```python
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
```

- [ ] **Step 4: Create `app/templates/monitor_detail.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ monitor_name }} — changewatch</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #0f1117; color: #e2e8f0; padding: 2rem; }
    .header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
    .breadcrumb { color: #64748b; font-size: 0.875rem; }
    .breadcrumb a { color: #93c5fd; text-decoration: none; }
    h1 { font-size: 1.25rem; color: #f8fafc; }
    .meta { color: #64748b; font-size: 0.8rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th { text-align: left; padding: 0.5rem 1rem; border-bottom: 1px solid #1e293b; color: #94a3b8; font-weight: 500; }
    td { padding: 0.6rem 1rem; border-bottom: 1px solid #1e293b; vertical-align: top; }
    tr:hover td { background: #1e293b22; }
    .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
    .ok      { background: #14532d; color: #86efac; }
    .error   { background: #7f1d1d; color: #fca5a5; }
    .changed { background: #78350f; color: #fde68a; }
    .pending { background: #1e293b; color: #94a3b8; }
    .error-msg { color: #fca5a5; font-size: 0.8rem; }
    .log-block { margin-top: 0.5rem; background: #0a0d14; border-radius: 4px; padding: 0.5rem 0.75rem; font-family: monospace; font-size: 0.72rem; line-height: 1.8; color: #94a3b8; }
    .log-line { display: flex; gap: 0.75rem; }
    .log-time { color: #475569; white-space: nowrap; }
    .log-level-INFO    { color: #60a5fa; }
    .log-level-WARNING { color: #fbbf24; }
    .log-level-ERROR   { color: #f87171; }
    .log-level-DEBUG   { color: #6b7280; }
    details summary { cursor: pointer; color: #64748b; font-size: 0.75rem; user-select: none; }
    details summary:hover { color: #94a3b8; }
    button { background: #334155; border: none; color: #e2e8f0; padding: 0.35rem 0.9rem;
             border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
    button:hover { background: #475569; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <div class="breadcrumb"><a href="/">changewatch</a> › {{ monitor_name }}</div>
      <div style="display:flex;align-items:center;gap:0.75rem;margin-top:0.35rem">
        <h1>{{ monitor_name }}</h1>
        <span class="badge {{ current_status }}">{{ current_status }}</span>
        <span class="meta">runs at {{ schedule }}</span>
      </div>
    </div>
    <button id="run-btn" onclick="runNow()">▶ Run now</button>
  </div>

  <table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Status</th>
        <th>Duration</th>
        <th>Value</th>
        <th>Error / Logs</th>
      </tr>
    </thead>
    <tbody>
      {% for run in runs %}
      <tr data-run-id="{{ run.id }}">
        <td style="color:#94a3b8;white-space:nowrap">{{ run.ran_at }}</td>
        <td><span class="badge {{ run.status }}">{{ run.status }}</span></td>
        <td style="color:#94a3b8">{{ run.duration_ms }}ms</td>
        <td>{{ run.last_value or "—" }}</td>
        <td>
          {% if run.error %}
          <div class="error-msg">{{ run.error }}</div>
          {% endif %}
          {% if run.logs %}
          <details {% if loop.first and run.status == 'error' %}open{% endif %}>
            <summary>{{ run.logs | length }} log line{{ 's' if run.logs | length != 1 }}</summary>
            <div class="log-block">
              {% for line in run.logs %}
              <div class="log-line">
                <span class="log-time">{{ line.logged_at }}</span>
                <span class="log-level-{{ line.level }}">{{ line.level }}</span>
                <span>{{ line.message }}</span>
              </div>
              {% endfor %}
            </div>
          </details>
          {% endif %}
        </td>
      </tr>
      {% else %}
      <tr><td colspan="5" style="text-align:center;color:#475569;padding:2rem">No runs yet.</td></tr>
      {% endfor %}
    </tbody>
  </table>

  <script>
    async function runNow() {
      const btn = document.getElementById('run-btn');
      btn.disabled = true;
      btn.textContent = 'Queued…';
      const latestId = parseInt(document.querySelector('tr[data-run-id]')?.dataset.runId || '0');
      try {
        const res = await fetch('/monitors/{{ monitor_name }}/run', { method: 'POST' });
        if (!res.ok) { btn.textContent = 'Error'; btn.disabled = false; return; }
        const poll = setInterval(async () => {
          try {
            const r = await fetch('/api/monitors/{{ monitor_name }}/runs');
            if (!r.ok) return;
            const runs = await r.json();
            if (runs.length > 0 && runs[0].id > latestId) {
              clearInterval(poll);
              location.reload();
            }
          } catch (_) {}
        }, 1000);
      } catch (_) {
        btn.textContent = 'Error';
        btn.disabled = false;
      }
    }
  </script>
</body>
</html>
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest app/main_test.py::test_monitor_detail_returns_404_for_unknown_monitor app/main_test.py::test_monitor_detail_returns_200_for_known_monitor -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/monitor_detail.html app/main_test.py
git commit -m "feat: add /monitors/{name} detail page with run history and log expansion"
```

---

### Task 5: Global activity feed

**Files:**
- Modify: `app/main.py`
- Create: `app/templates/activity.html`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `app/main_test.py`:

```python
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
    for i in range(3):
        await db.record_run("mon", status="ok", last_value=str(i), error=None, duration_ms=10)
    response = await client.get("/activity?offset=2&limit=2")
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/main_test.py::test_activity_returns_200 app/main_test.py::test_activity_shows_runs_from_all_monitors app/main_test.py::test_activity_offset_pagination -x -q --no-cov
```

Expected: FAIL with 404.

- [ ] **Step 3: Add the route to `app/main.py`**

Add the `limit` and `offset` query parameters. Add after the `/monitors/{name}` route:

```python
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
```

- [ ] **Step 4: Create `app/templates/activity.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Activity — changewatch</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #0f1117; color: #e2e8f0; padding: 2rem; }
    .header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
    .breadcrumb { color: #64748b; font-size: 0.875rem; }
    .breadcrumb a { color: #93c5fd; text-decoration: none; }
    h1 { font-size: 1.25rem; color: #f8fafc; }
    .filters { display: flex; gap: 0.5rem; margin-left: auto; }
    select { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; padding: 0.3rem 0.5rem; border-radius: 4px; font-size: 0.8rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th { text-align: left; padding: 0.5rem 1rem; border-bottom: 1px solid #1e293b; color: #94a3b8; font-weight: 500; }
    td { padding: 0.6rem 1rem; border-bottom: 1px solid #1e293b; vertical-align: top; }
    tr:hover td { background: #1e293b22; }
    .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
    .ok      { background: #14532d; color: #86efac; }
    .error   { background: #7f1d1d; color: #fca5a5; }
    .changed { background: #78350f; color: #fde68a; }
    .pending { background: #1e293b; color: #94a3b8; }
    .monitor-link { color: #93c5fd; text-decoration: none; font-size: 0.85rem; }
    .monitor-link:hover { text-decoration: underline; }
    .error-snippet { color: #fca5a5; font-size: 0.78rem; }
    .pagination { margin-top: 1rem; display: flex; gap: 0.75rem; justify-content: center; font-size: 0.8rem; }
    .pagination a { color: #93c5fd; text-decoration: none; }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <div class="breadcrumb"><a href="/">changewatch</a> › activity</div>
      <h1 style="margin-top:0.35rem">Activity</h1>
    </div>
    <div class="filters">
      <select id="mon-filter" onchange="applyFilters()">
        <option value="">All monitors</option>
        {% for name in monitor_names %}
        <option value="{{ name }}">{{ name }}</option>
        {% endfor %}
      </select>
      <select id="status-filter" onchange="applyFilters()">
        <option value="">All statuses</option>
        <option value="ok">ok</option>
        <option value="error">error</option>
        <option value="changed">changed</option>
      </select>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Monitor</th>
        <th>Status</th>
        <th>Value / Error</th>
        <th>Duration</th>
      </tr>
    </thead>
    <tbody id="feed">
      {% for run in runs %}
      <tr data-monitor="{{ run.monitor_name }}" data-status="{{ run.status }}">
        <td style="color:#94a3b8;white-space:nowrap">{{ run.ran_at }}</td>
        <td><a class="monitor-link" href="/monitors/{{ run.monitor_name }}">{{ run.monitor_name }}</a></td>
        <td><span class="badge {{ run.status }}">{{ run.status }}</span></td>
        <td>
          {% if run.error %}
          <span class="error-snippet">{{ run.error[:80] }}{% if run.error | length > 80 %}…{% endif %}</span>
          {% elif run.last_value %}
          <span style="color:#94a3b8;font-size:0.85rem">{{ run.last_value }}</span>
          {% else %}
          <span style="color:#475569">—</span>
          {% endif %}
        </td>
        <td style="color:#64748b">{{ run.duration_ms }}ms</td>
      </tr>
      {% else %}
      <tr><td colspan="5" style="text-align:center;color:#475569;padding:2rem">No runs yet.</td></tr>
      {% endfor %}
    </tbody>
  </table>

  <div class="pagination">
    {% if offset > 0 %}
    <a href="/activity?offset={{ [offset - limit, 0] | max }}&limit={{ limit }}">← newer</a>
    {% endif %}
    {% if has_more %}
    <a href="/activity?offset={{ offset + limit }}&limit={{ limit }}">older →</a>
    {% endif %}
  </div>

  <script>
    function applyFilters() {
      const mon = document.getElementById('mon-filter').value;
      const status = document.getElementById('status-filter').value;
      document.querySelectorAll('#feed tr[data-monitor]').forEach(row => {
        const monMatch = !mon || row.dataset.monitor === mon;
        const statusMatch = !status || row.dataset.status === status;
        row.style.display = monMatch && statusMatch ? '' : 'none';
      });
    }
  </script>
</body>
</html>
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest app/main_test.py::test_activity_returns_200 app/main_test.py::test_activity_shows_runs_from_all_monitors app/main_test.py::test_activity_offset_pagination -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/activity.html app/main_test.py
git commit -m "feat: add /activity global feed with monitor and status filters"
```

---

### Task 6: Dashboard links + full test suite

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `app/main_test.py`:

```python
async def test_dashboard_has_monitor_name_links(client, db):
    await db.record_run("my_monitor", status="ok", last_value="v", error=None, duration_ms=10)
    response = await client.get("/")
    assert 'href="/monitors/my_monitor"' in response.text


async def test_dashboard_has_activity_link(client):
    response = await client.get("/")
    assert 'href="/activity"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/main_test.py::test_dashboard_has_monitor_name_links app/main_test.py::test_dashboard_has_activity_link -x -q --no-cov
```

Expected: FAIL — links not present yet.

- [ ] **Step 3: Update `app/templates/dashboard.html`**

**Header:** add the Activity link. Find the `<div class="header">` block and add the link after `<h1>changewatch</h1>`:

```html
<div class="header">
  <h1>changewatch</h1>
  <a href="/activity" style="color:#93c5fd;text-decoration:none;font-size:0.875rem">Activity</a>
  {% if git_sync_enabled %}
  ...
```

**Monitor name cell:** change the `<td>{{ m.monitor_name }}</td>` line to:

```html
<td><a href="/monitors/{{ m.monitor_name }}" style="color:#93c5fd;text-decoration:none">{{ m.monitor_name }}</a></td>
```

- [ ] **Step 4: Run the two new tests**

```bash
uv run pytest app/main_test.py::test_dashboard_has_monitor_name_links app/main_test.py::test_dashboard_has_activity_link -x -q --no-cov
```

Expected: both pass.

- [ ] **Step 5: Run the full suite with coverage gate**

```bash
uv run pytest
```

Expected: all tests pass, 100% coverage.

- [ ] **Step 6: Commit**

```bash
git add app/templates/dashboard.html app/main_test.py
git commit -m "feat: link monitor names to detail page and add Activity nav link"
```

---

## Verification

After all tasks complete:

1. **Start local dev server:**
   ```bash
   uv run uvicorn app.main:app --reload
   ```

2. **Trigger a run and watch logs appear on the detail page:**
   ```bash
   curl -X POST http://localhost:8000/monitors/daily_weather_amsterdam/run
   ```
   Open `http://localhost:8000/monitors/daily_weather_amsterdam` — new run should appear with log lines expanded.

3. **Check the global feed:** open `http://localhost:8000/activity` — all monitors' runs visible, filter dropdowns work.

4. **Verify dashboard links:** open `http://localhost:8000` — monitor names are clickable, Activity link in header.
