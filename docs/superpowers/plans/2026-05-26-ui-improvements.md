# UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pause/resume, in-place SSE dashboard updates, avg duration + changed_at metrics, human-readable cron labels, run history pagination, and remove dead nav UI.

**Architecture:** All persistent state (paused flag, changed_at) lives in a new `monitor_config` SQLite table. The SSE event payload gains an `event` type field so the dashboard JS can perform surgical DOM updates instead of full reloads. Pause check is a scheduler-side wrapper; manual trigger bypasses it.

**Tech Stack:** Python/FastAPI, aiosqlite, APScheduler, Jinja2, cron-descriptor, vanilla JS

---

## File Map

| File | Change |
|------|--------|
| `app/db.py` | Add `monitor_config` table; add `set_paused`, `set_changed_at`, `get_config`, `get_all_configs`, `get_avg_duration`; add `offset` param to `get_runs_with_logs`; update `get_all_monitor_states` to LEFT JOIN `monitor_config` |
| `app/db_test.py` | Tests for all new DB methods |
| `app/runner.py` | Add `"event": "run"` field to SSE publish dict; call `set_changed_at` on value change |
| `app/runner_test.py` | Test `event` field + `set_changed_at` call |
| `app/scheduler.py` | Extract `_make_job_fn(runner, monitor)` wrapping run with pause check; use in `start()` and `reload()` |
| `app/scheduler_test.py` | Test pause check skips run; test normal run still fires |
| `app/main.py` | Add `_humanize_cron` fn + Jinja filter; add pause/resume endpoints; update `dashboard`, `monitor_detail`, `api_monitor_runs` routes |
| `app/main_test.py` | Tests for pause/resume endpoints; `_humanize_cron`; offset param on runs endpoint |
| `app/templates/base.html` | Remove disabled sign-out nav button |
| `app/templates/dashboard.html` | Add `data-monitor` attr; replace `location.reload()` SSE handler with `updateCard`/`updatePauseChip`; paused chip; cron human label |
| `app/templates/monitor_detail.html` | Wire pause/resume button; add avg_duration tile + changed_at sub-line; cron human label; Load More button |
| `pyproject.toml` | Add `cron-descriptor` dependency |

---

## Task 1: monitor_config DB table + pause/changed_at/config methods

**Files:**
- Modify: `app/db.py`
- Modify: `app/db_test.py`

- [ ] **Step 1: Write failing tests**

Add to `app/db_test.py`:

```python
async def test_init_creates_monitor_config_table(db):
    async with db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_config'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_get_config_returns_defaults_when_missing(db):
    config = await db.get_config("nonexistent")
    assert config["paused"] == 0
    assert config["changed_at"] is None


async def test_set_paused_creates_row(db):
    await db.set_paused("mon", True)
    config = await db.get_config("mon")
    assert config["paused"] == 1


async def test_set_paused_updates_existing_row(db):
    await db.set_paused("mon", True)
    await db.set_paused("mon", False)
    config = await db.get_config("mon")
    assert config["paused"] == 0


async def test_set_changed_at_populates_field(db):
    await db.set_changed_at("mon")
    config = await db.get_config("mon")
    assert config["changed_at"] is not None


async def test_set_changed_at_updates_on_repeated_call(db):
    await db.set_changed_at("mon")
    first = (await db.get_config("mon"))["changed_at"]
    await db.set_changed_at("mon")
    second = (await db.get_config("mon"))["changed_at"]
    assert second >= first


async def test_get_all_configs_returns_keyed_dict(db):
    await db.set_paused("a", True)
    await db.set_paused("b", False)
    configs = await db.get_all_configs()
    assert "a" in configs
    assert "b" in configs
    assert configs["a"]["paused"] == 1
    assert configs["b"]["paused"] == 0


async def test_get_all_monitor_states_includes_paused_and_changed_at(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=10)
    await db.set_paused("mon", True)
    await db.set_changed_at("mon")
    states = await db.get_all_monitor_states()
    mon = next(s for s in states if s["monitor_name"] == "mon")
    assert mon["paused"] == 1
    assert mon["changed_at"] is not None


async def test_get_all_monitor_states_paused_defaults_to_zero(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=10)
    states = await db.get_all_monitor_states()
    mon = next(s for s in states if s["monitor_name"] == "mon")
    assert mon["paused"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/db_test.py -x -q --no-cov -k "monitor_config or get_config or set_paused or set_changed_at or get_all_configs or paused or changed_at"
```

