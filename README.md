# changewatch

A self-hosted service that runs scheduled web monitors with Playwright, tracks value changes in SQLite, and sends notifications via Apprise.

## How it works

Drop a Python file in `monitors/`, define a `Monitor` with a name, cron schedule, and notify channels, then decorate an async function with `@monitor.check`. On startup, the scheduler discovers all monitor files and runs them on schedule. The dashboard at `http://localhost:8000` shows status, last value, and run history for each monitor.

## Quick start

```bash
uv sync
uv run playwright install chromium
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000

## Writing a monitor

`monitors/example_price.py`:

```python
from app.helpers import Monitor, extract_text, get_last_value, set_value, notify, record_metric

monitor = Monitor(
    name="example_price",
    schedule="*/30 * * * *",
    notify_channels=["telegram"],
    url="https://example.com/product",
)


@monitor.check
async def check(page, ctx):
    await page.goto(monitor.url)
    raw = await extract_text(page, ".price")
    price = float(raw.replace("€", "").replace(",", ".").strip())

    if ctx.influx:
        await record_metric(ctx.influx, "price", price, monitor=monitor.name)

    last = await get_last_value(ctx.db, monitor.name)
    if last is not None and price < float(last) and ctx.apprise:
        await notify(
            ctx.apprise,
            title=f"{monitor.name}: price dropped",
            body=f"€{last} → €{price}",
            tags=monitor.notify_channels,
        )

    await set_value(ctx.db, monitor.name, str(price))
```

- `Monitor(name, schedule, notify_channels, url)` — `schedule` is a crontab string (e.g. `"*/30 * * * *"`)
- `@monitor.check` registers the async function as the check to run on each scheduled invocation
- `page` is a Playwright `Page` object — each run gets a fresh browser context
- `ctx` carries `.db`, `.apprise`, `.influx`, and `.logger`; check for `None` before using optional integrations
- Helpers available: `extract_text`, `extract_json`, `get_last_value`, `set_value`, `notify`, `record_metric`

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/state.db` | SQLite database path |
| `MONITORS_DIR` | `./monitors` | Directory to load monitors from |
| `APPRISE_URL_<channel>` | — | Apprise notification URL for channel name `<channel>` (e.g. `APPRISE_URL_TELEGRAM`) |
| `INFLUXDB_URL` | — | InfluxDB endpoint (optional) |
| `INFLUXDB_TOKEN` | — | InfluxDB auth token (optional) |
| `INFLUXDB_ORG` | — | InfluxDB org (optional) |
| `INFLUXDB_BUCKET` | — | InfluxDB bucket (optional) |

Notification channels are configured by setting `APPRISE_URL_<CHANNEL>` environment variables. The `<channel>` part (lowercased) must match a name used in `notify_channels` when defining a monitor.

## Deployment

The Docker image is published to `ghcr.io/stevendejongnl/changewatch:latest` and also tagged `vX.Y.Z` for each release.

Kubernetes manifests live in `k8s/`. To deploy:

1. Copy secret templates: `cp k8s/secrets/*.example.yaml k8s/secrets/*.yaml`
2. Fill in values (Apprise URLs, InfluxDB credentials)
3. Apply: `kubectl apply -k k8s/`

A persistent volume must be mounted at `DB_PATH` (`/data` by default) to preserve state across restarts. The deployment uses `strategy: Recreate` — only one replica should run at a time since SQLite does not support concurrent writers.

## Development

```bash
make install-hooks   # wire pre-commit / pre-push hooks
make test            # run full suite (100% coverage required)
```

Test files use the `*_test.py` suffix. Conventional commits (`feat:`, `fix:`, etc.) trigger automatic releases via semantic-release, which publishes a GitHub Release and a versioned Docker image to GHCR.
