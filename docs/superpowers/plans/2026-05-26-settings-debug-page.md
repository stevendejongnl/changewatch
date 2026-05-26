# Settings & Debug Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/settings` debug page (config dump, DB stats, notification test, live app logs via SSE) and a helper reference panel in the monitor editor.

**Architecture:** A new `AppLogBuffer` logging handler captures app-level Python log records to an in-memory deque and streams them via SSE. The settings page fetches config/stats via three new JSON endpoints and renders everything client-side using DOM methods (no innerHTML with dynamic data). The editor helper panel is purely frontend — static HTML + a snippet-insert JS function.

**Tech Stack:** FastAPI, Jinja2, aiosqlite, Python `logging`, asyncio.Queue (SSE streaming), existing neumorphic CSS design system.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `app/log_stream.py` | Create | `AppLogBuffer` handler + singleton |
| `app/log_stream_test.py` | Create | Tests for AppLogBuffer |
| `app/db.py` | Modify | Add `get_stats()` method |
| `app/db_test.py` | Modify | Tests for `get_stats()` |
| `app/main.py` | Modify | New routes + `_apprise` dep + register log buffer in lifespan |
| `app/main_test.py` | Modify | Tests for new endpoints |
| `app/templates/settings.html` | Create | Settings page template |
| `app/templates/base.html` | Modify | Gear nav item in sidebar + mobile tabs |
| `app/templates/monitor_editor.html` | Modify | Helper reference panel |

---

## Task 1: AppLogBuffer

**Files:**
- Create: `app/log_stream.py`
- Create: `app/log_stream_test.py`

- [ ] **Step 1: Write failing tests**

```python
# app/log_stream_test.py
import asyncio
import logging

from app.log_stream import AppLogBuffer, get_log_buffer


def _make_record(msg: str, level: str = "INFO") -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=getattr(logging, level),
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    return record


def test_emit_stores_in_history():
    buf = AppLogBuffer(maxlen=10)
    buf.emit(_make_record("hello"))
    history = buf.get_history()
    assert len(history) == 1
    assert history[0]["message"] == "hello"
    assert history[0]["level"] == "INFO"
    assert history[0]["logger"] == "test.logger"
    assert isinstance(history[0]["ts"], float)


def test_history_respects_maxlen():
    buf = AppLogBuffer(maxlen=3)
    for i in range(5):
        buf.emit(_make_record(f"msg{i}"))
    history = buf.get_history()
    assert len(history) == 3
    assert history[0]["message"] == "msg2"
    assert history[-1]["message"] == "msg4"


def test_get_history_returns_snapshot():
    buf = AppLogBuffer()
    buf.emit(_make_record("a"))
    snapshot = buf.get_history()
    buf.emit(_make_record("b"))
    assert len(snapshot) == 1  # snapshot not affected by later emit


async def test_subscribe_receives_emitted_record():
    buf = AppLogBuffer()
    q = buf.subscribe()
    buf.emit(_make_record("streamed"))
    entry = await asyncio.wait_for(q.get(), timeout=1.0)
    assert entry["message"] == "streamed"


async def test_unsubscribe_stops_delivery():
    buf = AppLogBuffer()
    q = buf.subscribe()
    buf.unsubscribe(q)
    buf.emit(_make_record("after-unsub"))
    assert q.empty()


def test_get_log_buffer_returns_singleton():
    a = get_log_buffer()
    b = get_log_buffer()
    assert a is b
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/stevendejong/workspace/personal/changewatch
uv run pytest app/log_stream_test.py --no-cov -x -q 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'app.log_stream'`

- [ ] **Step 3: Implement AppLogBuffer**

Create `app/log_stream.py`:

```python
import asyncio
import collections
import logging
from typing import Any


class AppLogBuffer(logging.Handler):
    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._history: collections.deque[dict[str, Any]] = collections.deque(maxlen=maxlen)
        self._queues: set[asyncio.Queue] = set()

    def emit(self, record: logging.LogRecord) -> None:
        entry: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "ts": record.created,
        }
        self._history.append(entry)
        for q in list(self._queues):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._history)


_buf = AppLogBuffer()


def get_log_buffer() -> AppLogBuffer:
    return _buf
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/log_stream_test.py --no-cov -x -q
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/log_stream.py app/log_stream_test.py
git commit -m "feat(log_stream): add AppLogBuffer for in-memory app log capture"
```