Expected: several `AttributeError` / `AssertionError` failures.

- [ ] **Step 3: Add `monitor_config` table to `db.init()`**

In `app/db.py`, inside `init()`, add to the `executescript` string after the existing `CREATE INDEX IF NOT EXISTS idx_run_logs_run_id` line:

```sql
            CREATE TABLE IF NOT EXISTS monitor_config (
                monitor_name TEXT PRIMARY KEY,
                paused       INTEGER NOT NULL DEFAULT 0,
                changed_at   TEXT
            );
```

- [ ] **Step 4: Add new DB methods to the `Database` class**

```python
    async def set_paused(self, monitor_name: str, paused: bool) -> None:
        await self.conn.execute(
            """INSERT INTO monitor_config (monitor_name, paused)
               VALUES (?, ?)
               ON CONFLICT(monitor_name) DO UPDATE SET paused=excluded.paused""",
            (monitor_name, 1 if paused else 0),
        )
        await self.conn.commit()

    async def set_changed_at(self, monitor_name: str) -> None:
        await self.conn.execute(
            """INSERT INTO monitor_config (monitor_name, changed_at)
               VALUES (?, datetime('now'))
               ON CONFLICT(monitor_name) DO UPDATE SET changed_at=datetime('now')""",
            (monitor_name,),
        )
        await self.conn.commit()

    async def get_config(self, monitor_name: str) -> dict:
        async with self.conn.execute(
            "SELECT monitor_name, paused, changed_at FROM monitor_config WHERE monitor_name = ?",
            (monitor_name,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return {"monitor_name": monitor_name, "paused": 0, "changed_at": None}
        return dict(row)

    async def get_all_configs(self) -> dict[str, dict]:
        async with self.conn.execute(
            "SELECT monitor_name, paused, changed_at FROM monitor_config"
        ) as cur:
            rows = await cur.fetchall()
        return {row["monitor_name"]: dict(row) for row in rows}
```

- [ ] **Step 5: Update `get_all_monitor_states` to LEFT JOIN `monitor_config`**

Replace the existing `get_all_monitor_states` method body:

```python
    async def get_all_monitor_states(self) -> list[dict]:
        async with self.conn.execute(
            """SELECT r.monitor_name, r.status, r.last_value, r.error, r.duration_ms, r.ran_at,
                      COALESCE(c.paused, 0) AS paused, c.changed_at
               FROM runs r
               INNER JOIN (
                   SELECT monitor_name, MAX(ran_at) AS latest
                   FROM runs GROUP BY monitor_name
               ) latest ON r.monitor_name = latest.monitor_name AND r.ran_at = latest.latest
               LEFT JOIN monitor_config c ON r.monitor_name = c.monitor_name"""
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest app/db_test.py -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/db.py app/db_test.py
git commit -m "feat(db): add monitor_config table with pause and changed_at tracking"
```

---

## Task 2: avg_duration method + get_runs_with_logs offset

**Files:**
- Modify: `app/db.py`
- Modify: `app/db_test.py`

- [ ] **Step 1: Write failing tests**

Add to `app/db_test.py`:

```python
async def test_get_avg_duration_returns_none_when_no_runs(db):
    result = await db.get_avg_duration("nonexistent")
    assert result is None


async def test_get_avg_duration_returns_rounded_integer(db):
    await db.record_run("mon", status="ok", last_value="1", error=None, duration_ms=100)
    await db.record_run("mon", status="ok", last_value="2", error=None, duration_ms=200)
    result = await db.get_avg_duration("mon")
    assert result == 150


async def test_get_runs_with_logs_offset_returns_second_page(db):
    for i in range(5):
        await db.record_run("mon", status="ok", last_value=str(i), error=None, duration_ms=i * 10)
    page1 = await db.get_runs_with_logs("mon", limit=3, offset=0)
    page2 = await db.get_runs_with_logs("mon", limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2
    ids_page1 = {r["id"] for r in page1}
    ids_page2 = {r["id"] for r in page2}
    assert ids_page1.isdisjoint(ids_page2)
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest app/db_test.py -x -q --no-cov -k "avg_duration or offset"
```

