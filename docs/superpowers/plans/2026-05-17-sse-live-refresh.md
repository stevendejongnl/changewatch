# SSE Live Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 30-second meta-refresh with SSE push events so the dashboard reloads and the activity feed prepends rows the moment a monitor run completes.

**Architecture:** A module-level `EventBus` (`app/events.py`) holds a set of per-client `asyncio.Queue`s. `Runner.run()` publishes a completion event after every `record_run` call. A new `GET /api/events` SSE endpoint streams queued events to connected clients. The dashboard reloads on any event; the activity feed prepends a new row.

**Tech Stack:** FastAPI `StreamingResponse`, `asyncio.Queue`, vanilla `EventSource` JS API (no libraries)

---

## File Map

| File | Change |
|------|--------|
| `app/events.py` | **New** — `EventBus` class + module singleton + `get_event_bus` dep |
| `app/events_test.py` | **New** — unit tests for EventBus |
| `app/runner.py` | Add `event_bus` optional param; publish after `record_run` |
| `app/runner_test.py` | Add publish assertions (mock bus) |
| `app/scheduler.py` | Add `event_bus` param; thread through to `Runner` |
| `app/main.py` | Add `GET /api/events` endpoint; wire bus into `Scheduler` |
| `app/main_test.py` | SSE stream test + HTML assertion tests |
| `app/templates/dashboard.html` | Remove meta refresh; add `EventSource` JS; wire conn-indicator |
| `app/templates/activity.html` | Add `EventSource` JS; wire Live chip; prepend rows |

---

## Task 1: EventBus module

**Files:**
- Create: `app/events.py`
- Create: `app/events_test.py`

- [ ] **Step 1: Write the failing tests**

Create `app/events_test.py`:

```python
import asyncio
import pytest
from app.events import EventBus


async def test_subscribe_returns_queue():
    bus = EventBus()
    q = bus.subscribe()
    assert isinstance(q, asyncio.Queue)


async def test_publish_puts_event_on_all_queues():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    event = {"monitor_name": "mon", "status": "ok"}
    await bus.publish(event)
    assert q1.get_nowait() == event
    assert q2.get_nowait() == event


async def test_unsubscribe_removes_queue():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    await bus.publish({"x": 1})
    assert q.empty()


async def test_publish_with_no_subscribers_does_not_raise():
    bus = EventBus()
    await bus.publish({"x": 1})  # must not raise


async def test_unsubscribe_unknown_queue_does_not_raise():
    bus = EventBus()
    q = asyncio.Queue()
    bus.unsubscribe(q)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest app/events_test.py -x -q --no-cov
```

Expected: `ModuleNotFoundError: No module named 'app.events'`

- [ ] **Step 3: Implement EventBus**

Create `app/events.py`:

```python
import asyncio


class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        return q

    async def publish(self, event: dict) -> None:
        for q in list(self._queues):
            await q.put(event)

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest app/events_test.py -x -q --no-cov
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add app/events.py app/events_test.py
git commit -m "feat: add EventBus for SSE push notifications"
```

---

## Task 2: Runner publishes completion events

