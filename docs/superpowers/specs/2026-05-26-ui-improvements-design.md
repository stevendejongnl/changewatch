# changewatch UI Improvements — Design Spec

**Date:** 2026-05-26

## Scope

Eight improvements to changewatch:

1. Remove disabled sign-out nav button
2. Implement pause/resume for monitors (cron skipped; manual run always works)
3. Dashboard SSE in-place card updates (no full page reload)
4. Avg duration metric in monitor detail
5. Last changed timestamp per monitor
6. Human-readable cron labels via `cron-descriptor`
7. Run history pagination (load more)
8. Dashboard shows paused state

---

## 1. Data Layer

### New `monitor_config` table

Added in `db.py::Database.init()` alongside existing tables:

```sql
CREATE TABLE IF NOT EXISTS monitor_config (
    monitor_name TEXT PRIMARY KEY,
    paused       INTEGER NOT NULL DEFAULT 0,
    changed_at   TEXT
);
```

`changed_at` is updated by `Runner` when a new value differs from the previous stored value.

### New DB methods

| Method | Signature | Purpose |
|--------|-----------|---------|
| `set_paused` | `(name: str, paused: bool) → None` | Upsert paused flag |
| `set_changed_at` | `(name: str) → None` | Upsert `changed_at = datetime('now')` |
| `get_config` | `(name: str) → dict` | Fetch single monitor_config row |
| `get_all_configs` | `() → dict[str, dict]` | All configs keyed by monitor name |

### Updated query

`get_all_monitor_states()` updated to LEFT JOIN `monitor_config` so `paused` and `changed_at` are returned in the same query used by the dashboard.

---

## 2. Scheduler + API

### Pause check in cron jobs

`Scheduler` wraps cron job callbacks with a pause check:

```python
async def _run_job(monitor):
    config = await self._db.get_config(monitor.name)
    if config.get("paused"):
        return  # skip silently
    await runner.run(monitor, page)
```

Manual trigger (`POST /monitors/{name}/run`) calls `runner.run()` directly — bypasses pause check, always executes.

### New API endpoints

```
POST /monitors/{name}/pause   → db.set_paused(name, True)   → 204
POST /monitors/{name}/resume  → db.set_paused(name, False)  → 204
```

Both publish an SSE event:

```json
{"event": "paused", "monitor_name": "...", "paused": true}
```

### Runner change

After `set_value()`, if the new value differs from the previous value, call `db.set_changed_at(name)`.

---

## 3. SSE Enrichment + Dashboard In-Place Updates

### Richer run event payload

`Runner` currently publishes `{"event": "run"}`. Updated to:

```json
{
  "event": "run",
  "monitor_name": "example_price",
  "status": "ok",
  "last_value": "€ 29.99",
  "error": null,
  "ran_at": "2026-05-26T14:30:00+02:00",
  "duration_ms": 412
}
```

### Dashboard JS

Replaces `location.reload()`:

```js
src.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.event === "run")    updateCard(data);
    if (data.event === "paused") updatePauseChip(data);
};
```

`updateCard(data)` targets the card via `data-monitor` attribute and updates:
- LED class (`ok` / `error` / `changed` / `paused`)
- `data-status` attribute (filter buttons continue to work)
- Value well content
- Footer timestamp + duration
- Status chip text + class

Stat strip counters (healthy / changed / failing / pending) recomputed from live card `data-status` values after each update.

### Monitor detail page

Pause/resume SSE event updates the button label + style live without reload. "Run now" polling behavior unchanged.

---

## 4. UI

### Remove disabled nav button

Delete the disabled sign-out `<div class="nav-item">` from `base.html` (same pattern as the bell icon removed previously).

### Human-readable cron labels

Add `cron-descriptor` as a dependency (`uv add cron-descriptor`).

Register a Jinja2 filter `humanize_cron` in `main.py`. Renders below the raw cron expression in both dashboard cards and the monitor detail topbar:

```
*/30 * * * *
every 30 minutes      ← muted eyebrow style
```

### Monitor detail stat strip

Current 4 tiles: schedule / status / success rate / total runs.

Add:
- **Avg duration** tile — `SELECT ROUND(AVG(duration_ms)) FROM runs WHERE monitor_name = ?`
- **Last changed** — shown as a sub-line inside the status tile (`changed_at` from `monitor_config`)

### Pause/Resume button

Currently a disabled stub in the monitor detail topbar. Wired to `POST /monitors/{name}/pause|resume`. Button label and style toggle between "Pause" and "Resume". Paused monitors show a `paused` LED/chip in the dashboard card header.

### Run history pagination

Default: load 50 runs (already the case). Add "Load more" button at the bottom of `#runs-list`:

```
GET /api/monitors/{name}/runs?offset=50&limit=50
```

Appends rows to the existing list. `get_runs_with_logs` needs an `offset: int = 0` parameter added alongside the existing `limit`.

---

## Dependencies

- `cron-descriptor` — pure Python, no transitive deps

## Files Touched

| File | Change |
|------|--------|
| `app/db.py` | New `monitor_config` table + 4 methods; update `get_all_monitor_states` |
| `app/runner.py` | Publish richer SSE event; call `set_changed_at` on value change |
| `app/scheduler.py` | Pause check in cron callback |
| `app/main.py` | Pause/resume endpoints; `humanize_cron` Jinja filter |
| `app/templates/base.html` | Remove sign-out button |
| `app/templates/dashboard.html` | In-place SSE updates; paused chip; cron human label |
| `app/templates/monitor_detail.html` | Pause button wired; avg duration + changed_at tiles; cron label; pagination |
| `app/db_test.py` | Tests for new DB methods |
| `app/runner_test.py` | Test richer SSE payload; test `set_changed_at` call |
| `app/scheduler_test.py` | Test pause check skips cron; test manual run bypasses pause |
| `app/main_test.py` | Test pause/resume endpoints |
| `pyproject.toml` | Add `cron-descriptor` |