Expected: `AttributeError: 'Database' object has no attribute 'get_avg_duration'`

- [ ] **Step 3: Add `get_avg_duration` method**

```python
    async def get_avg_duration(self, monitor_name: str) -> Optional[int]:
        async with self.conn.execute(
            "SELECT ROUND(AVG(duration_ms)) AS avg FROM runs WHERE monitor_name = ?",
            (monitor_name,),
        ) as cur:
            row = await cur.fetchone()
        return int(row["avg"]) if row and row["avg"] is not None else None
```

- [ ] **Step 4: Add `offset` parameter to `get_runs_with_logs`**

Replace the existing `get_runs_with_logs` method signature and query:

```python
    async def get_runs_with_logs(self, monitor_name: str, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM runs WHERE monitor_name = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (monitor_name, limit, offset),
        ) as cur:
            run_rows = await cur.fetchall()
        runs = []
        for row in run_rows:
            run = dict(row)
            run["logs"] = await self.get_run_logs(run["id"])
            runs.append(run)
        return runs
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest app/db_test.py -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/db.py app/db_test.py
git commit -m "feat(db): add get_avg_duration and offset support to get_runs_with_logs"
```

---

## Task 3: Runner — add `event` field to SSE + call `set_changed_at` on value change

**Files:**
- Modify: `app/runner.py`
- Modify: `app/runner_test.py`

- [ ] **Step 1: Write failing tests**

Add to `app/runner_test.py`:

```python
async def test_runner_sse_event_has_event_field_on_success(db, browser):
    from unittest.mock import AsyncMock
    from app.events import EventBus

    bus = EventBus()
    bus.publish = AsyncMock()
    m = Monitor(name="evfield_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        pass

    runner = Runner(db=db, browser=browser, event_bus=bus)
    await runner.run(m)

    payload = bus.publish.call_args[0][0]
    assert payload["event"] == "run"


async def test_runner_sse_event_has_event_field_on_error(db, browser):
    from unittest.mock import AsyncMock
    from app.events import EventBus

    bus = EventBus()
    bus.publish = AsyncMock()
    m = Monitor(name="everr_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        raise RuntimeError("oops")

    runner = Runner(db=db, browser=browser, event_bus=bus)
    await runner.run(m)

    payload = bus.publish.call_args[0][0]
    assert payload["event"] == "run"
    assert payload["status"] == "error"


async def test_runner_calls_set_changed_at_when_value_changes(db, browser):
    await db.set_value("chg_mon", "old_value")
    m = Monitor(name="chg_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        from app.helpers import set_value
        await set_value(ctx.db, "chg_mon", "new_value")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    config = await db.get_config("chg_mon")
    assert config["changed_at"] is not None


async def test_runner_does_not_set_changed_at_when_value_unchanged(db, browser):
    await db.set_value("stable_mon", "same_value")
    m = Monitor(name="stable_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        from app.helpers import set_value
        await set_value(ctx.db, "stable_mon", "same_value")

    runner = Runner(db=db, browser=browser)
    await runner.run(m)

    config = await db.get_config("stable_mon")
    assert config["changed_at"] is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest app/runner_test.py -x -q --no-cov -k "event_field or set_changed_at"
```

Expected: `AssertionError` — `event` key missing from payload.

- [ ] **Step 3: Add `"event": "run"` to the success-branch SSE publish in `app/runner.py`**

Find the success-branch publish call and add `"event": "run"`:

```python
            if self._event_bus is not None:
                await self._event_bus.publish({
                    "event": "run",
                    "monitor_name": monitor.name,
                    "status": status,
                    "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "last_value": last_value,
                    "duration_ms": duration_ms,
                    "error": None,
                })
```

Find the exception-branch publish call and add `"event": "run"`:

```python
            if self._event_bus is not None:
                await self._event_bus.publish({
                    "event": "run",
                    "monitor_name": monitor.name,
                    "status": "error",
                    "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "last_value": None,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                })
```

- [ ] **Step 4: Call `set_changed_at` when the value changes**

In `app/runner.py`, after the line:

```python
            status = "changed" if prev_value is not None and last_value != prev_value else "ok"
```

