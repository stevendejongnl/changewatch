# SSE Live Refresh Design

**Date:** 2026-05-17  
**Status:** Approved

## Problem

The dashboard uses `<meta http-equiv="refresh" content="30">` — a blunt 30-second full-page reload regardless of whether anything changed. The Activity feed has a "Live" chip that is purely cosmetic. Both pages should update the moment a monitor run completes.

## Approach

Server-Sent Events (SSE). The server pushes a small event after every `Runner.run()` completes. Clients reload (dashboard) or prepend a row (activity) on receipt. `EventSource` handles reconnection automatically.

WebSockets were ruled out (server-only push, no bidirectional need). Partial DOM diffing on the dashboard was ruled out (complexity without meaningful UX gain).

## Architecture

### `app/events.py` — EventBus

A module-level singleton with a `set[asyncio.Queue]`.

```
subscribe() → asyncio.Queue   # adds queue to set, returns it
publish(event: dict) → None   # puts event onto every queue in the set
unsubscribe(queue) → None     # removes queue from set
```

No persistence. Events are fire-and-forget; a client that connects after a run misses that event (acceptable — they'll see the result on next run or reload).

### `app/main.py` — SSE endpoint

```
GET /api/events
Content-Type: text/event-stream
Cache-Control: no-cache
```

- Calls `bus.subscribe()` to get a queue
- Loops: `await queue.get()` → format as `data: <json>\n\n` → yield
- `try/finally`: calls `bus.unsubscribe(queue)` on disconnect
- Returns `StreamingResponse` with `media_type="text/event-stream"`

Event payload (minimal):
```json
{"monitor_name": "example_price", "status": "ok", "ran_at": "2026-05-17 14:23:01"}
```

`ran_at` is set to `datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")` at publish time in `runner.py` — the same format already used in the `runs` table and by the `localtime` Jinja filter.

### `app/runner.py` — publish after each run

`Runner.__init__` gains an optional `event_bus: EventBus | None = None` parameter. After `record_run` in both the success and error branches, if `event_bus` is set:

```python
await self._event_bus.publish({
    "monitor_name": monitor.name,
    "status": status,   # "ok" | "changed" | "error"
    "ran_at": ...,      # ISO timestamp string from record_run
})
```

Existing tests pass `event_bus=None` (the default) — no changes required to test setup.

`main.py` lifespan passes the global `EventBus` instance when constructing `Runner` instances inside `Scheduler`.

## Frontend

### Dashboard (`dashboard.html`)

- Remove `<meta http-equiv="refresh" content="30">` from `{% block head %}`
- Update subtitle: `"{{ monitors | length }} monitors · live"` (remove "auto-refresh every 30s")
- Add to `{% block scripts %}`:

```js
const evtSource = new EventSource('/api/events');
evtSource.onmessage = () => location.reload();
evtSource.onopen    = () => setConn(true);
evtSource.onerror   = () => setConn(false);

function setConn(ok) {
  const dot   = document.querySelector('.conn-dot');
  const label = document.querySelector('.conn-indicator');
  if (!dot || !label) return;
  dot.style.background   = ok ? 'var(--ok)'  : 'var(--ink-4)';
  dot.style.boxShadow    = ok ? '0 0 6px var(--ok-glow)' : 'none';
  label.lastChild.textContent = ok ? ' connected' : ' reconnecting…';
}
```

The `.conn-indicator` and `.conn-dot` elements already exist in the template — no HTML changes needed.

### Activity feed (`activity.html`)

- Add `EventSource` on page load
- On `message`: if the page is at offset 0 (detected via `new URLSearchParams(location.search).get('offset')`), prepend a new `.activity-row` to `#activity-feed` built from the event JSON. If offset > 0, skip (user is paginated — don't inject rows out of context)
- Wire the existing "Live" chip dot to SSE connection state (same `setConn` pattern)

New row HTML is built client-side from the event payload fields: `monitor_name`, `status`, `ran_at`. The row links to `/monitors/<name>` and uses the existing CSS classes (`led`, `act-time`, `act-name`, `chip`).

## Error Handling

- SSE disconnects: `EventSource` reconnects automatically with exponential backoff — no manual retry needed
- Slow clients / long-running monitors: each client has its own `asyncio.Queue` — a slow client only blocks itself, not the bus or other clients
- Server restart: client `onerror` fires, dot goes grey, auto-reconnect restores on next server start

## Testing

- `EventBus`: unit tests for `subscribe`, `publish` (events reach all queues), `unsubscribe` (disconnected client removed)
- `GET /api/events`: integration test with `httpx.AsyncClient` using `iter_lines()` — publish an event, assert the formatted SSE line appears in the stream
- `Runner.run()` with `event_bus` set: assert `bus.publish` is called with the correct payload after a successful run and after an error run
- Frontend: not unit-tested — covered by existing Playwright smoke tests on the running app

## Files Changed

| File | Change |
|------|--------|
| `app/events.py` | **New** — `EventBus` class |
| `app/events_test.py` | **New** — unit tests |
| `app/main.py` | Add `/api/events` endpoint; pass bus to `Scheduler`/`Runner` |
| `app/main_test.py` | Add SSE endpoint test |
| `app/runner.py` | Add `event_bus` param; publish after `record_run` |
| `app/runner_test.py` | Add publish assertions |
| `app/scheduler.py` | Thread bus through to `Runner` construction |
| `app/scheduler_test.py` | Update if needed |
| `app/templates/dashboard.html` | Remove meta refresh; add EventSource JS; wire conn-indicator |
| `app/templates/activity.html` | Add EventSource JS; wire Live chip; prepend rows |
