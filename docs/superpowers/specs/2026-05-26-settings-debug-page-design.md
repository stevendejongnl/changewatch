# Settings & Debug Page Design

**Date:** 2026-05-26  
**Status:** Approved

## Overview

Two features:
1. A `/settings` debug page with live app logs, DB stats, config dump, and notification channel testing.
2. A helper reference panel in the monitor editor with click-to-insert snippets.

## Feature 1: `/settings` Debug Page

### Route & Navigation

- `GET /settings` → renders `app/templates/settings.html` (extends `base.html`)
- Gear icon added to sidebar nav (between Activity and nav-spacer)
- Gear icon added to mobile bottom tabs
- `{% block nav_settings %}` / `{% block mob_settings %}` follow the existing active-class pattern

### Layout

Single scrollable page with 4 sections stacked vertically, each a `neu-raised-sm` card.

### Section 1: Config

API: `GET /api/debug/config` → JSON object

Fields returned:
- `display_tz` — value of `DISPLAY_TZ` env var
- `monitors_dir` — resolved `MONITORS_DIR` path (str)
- `db_path` — `DB_PATH`
- `git_repo_url` — `MONITORS_REPO_URL`, last 8 chars visible, rest masked (`****...abcd1234`); empty string if not set
- `git_sync_interval` — `MONITORS_REPO_SYNC_INTERVAL`
- `git_enabled` — bool
- `channels` — list of channel names from `APPRISE_URL_*` env vars (names only, no URLs)

Rendered as a two-column key/value table using `neu-inset` cells.

### Section 2: DB Stats

API: `GET /api/debug/db-stats` → JSON object

Fields:
- `runs` — row count in `runs` table
- `run_logs` — row count in `run_logs` table
- `state` — row count in `state` table
- `monitor_config` — row count in `monitor_config` table
- `db_size_bytes` — file size from `os.path.getsize(DB_PATH)`
- `oldest_run` — `MIN(ran_at)` from `runs`
- `newest_run` — `MAX(ran_at)` from `runs`

Rendered as stat tiles (reuse `neu-raised-xs` cards, smaller than dashboard tiles).

### Section 3: Notification Channels

API: `POST /api/debug/notify-test/{channel}` → `{"status": "ok"}` or `{"status": "error", "detail": "..."}`

The settings page loads channel names from `GET /api/debug/config` (`channels` key = list of channel names, URLs not exposed).
Each channel row: name chip + "Test" button. On click: button shows spinner, then ✓ or ✗ with color feedback. No page reload.

The test notification sends title `"changewatch test"` and body `"Notification channel is working."`.

### Section 4: App Logs (Live SSE)

#### Backend: `app/log_stream.py`

New module, singleton `AppLogBuffer`:

```python
class AppLogBuffer(logging.Handler):
    def __init__(self, maxlen: int = 500): ...
    def emit(self, record): ...        # stores in deque + put_nowait to queues
    def subscribe(self) -> asyncio.Queue: ...
    def unsubscribe(self, q): ...
    def get_history(self) -> list[dict]: ...  # returns deque snapshot
```

Record dict shape: `{"level": str, "logger": str, "message": str, "ts": float}`

`emit()` uses `q.put_nowait()` — safe to call from any thread (Python logging is synchronous).

Singleton exposed via `get_log_buffer() -> AppLogBuffer`.

#### Registration

In `main.py` lifespan (inside the `asynccontextmanager`, before yield):
```python
_log_buf = get_log_buffer()
_log_buf.setLevel(logging.INFO)
logging.getLogger().addHandler(_log_buf)
```

This catches all INFO+ records from uvicorn, apscheduler, and any app code.
Monitor-run loggers use `propagate=False` so they don't duplicate here.

#### SSE Endpoint

`GET /api/debug/log-stream`

On connect:
1. Yield all records from `get_history()` as SSE events
2. Subscribe to new records, yield indefinitely

SSE format: `data: <json>\n\n`

#### UI

Console-style `div` with fixed height (~320px), overflow-y scroll, monospace font.
Level coloring via CSS classes: `log-error` (var(--err)), `log-warning` (var(--chg)), `log-info` (var(--ink-2)), `log-debug` (var(--ink-4)).

Controls:
- Auto-scroll toggle (default on) — checkbox that keeps the console scrolled to bottom
- Clear button — clears client-side display only (not the server buffer)
- Level filter — segmented control: ALL / INFO+ / WARN+ / ERROR

On page load: connect to SSE, populate from history, then stream.

## Feature 2: Helper Reference Panel in Editor

### Location

`app/templates/monitor_editor.html` — added below the code editor in both modes:
- Form mode: below the code preview panel (right column)
- Custom file mode: below the full-width raw editor

### Data

Static — hardcoded in the template (helpers are stable, no runtime reflection needed).

### Structure

Collapsible section with eyebrow label "Available helpers". Default: collapsed.

Each helper entry (7 total):

| Helper | Snippet inserted |
|---|---|
| `extract_text(page, selector)` | `await extract_text(page, "selector")` |
| `extract_json(page, url)` | `await extract_json(page, url)` |
| `navigate(page, url)` | `await navigate(page, monitor.url)` |
| `get_last_value(ctx.db, name)` | `prev = await get_last_value(ctx.db, ctx.monitor_name)` |
| `set_value(ctx.db, name, value)` | `await set_value(ctx.db, ctx.monitor_name, value)` |
| `notify(ctx.apprise, title, body, tags)` | `if ctx.apprise:\n    await notify(ctx.apprise, "title", value, tags=["channel"])` |
| `record_metric(ctx.influx, measurement, value)` | `if ctx.influx:\n    await record_metric(ctx.influx, "measurement", value)` |

Each entry shows: function name (monospace), one-line description, "Insert" button.
"Insert" uses `textarea.setRangeText()` to insert at current cursor position, then dispatches `input` event to trigger any listeners (e.g. live preview).

### Import reminder

Panel also shows the import line that must be at the top of the file:
```python
from app.helpers import Monitor, extract_text, get_last_value, set_value, notify
```
With a copy button.

## Testing

- `GET /api/debug/config` — unit test covers masking logic and git_enabled flag
- `GET /api/debug/db-stats` — unit test against a real in-memory SQLite DB
- `POST /api/debug/notify-test/{channel}` — mock AppriseClient, verify send called
- `GET /api/debug/log-stream` — unit test: emit record to buffer, consume from SSE generator
- `AppLogBuffer` — unit test: capacity, subscribe/unsubscribe, history snapshot
- Settings page HTML — route test (200 + HTML response)
- Helper panel — no backend tests; covered by existing editor tests

## Files Changed

| File | Change |
|---|---|
| `app/log_stream.py` | New — `AppLogBuffer`, `get_log_buffer()` |
| `app/main.py` | Add `/settings`, `/api/debug/*` routes; register log buffer in lifespan |
| `app/db.py` | Add `get_stats()` method returning table row counts |
| `app/templates/settings.html` | New template |
| `app/templates/base.html` | Add gear nav item to sidebar + mobile tabs |
| `app/templates/monitor_editor.html` | Add helper reference panel |
| `app/log_stream_test.py` | New test file |
| `app/main_test.py` | Add tests for new debug endpoints + settings route |