Add:

```python
            if status == "changed":
                await self._db.set_changed_at(monitor.name)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest app/runner_test.py -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/runner.py app/runner_test.py
git commit -m "feat(runner): add event field to SSE payload; track changed_at on value change"
```

---

## Task 4: Pause/resume API endpoints

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing tests**

Add to `app/main_test.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest app/main_test.py -x -q --no-cov -k "pause or resume"
```

Expected: `404` (routes don't exist yet).

- [ ] **Step 3: Add pause/resume endpoints to `app/main.py`**

Add after the existing `run_now` endpoint:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/main_test.py -x -q --no-cov -k "pause or resume"
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat(api): add pause/resume endpoints for monitors"
```

---

## Task 5: Scheduler pause check

**Files:**
- Modify: `app/scheduler.py`
- Modify: `app/scheduler_test.py`

- [ ] **Step 1: Write failing tests**

Add to `app/scheduler_test.py` (the file already has a `db` fixture — add it if it doesn't exist; otherwise skip adding it):

```python
@pytest.fixture
async def db(tmp_path):
    from app.db import Database
    database = Database(str(tmp_path / "sched_test.db"))
    await database.init()
    yield database
    await database.close()


async def test_make_job_fn_skips_run_when_paused(db, monitors_dir):
    from unittest.mock import AsyncMock
    _make_monitor_module(monitors_dir, "price")
    sched = Scheduler(monitors_dir=monitors_dir, db=db)
    await sched.start()

    await db.set_paused("price", True)
    monitor = next(m for m in sched._monitors if m.name == "price")
    mock_runner = AsyncMock()
    job_fn = sched._make_job_fn(mock_runner, monitor)
    await job_fn()

    mock_runner.run.assert_not_called()
    await sched.stop()


async def test_make_job_fn_runs_when_not_paused(db, monitors_dir):
    from unittest.mock import AsyncMock
    _make_monitor_module(monitors_dir, "price")
    sched = Scheduler(monitors_dir=monitors_dir, db=db)
    await sched.start()

    monitor = next(m for m in sched._monitors if m.name == "price")
    mock_runner = AsyncMock()
    job_fn = sched._make_job_fn(mock_runner, monitor)
    await job_fn()

    mock_runner.run.assert_called_once_with(monitor)
    await sched.stop()
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest app/scheduler_test.py -x -q --no-cov -k "make_job_fn"
```

Expected: `AttributeError: 'Scheduler' object has no attribute '_make_job_fn'`

- [ ] **Step 3: Add `_make_job_fn` to `Scheduler` in `app/scheduler.py`**

```python
    def _make_job_fn(self, runner: Runner, monitor: Monitor):
        async def _run() -> None:
            config = await self._db.get_config(monitor.name)
            if config.get("paused"):
                return
            await runner.run(monitor)
        return _run
```

- [ ] **Step 4: Use `_make_job_fn` in `start()`**

Replace the `add_job` call inside `start()`:

```python
            self._scheduler.add_job(
                self._make_job_fn(runner, monitor),
                CronTrigger.from_crontab(monitor.schedule, timezone=self._timezone),
                id=monitor.name,
                name=monitor.name,
                misfire_grace_time=60,
                replace_existing=True,
            )
```

Note: remove `args=[monitor]` — monitor is captured in the closure.

- [ ] **Step 5: Apply identical change in `reload()`**

In `reload()`, replace the `add_job` call with the same pattern:

```python
            self._scheduler.add_job(
                self._make_job_fn(runner, monitor),
                CronTrigger.from_crontab(monitor.schedule, timezone=self._timezone),
                id=monitor.name,
                name=monitor.name,
                misfire_grace_time=60,
                replace_existing=True,
            )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest app/scheduler_test.py -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/scheduler.py app/scheduler_test.py
git commit -m "feat(scheduler): skip cron runs for paused monitors via _make_job_fn"
```

---

## Task 6: cron-descriptor + `_humanize_cron` Jinja filter

**Files:**
- Modify: `pyproject.toml` (via uv)
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Add `cron-descriptor` dependency**

```bash
uv add cron-descriptor
```

Verify:

```bash
uv run python -c "from cron_descriptor import get_description; print(get_description('*/30 * * * *'))"
```

Expected: `Every 30 minutes` (or similar).

- [ ] **Step 2: Write failing tests**

Add to `app/main_test.py`:

```python
def test_humanize_cron_returns_human_string_for_common_pattern():
    from app.main import _humanize_cron
    result = _humanize_cron("*/30 * * * *")
    assert "30" in result.lower()


def test_humanize_cron_returns_input_on_invalid_cron():
    from app.main import _humanize_cron
    result = _humanize_cron("not-a-cron")
    assert result == "not-a-cron"
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest app/main_test.py -x -q --no-cov -k "humanize_cron"
```

Expected: `ImportError` — `_humanize_cron` not defined yet.

- [ ] **Step 4: Add `_humanize_cron` and register as Jinja filter in `app/main.py`**

Add import at the top of `app/main.py`:

```python
from cron_descriptor import get_description as _cron_get_description
```

Add the function before `templates.env.filters["localtime"] = _to_local`:

```python
def _humanize_cron(cron: str) -> str:
    try:
        return _cron_get_description(cron).lower()
    except Exception:
        return cron
```

Add filter registration after `templates.env.filters["localtime"] = _to_local`:

```python
templates.env.filters["humanize_cron"] = _humanize_cron
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest app/main_test.py -x -q --no-cov -k "humanize_cron"
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock app/main.py app/main_test.py
git commit -m "feat(main): add humanize_cron Jinja filter via cron-descriptor"
```

---

## Task 7: Update routes to pass new context + offset on runs API

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing test for offset**

Add to `app/main_test.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest app/main_test.py -x -q --no-cov -k "offset"
```

Expected: pages return overlapping IDs (offset ignored).

- [ ] **Step 3: Update `api_monitor_runs` to accept `limit` and `offset`**

Replace the existing `api_monitor_runs` in `app/main.py`:

```python
@app.get("/api/monitors/{name}/runs")
async def api_monitor_runs(name: str, db: DbDep, limit: int = 50, offset: int = 0) -> list[dict]:
    return await db.get_runs_with_logs(name, limit=limit, offset=offset)
```

- [ ] **Step 4: Update `dashboard` route — add `paused`/`changed_at` defaults for pending monitors**

In `app/main.py`, in the `dashboard` route, change the pending monitor append:

```python
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
```

- [ ] **Step 5: Update `monitor_detail` route — pass `paused`, `changed_at`, `avg_duration`**

Replace the existing `monitor_detail` route:

```python
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
        }
    )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest app/main_test.py -x -q --no-cov
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat(main): pass paused/changed_at/avg_duration to templates; offset on runs API"
```

---

## Task 8: Dashboard UI — in-place SSE updates, paused chip, cron human label

**Files:**
- Modify: `app/templates/dashboard.html`

- [ ] **Step 1: Add `data-monitor` attribute to each monitor card**

Find:

```html
  <div class="neu-raised monitor-card" data-status="{{ m.status }}">