**Files:**
- Modify: `app/runner.py`
- Modify: `app/runner_test.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `app/runner_test.py`:

```python
async def test_runner_publishes_event_on_success(db, browser):
    from unittest.mock import AsyncMock
    from app.events import EventBus

    bus = EventBus()
    bus.publish = AsyncMock()

    m = Monitor(name="pub_ok_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        pass

    runner = Runner(db=db, browser=browser, event_bus=bus)
    await runner.run(m)

    bus.publish.assert_called_once()
    payload = bus.publish.call_args[0][0]
    assert payload["monitor_name"] == "pub_ok_mon"
    assert payload["status"] == "ok"
    assert "ran_at" in payload
    assert payload["duration_ms"] >= 0


async def test_runner_publishes_event_on_error(db, browser):
    from unittest.mock import AsyncMock
    from app.events import EventBus

    bus = EventBus()
    bus.publish = AsyncMock()

    m = Monitor(name="pub_err_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        raise RuntimeError("boom")

    runner = Runner(db=db, browser=browser, event_bus=bus)
    await runner.run(m)

    bus.publish.assert_called_once()
    payload = bus.publish.call_args[0][0]
    assert payload["monitor_name"] == "pub_err_mon"
    assert payload["status"] == "error"
    assert payload["error"] == "boom"
    assert "ran_at" in payload


async def test_runner_skips_publish_when_no_bus(db, browser):
    m = Monitor(name="no_bus_mon", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def check(page, ctx):
        pass

    runner = Runner(db=db, browser=browser)  # no event_bus
    await runner.run(m)  # must not raise

    runs = await db.get_recent_runs("no_bus_mon")
    assert runs[0]["status"] == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest app/runner_test.py::test_runner_publishes_event_on_success app/runner_test.py::test_runner_publishes_event_on_error app/runner_test.py::test_runner_skips_publish_when_no_bus -x -q --no-cov
```

Expected: `TypeError: Runner.__init__() got an unexpected keyword argument 'event_bus'`

- [ ] **Step 3: Update runner.py**

Add `from datetime import datetime` to the imports at the top of `app/runner.py`.

Extend the `TYPE_CHECKING` block:

```python
if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.events import EventBus
    from app.influx import InfluxClient
```

Update `Runner.__init__`:

```python
def __init__(
    self,
    db: Database,
    browser: Any,
    apprise: Optional["AppriseClient"] = None,
    influx: Optional["InfluxClient"] = None,
    event_bus: Optional["EventBus"] = None,
) -> None:
    self._db = db
    self._browser = browser
    self._apprise = apprise
    self._influx = influx
    self._event_bus = event_bus
```

In the `try` branch of `Runner.run`, after `await self._db.write_run_logs(run_id, log_buffer.lines)`, add:

```python
            if self._event_bus is not None:
                await self._event_bus.publish({
                    "monitor_name": monitor.name,
                    "status": status,
                    "ran_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_value": last_value,
                    "duration_ms": duration_ms,
                    "error": None,
                })
```

In the `except` branch of `Runner.run`, after `await self._db.write_run_logs(run_id, log_buffer.lines)`, add:

```python
            if self._event_bus is not None:
                await self._event_bus.publish({
                    "monitor_name": monitor.name,
                    "status": "error",
                    "ran_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_value": None,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                })
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest app/runner_test.py -x -q --no-cov
```

Expected: all runner tests pass

- [ ] **Step 5: Commit**

```bash
git add app/runner.py app/runner_test.py
git commit -m "feat(runner): publish SSE event after each run completes"
```

---

## Task 3: Thread EventBus through Scheduler

**Files:**
- Modify: `app/scheduler.py`

No new tests needed — all existing scheduler tests construct `Scheduler` without `event_bus`, which continues to work via the `None` default.

- [ ] **Step 1: Run existing scheduler tests to confirm baseline**

```
uv run pytest app/scheduler_test.py -x -q --no-cov
```

Expected: all pass

- [ ] **Step 2: Update scheduler.py**

Add import at the top of `app/scheduler.py`:

```python
from app.events import EventBus
```

Update `Scheduler.__init__` signature and body:

```python
def __init__(
    self,
    monitors_dir: Path,
    db: Database,
    apprise: Optional["AppriseClient"] = None,
    timezone: str = "UTC",
    event_bus: Optional[EventBus] = None,
) -> None:
    self._monitors_dir = monitors_dir
    self._db = db
    self._apprise = apprise
    self._timezone = timezone
    self._event_bus = event_bus
    self._browser: Any = None
    self._scheduler = AsyncIOScheduler()
    self._monitors: list[Monitor] = []
```

In `start()`, replace:
```python
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise)
```
with:
```python
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise, event_bus=self._event_bus)
```

In `reload()`, replace both occurrences of:
```python
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise)
```
with:
```python
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise, event_bus=self._event_bus)
```

In `trigger()`, replace:
```python
        runner = Runner(db=self._db, browser=browser, apprise=self._apprise)
```
with:
```python
        runner = Runner(db=self._db, browser=browser, apprise=self._apprise, event_bus=self._event_bus)