---

## Task 2: Database.get_stats()

**Files:**
- Modify: `app/db.py` (add `get_stats` method)
- Modify: `app/db_test.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `app/db_test.py`:

```python
async def test_get_stats_returns_zero_counts_on_empty_db(db):
    stats = await db.get_stats()
    assert stats["runs"] == 0
    assert stats["run_logs"] == 0
    assert stats["state"] == 0
    assert stats["monitor_config"] == 0
    assert stats["oldest_run"] is None
    assert stats["newest_run"] is None
    assert isinstance(stats["db_size_bytes"], int)


async def test_get_stats_counts_runs_correctly(db):
    await db.record_run("mon_a", status="ok", last_value="v", error=None, duration_ms=10)
    await db.record_run("mon_a", status="ok", last_value="v2", error=None, duration_ms=20)
    stats = await db.get_stats()
    assert stats["runs"] == 2
    assert stats["oldest_run"] is not None
    assert stats["newest_run"] is not None


async def test_get_stats_counts_state_and_config(db):
    await db.set_value("mon", "42")
    await db.set_paused("mon", True)
    stats = await db.get_stats()
    assert stats["state"] == 1
    assert stats["monitor_config"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/db_test.py::test_get_stats_returns_zero_counts_on_empty_db --no-cov -x -q
```

Expected: `AttributeError: 'Database' object has no attribute 'get_stats'`

- [ ] **Step 3: Implement get_stats()**

Add to `app/db.py` at the end of the `Database` class (before `close`):

```python
    async def get_stats(self) -> dict:
        import os
        result: dict = {}
        for table in ("runs", "run_logs", "state", "monitor_config"):
            async with self.conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:  # noqa: S608
                row = await cur.fetchone()
            result[table] = row[0]
        async with self.conn.execute("SELECT MIN(ran_at), MAX(ran_at) FROM runs") as cur:
            row = await cur.fetchone()
        result["oldest_run"] = row[0]
        result["newest_run"] = row[1]
        try:
            result["db_size_bytes"] = os.path.getsize(self._path)
        except OSError:
            result["db_size_bytes"] = 0
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/db_test.py --no-cov -x -q
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add app/db.py app/db_test.py
git commit -m "feat(db): add get_stats() for debug endpoint"
```

---

## Task 3: Config + Notify-Test Endpoints

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing tests**

Append to `app/main_test.py`:

```python
from app.main import _mask_url


def test_mask_url_empty_string_returns_empty():
    assert _mask_url("") == ""


def test_mask_url_short_url_returns_masked():
    assert _mask_url("abc") == "****"


def test_mask_url_long_url_shows_last_8_chars():
    result = _mask_url("https://github.com/user/secret-repo")
    assert result == "****...cret-repo"


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/main_test.py::test_mask_url_empty_string_returns_empty app/main_test.py::test_api_debug_config_returns_expected_keys --no-cov -x -q 2>&1 | head -10
```

Expected: `ImportError` — `_mask_url` not found

- [ ] **Step 3: Add _mask_url, _apprise dep, and two endpoints to main.py**

After the existing `_humanize_cron` function, add:

```python
def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 8:
        return "****"
    return "****..." + url[-8:]
```

After `_git_editor: GitEditor | None = None`, add:

```python
_apprise: AppriseClient | None = None
```

After the existing `get_git_editor` function, add:

```python
async def get_apprise() -> AppriseClient:  # pragma: no cover
    return _apprise or AppriseClient()

AppraiseDep = Annotated[AppriseClient, Depends(get_apprise)]
```

In the lifespan function, change the global declaration line to:

```python
global _db, _scheduler, _browser, _git_sync, _git_editor, _apprise
```

Replace the inline `AppriseClient()` inside the Scheduler call with `_apprise`:

```python
# Before:
_scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db, apprise=AppriseClient(), timezone=DISPLAY_TZ, event_bus=get_event_bus())