```

Change to:

```html
  <div class="neu-raised monitor-card" data-status="{{ m.status }}" data-monitor="{{ m.monitor_name }}">
```

- [ ] **Step 2: Add paused chip CSS to the `<style>` block**

Add after the `.conn-dot` rule:

```css
  /* ── Paused chip ─────────────────────────────────────────── */
  .paused-chip {
    font: 500 9px/1 var(--sans);
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ink-3);
    padding: 3px 7px;
    border-radius: 999px;
    background: var(--surface);
    box-shadow: inset 1px 1px 3px var(--shadow), inset -1px -1px 3px var(--raise);
  }
```

- [ ] **Step 3: Add conditional paused chip in the card header**

In the card template, after `</div>` closing `.monitor-name-block` and before the run-btn div, add:

```html
      {% if m.paused %}
      <span class="paused-chip">paused</span>
      {% endif %}
```

- [ ] **Step 4: Add human-readable cron label**

Find:

```html
          <div class="monitor-schedule">{{ m.schedule }}</div>
```

Change to:

```html
          <div class="monitor-schedule">{{ m.schedule }}</div>
          <div class="monitor-schedule" style="color:var(--ink-4)">{{ m.schedule | humanize_cron }}</div>
```

- [ ] **Step 5: Replace the entire `location.reload()` SSE IIFE with in-place update JS**

Find the entire `(function () { ... })();` block at the bottom of `{% block scripts %}` and replace it with:

```js
  (function () {
    const indicator = document.querySelector('.conn-indicator');
    const dot = indicator && indicator.querySelector('.conn-dot');

    function setConn(ok) {
      if (!dot || !indicator) return;
      dot.style.background = ok ? '' : 'var(--ink-4)';
      dot.style.boxShadow  = ok ? '' : 'none';
      indicator.childNodes.forEach(node => {
        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
          node.textContent = ok ? ' connected' : ' reconnecting…';
        }
      });
    }

    function updateStatStrip() {
      const cards = document.querySelectorAll('#monitor-grid .monitor-card');
      let ok = 0, changed = 0, error = 0, pending = 0;
      cards.forEach(c => {
        const s = c.dataset.status;
        if (s === 'ok') ok++;
        else if (s === 'changed') changed++;
        else if (s === 'error') error++;
        else pending++;
      });
      const counts = document.querySelectorAll('.stat-tile .count');
      if (counts.length >= 4) {
        [[ok, 0], [changed, 1], [error, 2], [pending, 3]].forEach(([n, i]) => {
          counts[i].textContent = String(n).padStart(2, '0');
          counts[i].className = 'count num' + (n === 0 ? ' zero' : '');
        });
      }
    }

    function setText(el, text) {
      if (el) el.textContent = text;
    }

    function updateCard(data) {
      const card = document.querySelector('.monitor-card[data-monitor="' + data.monitor_name + '"]');
      if (!card) { location.reload(); return; }

      card.dataset.status = data.status;

      const led = card.querySelector('.led');
      if (led) led.className = 'led ' + data.status;

      const chip = card.querySelector('.chip');
      if (chip) { chip.className = 'chip ' + data.status; setText(chip, data.status); }

      const well = card.querySelector('.monitor-value-well');
      if (well) {
        const valueEl = well.querySelector('.monitor-value');
        if (data.status === 'error') {
          const msg = (data.error || '').slice(0, 60) + ((data.error || '').length > 60 ? '…' : '');
          if (valueEl) {
            valueEl.className = 'mono t-err';
            valueEl.style.fontSize = '12px';
            valueEl.style.lineHeight = '1.4';
            setText(valueEl, msg);
          }
        } else if (data.status === 'changed') {
          if (valueEl) {
            valueEl.className = 'mono t-chg monitor-value';
            valueEl.style.fontSize = '';
            valueEl.style.lineHeight = '';
            setText(valueEl, data.last_value || '—');
          }
        } else {
          if (valueEl) {
            valueEl.className = 'monitor-value' + (data.last_value ? '' : ' t-4');
            valueEl.style.fontSize = '';
            valueEl.style.lineHeight = '';
            setText(valueEl, data.last_value || '—');
          }
        }
      }

      const footer = card.querySelector('.monitor-footer');
      if (footer) {
        const timeEl = footer.querySelector('.mono');
        if (timeEl) setText(timeEl, 'last: ' + (data.ran_at || 'never'));
        const durEls = footer.querySelectorAll('.mono');
        if (durEls[1] && data.duration_ms != null) setText(durEls[1], data.duration_ms + 'ms');
      }

      updateStatStrip();
    }

    function updatePauseChip(data) {
      const card = document.querySelector('.monitor-card[data-monitor="' + data.monitor_name + '"]');
      if (!card) return;
      const existing = card.querySelector('.paused-chip');
      if (data.paused && !existing) {
        const chip = document.createElement('span');
        chip.className = 'paused-chip';
        chip.textContent = 'paused';
        const header = card.querySelector('.monitor-card-header');
        const runBtn = header && header.querySelector('.run-btn');
        if (header && runBtn) header.insertBefore(chip, runBtn);
      } else if (!data.paused && existing) {
        existing.remove();
      }
    }

    const src = new EventSource('/api/events');
    src.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.event === 'run')    updateCard(data);
        if (data.event === 'paused') updatePauseChip(data);
      } catch (_) { location.reload(); }
    };
    src.onopen    = () => setConn(true);
    src.onerror   = () => setConn(false);
    window.addEventListener('beforeunload', () => src.close());
  })();