```

- [ ] **Step 3: Run tests to verify nothing broken**

```
uv run pytest app/scheduler_test.py -x -q --no-cov
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add app/scheduler.py
git commit -m "feat(scheduler): thread EventBus through to Runner"
```

---

## Task 4: SSE endpoint in main.py

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write the failing test**

Add to `app/main_test.py`:

```python
async def test_api_events_streams_published_event():
    import asyncio
    import json
    from app.events import EventBus, get_event_bus

    bus = EventBus()
    app.dependency_overrides[get_event_bus] = lambda: bus

    lines: list[str] = []

    async def consume():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            async with c.stream("GET", "/api/events") as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]
                async for raw in resp.aiter_lines():
                    if raw.startswith("data:"):
                        lines.append(raw)
                        return

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await bus.publish({"monitor_name": "test_mon", "status": "ok", "ran_at": "2026-01-01 00:00:00"})
    await asyncio.wait_for(consumer, timeout=2.0)

    app.dependency_overrides.clear()
    assert len(lines) == 1
    payload = json.loads(lines[0][len("data: "):])
    assert payload["monitor_name"] == "test_mon"
    assert payload["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest app/main_test.py::test_api_events_streams_published_event -x -q --no-cov
```

Expected: `FAILED` — route not found (404)

- [ ] **Step 3: Update main.py**

Add to the imports at the top of `app/main.py`:

```python
import json as _json

from app.events import EventBus, get_event_bus
```

Add a dependency alias after the existing `GitSyncDep` line:

```python
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
```

Add the async generator and endpoint before `@app.get("/healthz")`:

```python
async def _event_stream(bus: EventBus):
    queue = bus.subscribe()
    try:
        while True:
            event = await queue.get()
            yield f"data: {_json.dumps(event)}\n\n"
    finally:
        bus.unsubscribe(queue)


@app.get("/api/events")
async def events(bus: EventBusDep):
    return StreamingResponse(
        _event_stream(bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

In the `lifespan` function, update the `Scheduler(...)` call to wire the bus in. Replace:

```python
    _scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db, apprise=AppriseClient(), timezone=DISPLAY_TZ)
```

with:

```python
    _scheduler = Scheduler(monitors_dir=MONITORS_DIR, db=_db, apprise=AppriseClient(), timezone=DISPLAY_TZ, event_bus=get_event_bus())
```

- [ ] **Step 4: Run the new test**

```
uv run pytest app/main_test.py::test_api_events_streams_published_event -x -q --no-cov
```

Expected: `1 passed`

- [ ] **Step 5: Run full main test suite**

```
uv run pytest app/main_test.py -x -q --no-cov
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat: add GET /api/events SSE endpoint"
```

---

## Task 5: Dashboard frontend — remove meta refresh, add EventSource

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `app/main_test.py`:

```python
async def test_dashboard_has_no_meta_refresh(client):
    response = await client.get("/")
    assert 'http-equiv="refresh"' not in response.text


async def test_dashboard_has_eventsource_script(client):
    response = await client.get("/")
    assert "EventSource" in response.text


async def test_dashboard_subtitle_does_not_mention_auto_refresh(client):
    response = await client.get("/")
    assert "auto-refresh" not in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest app/main_test.py::test_dashboard_has_no_meta_refresh app/main_test.py::test_dashboard_has_eventsource_script app/main_test.py::test_dashboard_subtitle_does_not_mention_auto_refresh -x -q --no-cov
```

Expected: `FAILED` — meta refresh tag present, EventSource absent

- [ ] **Step 3: Update dashboard.html**

**Remove** line 8 entirely:
```html
<meta http-equiv="refresh" content="30">
```

**Update** the subtitle text in `{% block topbar %}` from:
```html
  <div class="topbar-sub">{{ monitors | length }} monitors · auto-refresh every 30s</div>
```
to:
```html
  <div class="topbar-sub">{{ monitors | length }} monitors · live</div>
```

**Replace** the entire `{% block scripts %}` section with:

```html
{% block scripts %}
<script>
  function filterMonitors(status, btn) {
    document.querySelectorAll('.seg button').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    document.querySelectorAll('#monitor-grid .neu-raised').forEach(card => {
      card.style.display = (status === 'all' || card.dataset.status === status) ? '' : 'none';
    });
  }

  async function runMonitor(name) {
    const wrap = document.getElementById('run-wrap-' + name);
    if (!wrap) return;
    const btn = wrap.querySelector('button');
    btn.disabled = true;
    wrap.classList.add('loading');
    try {
      const res = await fetch('/monitors/' + name + '/run', { method: 'POST' });
      if (res.ok) {
        btn.style.color = 'var(--ok)';
        setTimeout(() => location.reload(), 2000);
      } else {
        btn.style.color = 'var(--err)';
        btn.disabled = false;
        wrap.classList.remove('loading');
      }
    } catch (_) {
      btn.style.color = 'var(--err)';
      btn.disabled = false;
      wrap.classList.remove('loading');
    }
  }

  {% if git_sync_enabled %}
  async function syncMonitors() {
    const btn = document.getElementById('sync-btn');
    const label = document.getElementById('sync-label');
    const err = document.getElementById('sync-error');
    btn.disabled = true;
    label.textContent = 'Syncing…';
    err.textContent = '';
    try {
      const res = await fetch('/sync', { method: 'POST' });
      if (res.ok) {
        location.reload();
      } else {
        const data = await res.json().catch(() => ({}));
        err.textContent = data.detail || 'Sync failed';
        btn.disabled = false;
        label.textContent = 'Sync';
      }
    } catch (_) {
      err.textContent = 'Network error';
      btn.disabled = false;
      label.textContent = 'Sync';
    }
  }
  {% endif %}

  (function () {
    const indicator = document.querySelector('.conn-indicator');
    const dot = indicator && indicator.querySelector('.conn-dot');

    function setConn(ok) {
      if (!dot || !indicator) return;
      dot.style.background = ok ? '' : 'var(--ink-4)';
      dot.style.boxShadow  = ok ? '' : 'none';
      // Walk child nodes to find the text node and update it
      indicator.childNodes.forEach(node => {
        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
          node.textContent = ok ? ' connected' : ' reconnecting…';
        }
      });
    }

    const src = new EventSource('/api/events');
    src.onmessage = () => location.reload();
    src.onopen    = () => setConn(true);
    src.onerror   = () => setConn(false);
  })();
</script>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest app/main_test.py::test_dashboard_has_no_meta_refresh app/main_test.py::test_dashboard_has_eventsource_script app/main_test.py::test_dashboard_subtitle_does_not_mention_auto_refresh -x -q --no-cov
```

Expected: `3 passed`

- [ ] **Step 5: Run full test suite**

```
uv run pytest -x -q --no-cov
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add app/templates/dashboard.html app/main_test.py
git commit -m "feat(dashboard): replace 30s meta-refresh with SSE EventSource"
```

---

## Task 6: Activity feed frontend — live row prepend

**Files:**
- Modify: `app/templates/activity.html`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write the failing test**

Add to `app/main_test.py`:

```python
async def test_activity_has_eventsource_script(client):
    response = await client.get("/activity")
    assert "EventSource" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest app/main_test.py::test_activity_has_eventsource_script -x -q --no-cov
```

Expected: `FAILED`

- [ ] **Step 3: Update activity.html**

Replace the entire `{% block scripts %}` section with the following. Note: `_buildRow` uses only safe DOM methods — `textContent` for all values from the SSE payload to prevent XSS:

```html
{% block scripts %}
<script>
  function filterActivity(status, btn) {
    if (btn) {
      document.querySelectorAll('.seg button').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
    }
    const monFilter = document.getElementById('mon-filter').value;
    const activeBtn = document.querySelector('.seg button.on');
    const statusFilter = activeBtn ? activeBtn.textContent.trim().toLowerCase() : 'all';
    const resolvedStatus = status !== null ? status : statusFilter;

    document.querySelectorAll('#activity-feed .activity-row').forEach(row => {
      const statusMatch = resolvedStatus === 'all' || row.dataset.status === resolvedStatus;
      const monMatch = !monFilter || row.dataset.monitor === monFilter;
      row.style.display = statusMatch && monMatch ? '' : 'none';
    });
  }

  function _buildRow(e) {
    const statusClass = String(e.status || '');
    const name        = String(e.monitor_name || '');
    const time        = e.ran_at ? String(e.ran_at).slice(11, 19) : '—';
    const rawVal      = e.error
      ? String(e.error).slice(0, 80) + (String(e.error).length > 80 ? '…' : '')
      : (e.last_value ? String(e.last_value) : '—');
    const dur         = e.duration_ms != null ? String(e.duration_ms) + 'ms' : '—';

    const a = document.createElement('a');
    a.href  = '/monitors/' + encodeURIComponent(name);
    a.className = 'neu-raised-sm activity-row';
    a.dataset.status  = statusClass;
    a.dataset.monitor = name;
    a.style.textDecoration = 'none';

    const led = document.createElement('div');
    led.className = 'led ' + statusClass;

    const tTime = document.createElement('span');
    tTime.className = 'act-time';
    tTime.textContent = time;

    const tName = document.createElement('span');
    tName.className = 'act-name';
    tName.textContent = name;

    const valCls = statusClass === 'error' ? 'act-value t-err mono'
                 : statusClass === 'changed' ? 'act-value t-chg mono'
                 : 'act-value t-2';
    const tVal = document.createElement('span');
    tVal.className = valCls;
    tVal.textContent = rawVal;

    const tDur = document.createElement('span');
    tDur.className = 'act-dur mono num';
    tDur.textContent = dur;

    const chip = document.createElement('span');
    chip.className = 'chip ' + statusClass + ' act-chip';
    chip.style.cssText = 'padding:3px 8px;font-size:9px';
    chip.textContent = statusClass;

    const chevron = document.createElement('span');
    chevron.className = 'act-chevron';
    chevron.setAttribute('aria-hidden', 'true');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '13');
    svg.setAttribute('height', '13');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6');
    svg.setAttribute('stroke-linecap', 'round');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M9 6l6 6-6 6');
    svg.appendChild(path);
    chevron.appendChild(svg);

    a.append(led, tTime, tName, tVal, tDur, chip, chevron);
    return a;
  }

  (function () {
    const liveDot = document.querySelector('.live-dot');

    function setConn(ok) {
      if (!liveDot) return;
      liveDot.style.background = ok ? '' : 'var(--ink-4)';
      liveDot.style.boxShadow  = ok ? '' : 'none';
    }

    const onFirstPage = !new URLSearchParams(location.search).get('offset');

    const src = new EventSource('/api/events');
    src.onmessage = (ev) => {
      if (!onFirstPage) return;
      let event;
      try { event = JSON.parse(ev.data); } catch (_) { return; }
      const feed = document.getElementById('activity-feed');
      if (!feed) return;
      const firstGroup = feed.querySelector('.day-group');
      const row = _buildRow(event);
      if (firstGroup) {
        const firstRow = firstGroup.querySelector('.activity-row');
        firstGroup.insertBefore(row, firstRow || null);
      } else {
        feed.prepend(row);
      }
    };
    src.onopen  = () => setConn(true);
    src.onerror = () => setConn(false);
  })();
</script>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest app/main_test.py::test_activity_has_eventsource_script -x -q --no-cov
```

Expected: `1 passed`

- [ ] **Step 5: Run full test suite with coverage**

```
uv run pytest
```

Expected: all pass, 100% coverage

- [ ] **Step 6: Commit**

```bash
git add app/templates/activity.html app/main_test.py
git commit -m "feat(activity): prepend live rows via SSE EventSource"
```

---

## Task 7: Smoke test in the browser

- [ ] **Step 1: Start the dev server**

```
uv run uvicorn app.main:app --reload
```

- [ ] **Step 2: Open http://localhost:8000 and verify**

- Subtitle shows "live" (not "auto-refresh every 30s")
- Green dot + "connected" label visible in the filter row
- Trigger a monitor run via the play button — page should reload within seconds (driven by SSE)
- Kill and restart the server — dot briefly goes grey ("reconnecting…"), returns green on reconnect

- [ ] **Step 3: Open http://localhost:8000/activity and verify**

- "Live" chip dot is green
- Trigger a monitor run — a new row appears at the top of the feed without a page reload
- Rows injected via SSE show UTC time (minor known trade-off; server-rendered rows show local time via the `localtime` Jinja filter)

- [ ] **Step 4: Commit any fixups needed, then done**
