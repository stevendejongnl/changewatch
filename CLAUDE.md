# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

| Command | Purpose |
|---------|---------|
| `uv run pytest` | Full suite + 100% coverage gate (also what pre-push runs) |
| `uv run pytest --no-cov -x -q` | Fast iteration — what pre-commit runs |
| `uv run pytest app/main_test.py::test_name` | Single test |
| `make install-hooks` | Symlinks `.hooks/pre-commit` (fast) and `.hooks/pre-push` (full + coverage) into `.git/hooks/` |
| `uv run uvicorn app.main:app --reload` | Local dev server |
| `uv run playwright install chromium` | One-time local setup; CI also runs `--with-deps` |

**Docker**: base image is `mcr.microsoft.com/playwright/python:v1.59.0-jammy`. The version tag must match the `playwright` version that `uv` resolves at install time — check `uv.lock` for the resolved `playwright` version; the Dockerfile base image tag must match that version exactly.

## Architecture

### Monitor plugin model

`monitors/*.py` files are the unit of configuration. Each file declares a module-level `Monitor` instance and registers the async check function via the `@monitor.check` decorator:

```python
from app.helpers import Monitor, extract_text, get_last_value, set_value, notify, record_metric

monitor = Monitor(
    name="example_price",
    schedule="*/30 * * * *",   # standard crontab
    notify_channels=["telegram"],
    url="https://example.com/product",
)

@monitor.check
async def check(page, ctx):
    ...
```

`scheduler.py::discover_monitors` loads all `monitors/*.py` via `importlib.util`, silently skipping files that raise on import. Adding a monitor = dropping a new `.py` file; no registration required.

### Check function signature

`async def check(page, ctx)`:
- `page` — Playwright `Page` from a fresh browser context allocated per run by `Runner`
- `ctx` — `RunContext` from `runner.py` with fields: `.db`, `.apprise`, `.influx`, `.logger`, `.monitor_name`

Always use the helpers from `app/helpers.py` rather than accessing `ctx` fields directly:

| Helper | Purpose |
|--------|---------|
| `extract_text(page, selector)` | Wait for selector, return stripped inner text |
| `extract_json(page, url)` | Fetch JSON via browser request context (respects cookies/auth) |
| `get_last_value(ctx.db, monitor_name)` | Read latest persisted value from `state` table |
| `set_value(ctx.db, monitor_name, value)` | Upsert value into `state` table |
| `notify(ctx.apprise, title, body, tags)` | Send notification via Apprise |
| `record_metric(ctx.influx, measurement, value, **tags)` | Write point to InfluxDB |

`ctx.apprise` and `ctx.influx` are `Optional` — guard with `if ctx.apprise:` / `if ctx.influx:` before use.

### Lifespan singletons

`main.py` owns module-level `_db`, `_scheduler`, `_browser` created inside the FastAPI `lifespan` context manager and exposed via `Depends`. These are all marked `# pragma: no cover` because the 100% coverage gate would otherwise require real Playwright/InfluxDB startup in tests.

### Runner contract

`Runner.run` always writes a row to the `runs` table (status `ok` or `error`) and never re-raises exceptions — a failing monitor must not crash the scheduler.

SQLite has two tables:
- `state` — one row per monitor, stores the latest observed value (used for change detection)
- `runs` — append-only audit log of every execution (shown on the dashboard at `/`)

### Scheduling

`APScheduler AsyncIOScheduler` with `CronTrigger.from_crontab(monitor.schedule)` and `misfire_grace_time=60`. `POST /monitors/{name}/run` queues an immediate run via `Scheduler.trigger`, which bypasses the cron schedule. Note: `Scheduler` needs to receive the Playwright browser instance at init time (from the `main.py` lifespan where `_browser` lives); currently `start()` hardcodes `browser=None` when creating `Runner` for cron jobs, which would crash cron-scheduled runs.

### Notifications

`AppriseClient` reads all env vars prefixed `APPRISE_URL_<TAG>` (tag lowercased). A monitor's `notify_channels=["telegram"]` becomes the Apprise tag list; only channels with a matching env var are notified.

## Testing

- `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator needed
- `--cov-fail-under=100` enforced; use `# pragma: no cover` only for untestable glue (lifespan, `TYPE_CHECKING` blocks)
- Test files use `*_test.py` suffix (not `test_*.py`), co-located in `app/` and `monitors/`
- `app/conftest.py` provides an `influx_client` fixture (module-scoped, skipped when InfluxDB at 192.168.1.22:8086 is unreachable or `INFLUXDB_TOKEN`/`INFLUXDB_ORG` env vars are unset)

## CI / Release

- GitHub Actions: `test` → `release` (semantic-release, `main` only) → `build` (pushes GHCR image as `latest` + `vX.Y.Z`)
- Conventional commits (`feat:`, `fix:`) drive semver bumps per `.releaserc.json`
- k8s secrets are committed as `.example.yaml` only; real secret files are gitignored