```

- [ ] **Step 6: Remove `location.reload()` from `runMonitor` — SSE now handles the update**

In the `runMonitor` function (in the same `{% block scripts %}`), replace:

```js
      if (res.ok) {
        btn.style.color = 'var(--ok)';
        setTimeout(() => location.reload(), 2000);
      }
```

With:

```js
      if (res.ok) {
        btn.style.color = 'var(--ok)';
        setTimeout(() => { btn.style.color = ''; btn.disabled = false; wrap.classList.remove('loading'); }, 2000);
      }
```

The SSE event published by the runner will fire and call `updateCard` within ~150ms of the run completing, so the card updates in-place.

- [ ] **Step 7: Verify locally**

```bash
uv run uvicorn app.main:app --reload
```

Navigate to `http://localhost:8000`. Trigger a monitor run manually. Verify the card updates in place without a page reload flash. Verify stat strip counters update. Call `POST /monitors/{name}/pause` via curl and verify the paused chip appears without reload.

- [ ] **Step 8: Commit**

```bash
git add app/templates/dashboard.html
git commit -m "feat(dashboard): in-place SSE card updates, paused chip, humanize_cron label"
```

---

## Task 9: Monitor detail UI — pause button, metrics, cron label, pagination

**Files:**
- Modify: `app/templates/monitor_detail.html`

