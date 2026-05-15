# Debug / Activity Pages Design

**Date:** 2026-05-15
**Status:** Approved

## Context

The dashboard shows the latest run per monitor but nothing more. When a monitor fails it's hard to understand why — the error cell truncates, there's no history, and there are no log lines from the monitor script itself. This design adds a per-monitor detail page and a global activity feed, backed by per-line log capture stored in SQLite.

## Goals

- See the full run history for any monitor (last 50 runs)
- Read Python `ctx.logger` output per run (level + message + timestamp)
- Trigger a run from the detail page and see the result without navigating away
- See a chronological stream of all monitors' runs on one global page

## Schema

New table added to `db.py::Database.init()`:

```sql
CREATE TABLE IF NOT EXISTS run_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    level      TEXT NOT NULL,   -- INFO / WARNING / ERROR etc.
    message    TEXT NOT NULL,
    logged_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

No changes to the existing `runs` or `state` tables.

## Log Capture

`Runner.run()` in `runner.py` attaches a custom `logging.Handler` to the monitor's logger before calling `monitor.fn(page, ctx)`. The handler buffers `(level, message, logged_at)` tuples in memory. After the run completes — whether ok or error — it writes the buffer to `run_logs` using the `run_id` returned by `db.record_run()`.

`db.record_run()` must return the inserted row's `lastrowid` so the runner can reference it when writing logs.

The custom handler is removed from the logger after each run (no leaking handlers across runs).

## New DB Methods

- `db.record_run(...) -> int` — existing method, return type changes from `None` to `int` (the new run's id)
- `db.get_runs_with_logs(monitor_name, limit=50) -> list[dict]` — returns runs joined with their log lines, ordered by run descending
- `db.get_all_runs(limit=50) -> list[dict]` — returns all runs across all monitors ordered by `ran_at` descending (for the activity feed); no logs joined here (kept lean)
- `db.get_run_logs(run_id) -> list[dict]` — returns log lines for a single run (used by the JSON API)

## New Routes

All added to `main.py`:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/monitors/{name}` | Server-rendered detail page (Jinja) |
| `GET` | `/activity` | Server-rendered global feed (Jinja) |
| `GET` | `/api/monitors/{name}/runs` | JSON: recent runs + logs; used by JS poll |

`/monitors/{name}` returns 404 if the monitor name is not in `discover_monitors()`.

## Templates

### `templates/monitor_detail.html`

Sections:
- Header: monitor name, schedule, current status badge, "Run now" button
- Run history table (last 50): `ran_at`, status badge, duration, last_value, error message
- Each row is expandable — click reveals log lines from `run_logs` for that run (loaded inline from the server-rendered template, not via AJAX)
- "Run now" JS: `POST /monitors/{name}/run` → polls `GET /api/monitors/{name}/runs` every second → when a new `run_id` appears, re-renders the top row without a full page reload

### `templates/activity.html`

Sections:
- Header: "Activity" title + monitor filter dropdown + status filter dropdown (client-side JS filtering of rendered rows — no extra API calls)
- Feed rows (last 50 runs, all monitors): `ran_at`, monitor name as link to detail page, status badge, error/value snippet, duration
- "Load more" link: `?offset=50` query param, server returns next 50

## Dashboard Changes

- Monitor name cells become `<a href="/monitors/{{ m.monitor_name }}">` links
- "Activity" link added to the header bar next to "Sync monitors"

## Interactions

### Run now → poll

```
click "Run now"
  → POST /monitors/{name}/run  (202 Accepted, returns {queued: name})
  → JS records current latest run_id
  → polls GET /api/monitors/{name}/runs every 1s
  → when new run_id appears, inserts new row at top of table (status + logs)
  → stops polling
```

### Log expansion

Log lines are rendered server-side inside a `<details>` element per run row. No AJAX needed — the full log is in the HTML, collapsed by default, expanded on click. Latest error run starts expanded.

## Testing

- `db_test.py`: new tests for `get_runs_with_logs`, `get_all_runs`, `get_run_logs`, and `record_run` returning an int
- `runner_test.py`: new test asserting that log lines emitted by `ctx.logger` during a run are persisted to `run_logs`
- `main_test.py`: route tests for `/monitors/{name}` (200, 404), `/activity` (200), `/api/monitors/{name}/runs` (JSON shape)
- 100% coverage gate must stay green

## Out of Scope

- Live streaming (SSE/WebSocket) — trigger-and-poll is sufficient
- Log level filtering on the detail page — all levels shown inline
- Deleting runs or clearing history