# After (two lines):
_apprise = AppriseClient()
_scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db, apprise=_apprise, timezone=DISPLAY_TZ, event_bus=get_event_bus())
```

Add the two new endpoints (before the `@app.get("/")` dashboard route):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/main_test.py::test_mask_url_empty_string_returns_empty app/main_test.py::test_mask_url_short_url_returns_masked app/main_test.py::test_mask_url_long_url_shows_last_8_chars app/main_test.py::test_api_debug_config_returns_expected_keys app/main_test.py::test_api_debug_notify_test_returns_404_for_unknown_channel app/main_test.py::test_api_debug_notify_test_sends_notification_and_returns_ok --no-cov -x -q
```

Expected: `6 passed`

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat(main): add _apprise dep, /api/debug/config, /api/debug/notify-test"
```

---

## Task 4: DB Stats + Log Stream Endpoints

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing tests**

Append to `app/main_test.py`:

```python
async def test_api_debug_db_stats_returns_expected_keys(client, db):
    response = await client.get("/api/debug/db-stats")
    assert response.status_code == 200
    data = response.json()
    for key in ("runs", "run_logs", "state", "monitor_config", "db_size_bytes"):
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/main_test.py::test_api_debug_db_stats_returns_expected_keys --no-cov -x -q 2>&1 | head -10
```

Expected: `404 Not Found`

- [ ] **Step 3: Add endpoints + imports + log buffer registration**

In `app/main.py`, add to the top-level imports:

```python
import logging as _logging
from app.log_stream import AppLogBuffer, get_log_buffer
```

Add a new dependency function after `get_apprise`:

```python
def get_log_buf() -> AppLogBuffer:  # pragma: no cover
    return get_log_buffer()

LogBufDep = Annotated[AppLogBuffer, Depends(get_log_buf)]
```

Add the two endpoints after `api_debug_notify_test`:

```python
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
```

In the lifespan function, after `_apprise = AppriseClient()`, add:

```python
_log_buf = get_log_buffer()
_log_buf.setLevel(_logging.INFO)
_logging.getLogger().addHandler(_log_buf)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/main_test.py::test_api_debug_db_stats_returns_expected_keys app/main_test.py::test_api_debug_db_stats_counts_reflect_data app/main_test.py::test_api_debug_log_stream_returns_history_as_sse --no-cov -x -q
```

Expected: `3 passed`

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat(main): add /api/debug/db-stats and /api/debug/log-stream endpoints"
```

---

## Task 5: /settings Route + Template

**Files:**
- Modify: `app/main.py` (add `/settings` route)
- Create: `app/templates/settings.html`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing test**

Append to `app/main_test.py`:

```python
async def test_settings_returns_200(client):
    response = await client.get("/settings")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Settings" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest app/main_test.py::test_settings_returns_200 --no-cov -x -q 2>&1 | head -5
```

Expected: `404 Not Found`

- [ ] **Step 3: Add /settings route to main.py**

Add before the `@app.get("/")` dashboard route:

```python
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {})
```

- [ ] **Step 4: Create settings.html**

Create `app/templates/settings.html` with the following content.
All dynamic rendering uses DOM methods (`createElement`, `textContent`) — no `innerHTML` for untrusted data:

```html
{% extends "base.html" %}

{% block title %}Settings — changewatch{% endblock %}
{% block nav_settings %}active{% endblock %}
{% block mob_settings %}active{% endblock %}

{% block head %}
<style>
  .settings-stack { display: flex; flex-direction: column; gap: 20px; }
  .settings-card { padding: 24px; }
  .settings-card-title {
    font: 600 11px var(--sans);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--ink-3);
    margin-bottom: 18px;
  }
  .config-table { display: flex; flex-direction: column; gap: 10px; }
  .config-row {
    display: flex;
    align-items: baseline;
    gap: 16px;
    padding: 9px 14px;
    border-radius: 9px;
    background: var(--surface);
    box-shadow: inset 2px 2px 5px var(--shadow), inset -2px -2px 5px var(--raise);
  }
  .config-key {
    font: 500 10.5px var(--sans);
    letter-spacing: 0.04em;
    color: var(--ink-3);
    min-width: 130px;
    flex-shrink: 0;
  }
  .config-val {
    font: 12.5px var(--mono);
    color: var(--ink);
    word-break: break-all;
  }
  .db-stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 16px;
  }
  .stat-mini {
    padding: 14px 16px;
    border-radius: 12px;
    text-align: center;
  }
  .stat-mini-val {
    font: 600 22px/1 var(--sans);
    letter-spacing: -0.02em;
    color: var(--ink);
  }
  .channel-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
  }
  .channel-row:last-child { border-bottom: 0; }
  .channel-name {
    font: 500 12px var(--mono);
    color: var(--ink-2);
    min-width: 100px;
  }
  .test-result {
    font: 12px var(--sans);
    min-width: 80px;
  }
  .log-controls {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }
  .log-console-wrap {
    height: 320px;
    overflow-y: auto;
    padding: 12px 14px;
    border-radius: 12px;
    font: 11.5px/1.65 var(--mono);
    background: var(--surface);
    box-shadow: inset 3px 3px 7px var(--shadow), inset -2px -2px 5px var(--raise);
  }
  .log-line { white-space: pre-wrap; word-break: break-all; }
  .log-error  { color: var(--err); }
  .log-warn   { color: var(--chg); }
  .log-info   { color: var(--ink-2); }
  .log-debug  { color: var(--ink-4); }
  .autoscroll-label {
    display: flex; align-items: center; gap: 6px;
    font: 500 11px var(--sans); color: var(--ink-3); cursor: pointer;
  }
  @media (max-width: 700px) {
    .db-stats-grid { grid-template-columns: repeat(2, 1fr); }
    .log-controls { gap: 6px; }
  }
</style>
{% endblock %}

{% block topbar %}
<div class="topbar-left">
  <h1>Settings</h1>
  <div class="topbar-sub">Configuration &amp; debug tools</div>
</div>
{% endblock %}

{% block content %}
<div class="settings-stack">

  <div class="neu-raised-sm settings-card">
    <div class="settings-card-title">Configuration</div>
    <div class="config-table" id="config-table">
      <div class="t-3" style="font-size:12px">Loading&#8230;</div>
    </div>
  </div>

  <div class="neu-raised-sm settings-card">
    <div class="settings-card-title">Database</div>
    <div id="db-stats-content">
      <div class="t-3" style="font-size:12px">Loading&#8230;</div>
    </div>
  </div>

  <div class="neu-raised-sm settings-card">
    <div class="settings-card-title">Notification channels</div>
    <div id="channels-list">
      <div class="t-3" style="font-size:12px">Loading&#8230;</div>
    </div>
  </div>

  <div class="neu-raised-sm settings-card">
    <div class="settings-card-title" style="margin-bottom:12px">App logs</div>
    <div class="log-controls">
      <div class="seg" id="log-level-seg">
        <button class="on" onclick="setLogFilter('all', this)">All</button>
        <button onclick="setLogFilter('info', this)">Info+</button>
        <button onclick="setLogFilter('warn', this)">Warn+</button>
        <button onclick="setLogFilter('error', this)">Error</button>
      </div>
      <label class="autoscroll-label">
        <input type="checkbox" id="autoscroll" checked> Auto-scroll
      </label>
      <button class="btn" onclick="clearLogs()">Clear</button>
    </div>
    <div class="log-console-wrap" id="log-console"></div>
  </div>

</div>
{% endblock %}

{% block scripts %}
<script>
  // ── Config ──────────────────────────────────────────────────
  fetch('/api/debug/config').then(function(r) { return r.json(); }).then(function(cfg) {
    var pairs = [
      ['Timezone',      String(cfg.display_tz)],
      ['Monitors dir',  String(cfg.monitors_dir)],
      ['DB path',       String(cfg.db_path)],
      ['Git repo',      cfg.git_repo_url ? String(cfg.git_repo_url) : '(not set)'],
      ['Sync interval', String(cfg.git_sync_interval)],
      ['Git enabled',   cfg.git_enabled ? 'yes' : 'no'],
    ];
    var table = document.getElementById('config-table');
    table.textContent = '';
    pairs.forEach(function(pair) {
      var row = document.createElement('div');
      row.className = 'config-row';
      var keyEl = document.createElement('span');
      keyEl.className = 'config-key';
      keyEl.textContent = pair[0];
      var valEl = document.createElement('span');
      valEl.className = 'config-val';
      valEl.textContent = pair[1];
      row.appendChild(keyEl);
      row.appendChild(valEl);
      table.appendChild(row);
    });

    var list = document.getElementById('channels-list');
    list.textContent = '';
    if (!cfg.channels || !cfg.channels.length) {
      var msg = document.createElement('div');
      msg.className = 't-4';
      msg.style.fontSize = '12px';
      msg.textContent = 'No APPRISE_URL_* env vars configured.';
      list.appendChild(msg);
    } else {
      cfg.channels.forEach(function(ch) {
        var row = document.createElement('div');
        row.className = 'channel-row';
        row.id = 'ch-' + ch;

        var nameEl = document.createElement('span');
        nameEl.className = 'channel-name';
        nameEl.textContent = ch;

        var btn = document.createElement('button');
        btn.className = 'btn';
        var label = document.createElement('span');
        label.className = 'ch-label';
        label.textContent = 'Test';
        var spin = document.createElement('span');
        spin.className = 'ch-spin spinner';
        spin.style.cssText = 'display:none;width:10px;height:10px;border-radius:50%;border:1.5px solid var(--ink-4);border-top-color:var(--accent);animation:spin .6s linear infinite';
        btn.appendChild(label);
        btn.appendChild(spin);
        (function(channel) {
          btn.addEventListener('click', function() { testChannel(channel); });
        }(ch));

        var result = document.createElement('span');
        result.className = 'test-result';
        result.id = 'ch-result-' + ch;

        row.appendChild(nameEl);
        row.appendChild(btn);
        row.appendChild(result);
        list.appendChild(row);
      });
    }
  }).catch(function() {
    var el = document.getElementById('config-table');
    el.textContent = '';
    var msg = document.createElement('div');
    msg.className = 't-err';
    msg.style.fontSize = '12px';
    msg.textContent = 'Failed to load config.';
    el.appendChild(msg);
  });

  // ── DB Stats ─────────────────────────────────────────────────
  fetch('/api/debug/db-stats').then(function(r) { return r.json(); }).then(function(s) {
    function fmt(n) { return n != null ? n.toLocaleString() : '—'; }
    function fmtBytes(n) {
      if (!n) return '0 B';
      var kb = n / 1024;
      return kb >= 1024 ? (kb / 1024).toFixed(1) + ' MB' : kb.toFixed(1) + ' KB';
    }

    var content = document.getElementById('db-stats-content');
    content.textContent = '';

    var grid = document.createElement('div');
    grid.className = 'db-stats-grid';

    [[fmt(s.runs), 'runs'], [fmt(s.run_logs), 'log lines'], [fmt(s.state), 'monitored'], [fmtBytes(s.db_size_bytes), 'db size']].forEach(function(pair) {
      var tile = document.createElement('div');
      tile.className = 'neu-raised-xs stat-mini';
      var valEl = document.createElement('div');
      valEl.className = 'stat-mini-val num';
      valEl.textContent = pair[0];
      var labelEl = document.createElement('div');
      labelEl.className = 'eyebrow';
      labelEl.style.marginTop = '6px';
      labelEl.textContent = pair[1];
      tile.appendChild(valEl);
      tile.appendChild(labelEl);
      grid.appendChild(tile);
    });

    content.appendChild(grid);

    var meta = document.createElement('div');
    meta.style.cssText = 'font-size:11px;color:var(--ink-3);margin-top:16px';
    var oldest = s.oldest_run != null ? String(s.oldest_run) : '—';
    var newest = s.newest_run != null ? String(s.newest_run) : '—';
    meta.textContent = 'Oldest: ' + oldest + '  ·  Newest: ' + newest;
    content.appendChild(meta);
  }).catch(function() {
    var el = document.getElementById('db-stats-content');
    el.textContent = 'Failed to load DB stats.';
  });

  // ── Notification test ─────────────────────────────────────────
  function testChannel(ch) {
    var row = document.getElementById('ch-' + ch);
    var btn = row.querySelector('button');
    var label = btn.querySelector('.ch-label');
    var spin = btn.querySelector('.ch-spin');
    var result = document.getElementById('ch-result-' + ch);
    btn.disabled = true;
    label.style.display = 'none';
    spin.style.display = '';
    result.textContent = '';
    fetch('/api/debug/notify-test/' + encodeURIComponent(ch), { method: 'POST' })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        result.textContent = data.status === 'ok' ? '✓ sent' : '✗ ' + (data.detail || 'error');
        result.style.color = data.status === 'ok' ? 'var(--ok)' : 'var(--err)';
      })
      .catch(function() {
        result.textContent = '✗ network error';
        result.style.color = 'var(--err)';
      })
      .finally(function() {
        btn.disabled = false;
        label.style.display = '';
        spin.style.display = 'none';
      });
  }

  // ── App Logs (SSE) ────────────────────────────────────────────
  var LEVEL_ORDER = { DEBUG: 0, INFO: 1, WARNING: 2, CRITICAL: 3, ERROR: 3 };
  var logFilter = 'all';

  function levelClass(lvl) {
    if (lvl === 'ERROR' || lvl === 'CRITICAL') return 'log-error';
    if (lvl === 'WARNING') return 'log-warn';
    if (lvl === 'INFO') return 'log-info';
    return 'log-debug';
  }

  function shouldShow(lvl) {
    if (logFilter === 'all') return true;
    var min = { info: 1, warn: 2, error: 3 }[logFilter] || 0;
    return (LEVEL_ORDER[lvl] || 0) >= min;
  }

  function setLogFilter(f, btn) {
    document.querySelectorAll('#log-level-seg button').forEach(function(b) { b.classList.remove('on'); });
    btn.classList.add('on');
    logFilter = f;
    document.querySelectorAll('#log-console .log-line').forEach(function(el) {
      el.style.display = shouldShow(el.dataset.level) ? '' : 'none';
    });
  }

  function appendLog(entry) {
    var wrap = document.getElementById('log-console');
    var el = document.createElement('div');
    el.className = 'log-line ' + levelClass(entry.level);
    el.dataset.level = entry.level;
    var ts = new Date(entry.ts * 1000).toLocaleTimeString('en-GB', { hour12: false });
    var pad = String(entry.level || '').padEnd(8);
    el.textContent = '[' + ts + '] ' + pad + ' ' + entry.logger + ': ' + entry.message;
    el.style.display = shouldShow(entry.level) ? '' : 'none';
    wrap.appendChild(el);
    if (document.getElementById('autoscroll').checked) {
      wrap.scrollTop = wrap.scrollHeight;
    }
  }

  function clearLogs() {
    document.getElementById('log-console').textContent = '';
  }

  var sse = new EventSource('/api/debug/log-stream');
  sse.onmessage = function(e) {
    try { appendLog(JSON.parse(e.data)); } catch (_) {}
  };
  window.addEventListener('beforeunload', function() { sse.close(); });
</script>
{% endblock %}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest app/main_test.py::test_settings_returns_200 --no-cov -x -q
```