- [ ] **Step 1: Wire the Pause/Resume button**

In `app/templates/monitor_detail.html`, find and replace the existing disabled pause button in `{% block topbar %}`:

```html
  <button class="btn" id="pause-btn" style="opacity:.5;cursor:default" disabled>
    <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" stroke="none">
      <rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>
    </svg>
    Pause
  </button>
```

Replace with:

```html
  <button class="btn" id="pause-btn" onclick="togglePause()">
    {% if paused %}
    <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" stroke="none">
      <path d="M7 5l11 7-11 7V5z"/>
    </svg>
    <span id="pause-label">Resume</span>
    {% else %}
    <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" stroke="none">
      <rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>
    </svg>
    <span id="pause-label">Pause</span>
    {% endif %}
  </button>
```

- [ ] **Step 2: Add `togglePause` JS to `{% block scripts %}`**

Add before the closing `</script>` tag:

```js
  let _paused = {{ 'true' if paused else 'false' }};

  async function togglePause() {
    const btn = document.getElementById('pause-btn');
    const label = document.getElementById('pause-label');
    btn.disabled = true;
    const action = _paused ? 'resume' : 'pause';
    try {
      const res = await fetch('/monitors/{{ monitor_name }}/' + action, { method: 'POST' });
      if (res.ok) {
        _paused = !_paused;
        label.textContent = _paused ? 'Resume' : 'Pause';
      }
    } finally {
      btn.disabled = false;
    }
  }
```

- [ ] **Step 3: Expand metric strip to 5 columns**

In `{% block head %}` CSS, change `.metric-strip` grid:

```css
  .metric-strip {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 22px;
  }
```

Update the `@media (max-width: 900px)` breakpoint:

```css
  @media (max-width: 900px) {
    .metric-strip { grid-template-columns: repeat(3, 1fr); }
```

- [ ] **Step 4: Add avg_duration tile**

In `{% block content %}`, after the existing "total runs" metric tile, add:

```html
  <div class="neu-raised-sm metric-card">
    <div class="eyebrow">avg duration</div>
    <div class="metric-value num">
      {% if avg_duration is not none %}
        {{ avg_duration }}<span class="metric-unit">ms</span>
      {% else %}
        <span class="t-4">—</span>
      {% endif %}
    </div>
  </div>
```

- [ ] **Step 5: Add `changed_at` sub-line inside the status tile**

Find the status metric-card (the tile with `<div class="eyebrow">status</div>`). After the closing `</div>` of the `metric-value` div, add:

```html
    {% if changed_at %}
    <div class="metric-sub">changed: {{ changed_at | localtime }}</div>
    {% endif %}
```

- [ ] **Step 6: Add human-readable cron label in the topbar**

Find:

```html
  <div class="topbar-sub">{{ schedule }}</div>
```

Change to:

```html
  <div class="topbar-sub">{{ schedule }} · {{ schedule | humanize_cron }}</div>
```

- [ ] **Step 7: Add "Load more" button**

At the bottom of `{% block content %}`, after the `{% endif %}` that closes the runs list section, add:

```html
<div id="load-more-wrap" style="text-align:center;margin-top:16px">
  {% if runs | length == 50 %}
  <button class="btn" id="load-more-btn" onclick="loadMoreRuns()">Load more</button>
  {% endif %}
</div>
```

- [ ] **Step 8: Add `loadMoreRuns` JS**

Add in `{% block scripts %}` before the closing `</script>` tag. This function fetches the next page and appends rows without using untrusted content in innerHTML — only `textContent` is used for dynamic values:

```js
  let _runsOffset = {{ runs | length }};

  async function loadMoreRuns() {
    const btn = document.getElementById('load-more-btn');
    if (btn) btn.disabled = true;
    try {
      const res = await fetch('/api/monitors/{{ monitor_name }}/runs?limit=50&offset=' + _runsOffset);
      if (!res.ok) return;
      const runs = await res.json();
      const list = document.getElementById('runs-list');
      runs.forEach(run => {
        const row = document.createElement('div');
        row.className = 'neu-raised-sm run-row';
        row.dataset.status = run.status;
        row.id = 'run-' + run.id;

        const main = document.createElement('div');
        main.className = 'run-row-main';
        main.onclick = () => toggleRun(String(run.id), !!(run.logs && run.logs.length));

        const led = document.createElement('div');
        led.className = 'led ' + run.status;

        const time = document.createElement('span');
        time.className = 'run-time mono num';
        time.textContent = run.ran_at || '—';

        const chip = document.createElement('span');
        chip.className = 'chip ' + run.status;
        chip.style.cssText = 'padding:3px 8px;font-size:9px;letter-spacing:0.1em';
        chip.textContent = run.status;

        const dur = document.createElement('span');
        dur.className = 'run-dur mono num';
        dur.textContent = run.duration_ms + 'ms';

        const val = document.createElement('span');
        const rawVal = run.last_value || (run.error ? run.error.split('\n')[0] : '—');
        val.className = 'run-value ' + (run.status === 'error' ? 't-err mono' : run.status === 'changed' ? 't-chg mono' : 't-2');
        val.textContent = rawVal;

        const chev = document.createElement('span');
        chev.className = 'run-chevron';
        chev.style.transform = 'rotate(-90deg)';
        chev.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>';

        main.append(led, time, chip, dur, val, chev);
        row.appendChild(main);
        if (list) list.appendChild(row);
      });
      _runsOffset += runs.length;
      if (runs.length < 50) {
        const wrap = document.getElementById('load-more-wrap');
        if (wrap) wrap.remove();
      } else if (btn) {
        btn.disabled = false;
      }
    } catch (_) {
      if (btn) btn.disabled = false;
    }
  }
```

- [ ] **Step 9: Verify locally**

```bash
uv run uvicorn app.main:app --reload
```

On a monitor detail page:
- Pause button toggles between "Pause" and "Resume"
- Avg duration tile shows a computed value
- Status tile shows "changed: {datetime}" if changed_at is set
- Topbar shows `*/30 * * * * · every 30 minutes` (or similar)
- "Load more" appears for monitors with 50+ runs; clicking appends rows

- [ ] **Step 10: Commit**

```bash
git add app/templates/monitor_detail.html
git commit -m "feat(monitor-detail): wire pause button, avg duration, cron label, load more"
```

---

## Task 10: Remove disabled sign-out nav button

**Files:**
- Modify: `app/templates/base.html`

- [ ] **Step 1: Delete the sign-out button**

In `app/templates/base.html`, find and delete:

```html
      <div class="nav-item" title="Sign out" style="cursor:default;opacity:.4">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3v9"/><path d="M5.5 8.5a9 9 0 1 0 13 0"/>
        </svg>
      </div>
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/base.html
git commit -m "chore(nav): remove disabled sign-out button"
```

---

## Task 11: Full test suite + coverage gate

- [ ] **Step 1: Run the full suite with coverage**

```bash
uv run pytest
```

Expected: 100% coverage, all pass. If any tests fail or coverage drops below 100%, fix before pushing.

- [ ] **Step 2: Push**

```bash
git pull --rebase && git push
```