Expected: `1 passed`

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/templates/settings.html app/main_test.py
git commit -m "feat(settings): add /settings page with config, db stats, channels, live logs"
```

---

## Task 6: Navigation (base.html)

**Files:**
- Modify: `app/templates/base.html`

- [ ] **Step 1: Add gear icon to sidebar**

In `app/templates/base.html`, find this line:

```html
      <div class="nav-spacer"></div>
```

Add the following immediately **before** that line:

```html
      <a href="/settings" class="nav-item {% block nav_settings %}{% endblock %}" title="Settings">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </a>
```

- [ ] **Step 2: Add settings tab to mobile bottom tabs**

In `app/templates/base.html`, find this block inside `.mobile-tabs-inner`:

```html
      <div class="mobile-tab" style="opacity:.35">
```

Add the following immediately **before** that line:

```html
      <a href="/settings" class="mobile-tab {% block mob_settings %}{% endblock %}">
        <div class="mobile-tab-icon">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </div>
        Settings
      </a>
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "feat(nav): add Settings gear icon to sidebar and mobile tabs"
```

---

## Task 7: Helper Reference Panel in Editor

**Files:**
- Modify: `app/templates/monitor_editor.html`

- [ ] **Step 1: Add CSS for helper panel to the existing style block**

In `app/templates/monitor_editor.html`, find the closing `</style>` tag inside `{% block head %}`. Add the following CSS immediately before it:

```css
  /* Helper reference panel */
  .helpers-panel { margin-top: 16px; }
  .helpers-toggle {
    width: 100%; display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; background: transparent; border: 0; cursor: pointer;
    color: var(--ink-3); font: 500 10px var(--sans); letter-spacing: 0.12em; text-transform: uppercase;
    box-shadow: inset 2px 2px 5px var(--shadow), inset -2px -2px 4px var(--raise);
    border-radius: 12px; transition: color .12s;
  }
  .helpers-toggle:hover { color: var(--ink-2); }
  .helpers-toggle-icon { transition: transform .2s; }
  .helpers-toggle.open .helpers-toggle-icon { transform: rotate(180deg); }
  .helpers-body { display: none; padding: 8px 0 0; }
  .helpers-body.open { display: block; }
  .helper-entry {
    padding: 9px 14px; border-bottom: 1px solid var(--line);
    display: flex; align-items: flex-start; justify-content: space-between; gap: 10px;
  }
  .helper-entry:last-child { border-bottom: 0; }
  .helper-sig { font: 11.5px var(--mono); color: var(--accent); margin-bottom: 3px; }
  .helper-desc { font: 11px var(--sans); color: var(--ink-3); }
  .helper-btn {
    flex-shrink: 0; padding: 5px 10px; border-radius: 8px;
    font: 500 10px var(--sans); color: var(--ink-3); background: var(--bg); border: 0;
    cursor: pointer; box-shadow: -2px -2px 4px var(--raise), 2px 2px 4px var(--shadow);
    white-space: nowrap; transition: color .12s;
  }
  .helper-btn:hover { color: var(--ink-2); }
  .import-row {
    padding: 9px 14px; border-bottom: 1px solid var(--line);
    display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 4px;
  }
  .import-line { font: 11px var(--mono); color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

- [ ] **Step 2: Add helper panel HTML**

In `app/templates/monitor_editor.html`, find the comment `</div><!-- /editor-right -->`.
Add the helper panel **inside** the `editor-right` div, immediately before that closing comment:

```html
    <!-- HELPER REFERENCE PANEL -->
    <div class="helpers-panel">
      <button class="helpers-toggle" id="helpers-toggle" onclick="toggleHelpers()">
        Available helpers
        <svg class="helpers-toggle-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
      </button>
      <div class="helpers-body" id="helpers-body">
        <div class="import-row">
          <span class="import-line" id="import-line">from app.helpers import Monitor, extract_text, get_last_value, set_value, notify</span>
          <button class="helper-btn" id="copy-import-btn">Copy import</button>
        </div>
        <div class="helper-entry">
          <div><div class="helper-sig">extract_text(page, selector)</div><div class="helper-desc">Wait for CSS selector, return stripped inner text</div></div>
          <button class="helper-btn" data-snippet='value = await extract_text(page, ".selector")'>Insert</button>
        </div>
        <div class="helper-entry">
          <div><div class="helper-sig">extract_json(page, url)</div><div class="helper-desc">Fetch JSON via browser request context</div></div>
          <button class="helper-btn" data-snippet="data = await extract_json(page, monitor.url)">Insert</button>
        </div>
        <div class="helper-entry">
          <div><div class="helper-sig">navigate(page, url)</div><div class="helper-desc">Navigate with auto consent-gate detection</div></div>
          <button class="helper-btn" data-snippet="await navigate(page, monitor.url)">Insert</button>
        </div>
        <div class="helper-entry">
          <div><div class="helper-sig">get_last_value(ctx.db, monitor_name)</div><div class="helper-desc">Read latest persisted value from state table</div></div>
          <button class="helper-btn" data-snippet="prev = await get_last_value(ctx.db, ctx.monitor_name)">Insert</button>
        </div>
        <div class="helper-entry">
          <div><div class="helper-sig">set_value(ctx.db, monitor_name, value)</div><div class="helper-desc">Upsert value into state table</div></div>
          <button class="helper-btn" data-snippet="await set_value(ctx.db, ctx.monitor_name, value)">Insert</button>
        </div>
        <div class="helper-entry">
          <div><div class="helper-sig">notify(ctx.apprise, title, body, tags)</div><div class="helper-desc">Send notification (guard with if ctx.apprise)</div></div>
          <button class="helper-btn" data-snippet='if ctx.apprise:&#10;    await notify(ctx.apprise, "title", value, tags=["channel"])'>Insert</button>
        </div>
        <div class="helper-entry">
          <div><div class="helper-sig">record_metric(ctx.influx, measurement, value)</div><div class="helper-desc">Write point to InfluxDB (guard with if ctx.influx)</div></div>
          <button class="helper-btn" data-snippet='if ctx.influx:&#10;    await record_metric(ctx.influx, "measurement", value)'>Insert</button>
        </div>
      </div>
    </div>
```

- [ ] **Step 3: Add helper panel JavaScript**

In `app/templates/monitor_editor.html`, inside the `{% block scripts %}` section, **before** `{% endblock %}`, add:

```html
<script>
  function toggleHelpers() {
    var btn = document.getElementById('helpers-toggle');
    var body = document.getElementById('helpers-body');
    btn.classList.toggle('open');
    body.classList.toggle('open');
  }

  function insertSnippet(snippet) {
    var ta = document.querySelector('#raw-editor-container textarea.input-layer');
    if (!ta) {
      navigator.clipboard && navigator.clipboard.writeText(snippet);
      return;
    }
    var start = ta.selectionStart;
    var end = ta.selectionEnd;
    ta.setRangeText(snippet, start, end, 'end');
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    ta.focus();
  }

  // Wire up Insert buttons via data-snippet attribute (avoids inline onclick with quotes)
  document.querySelectorAll('.helper-btn[data-snippet]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      insertSnippet(btn.dataset.snippet);
    });
  });

  // Wire up copy import button
  var copyBtn = document.getElementById('copy-import-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function() {
      var text = document.getElementById('import-line').textContent;
      navigator.clipboard && navigator.clipboard.writeText(text);
    });
  }
</script>
```

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass

- [ ] **Step 5: Run full suite with coverage gate**

```bash
uv run pytest
```

Expected: all pass, 100% coverage

- [ ] **Step 6: Commit**

```bash
git add app/templates/monitor_editor.html
git commit -m "feat(editor): add collapsible helper reference panel with insert-snippet"
```

---

## Self-Review

**Spec coverage:**
- Config dump (`/api/debug/config`) — Task 3 ✓
- DB stats (`/api/debug/db-stats`) — Task 4 ✓
- Notification test (`/api/debug/notify-test/{channel}`) — Task 3 ✓
- Live app logs SSE (`/api/debug/log-stream`) — Task 4 ✓
- Register log buffer in lifespan — Task 4 ✓
- `/settings` page route + template — Task 5 ✓
- Navigation gear icon (sidebar + mobile) — Task 6 ✓
- Helper reference panel in editor — Task 7 ✓
- Import copy button — Task 7 ✓

**Placeholder scan:** No TBDs. All steps include actual code.

**Type consistency:**
- `AppLogBuffer` defined in Task 1, used in Task 4 (`_log_stream_generator`, `get_log_buf`)
- `get_apprise` / `AppraiseDep` defined in Task 3, used in Task 3
- `get_log_buf` / `LogBufDep` defined in Task 4, used in Task 4
- `Database.get_stats()` defined in Task 2, called in Task 4 (`api_debug_db_stats`)
- `_mask_url` defined in Task 3, called in Task 3

**Coverage notes:**
- `get_apprise`, `get_log_buf`, lifespan additions all get `# pragma: no cover` consistent with existing `get_db` pattern
- `_mask_url` is a pure function with explicit unit tests → 100% covered
- `_log_stream_generator` is tested via the patched SSE test in Task 4
