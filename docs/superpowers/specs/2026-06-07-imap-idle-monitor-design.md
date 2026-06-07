# IMAP IDLE Monitor — Design Spec

**Date:** 2026-06-07
**Status:** Approved for implementation

## Goal

Add IMAP IDLE support to changewatch so monitors can react to incoming email in near-real-time (seconds) rather than waiting for the next cron tick. Initial use-case: watch `mail@stevenenanja.nl` for emails from `@zitmaxx.nl`, extract order/delivery data, and notify via Telegram.

---

## Section 1 — Data Extraction

Per incoming email from `@zitmaxx.nl`:

| Field | Source | Regex / rule |
|-------|--------|--------------|
| `order_nr` | subject or body | `\b\d{10}\b` (first match) |
| `delivery_week` | body | `week\s+(\d+)` (first match, optional) |
| `email_type` | sender address | `order_confirm` (verkoop@), `delivery_prognosis` (aftersales@), `review_request` (automail@), `other` |
| `subject` | header | raw, always included |

Notification fires on **every new matching email** — no change-detection gate needed. Raw subject always included as fallback if extraction finds nothing.

---

## Section 2 — Architecture

### 2.1 New files

| File | Purpose |
|------|---------|
| `app/imap_client.py` | `ImapClient` — parses `IMAP_URL_*` env vars, owns per-account IMAP connections |
| `app/imap_watcher.py` | `ImapWatcher` — long-running asyncio task per `(account, folder)`, holds IMAP IDLE connection, triggers monitor runs on new mail |
| `app/imap_client_test.py` | Unit tests for URL parsing, normalization, connection logic |
| `app/imap_watcher_test.py` | Unit tests for watcher trigger logic (mocked IMAP) |

### 2.2 Modified files

| File | Change |
|------|--------|
| `app/helpers.py` | Add `ImapIdleConfig` dataclass; add `imap_connect()` async context manager and `imap_fetch_unseen()` helper |
| `app/helpers_test.py` | Tests for new helpers |
| `app/main.py` | Lifespan: create `ImapClient`, start `ImapWatcher` tasks for monitors with `imap_idle` set |
| `app/scheduler.py` | `discover_monitors` already works; no change needed |
| `pyproject.toml` | Add `aioimaplib` dependency |

### 2.3 `ImapIdleConfig`

```python
@dataclass
class ImapIdleConfig:
    account: str        # full email, e.g. "mail@stevenenanja.nl"
    folder: str         # IMAP folder, e.g. "INBOX"
    search: list[str]   # IMAP search criteria, e.g. ["FROM", "@zitmaxx.nl"]
```

Added as an optional field on `Monitor`:

```python
@dataclass
class Monitor:
    ...
    imap_idle: ImapIdleConfig | None = None
```

Monitors with `imap_idle` set and `schedule=None` are IDLE-driven only. Monitors may have both set (IDLE for fast response + cron as a safety net).

### 2.4 `ImapClient`

Reads all env vars matching `IMAP_URL_*` at startup. Normalizes the account email to an env var key:

```
"mail@stevenenanja.nl" → upper + replace @/. with _ → "MAIL_STEVENENANJA_NL"
→ reads env var IMAP_URL_MAIL_STEVENENANJA_NL
```

Env var format: standard IMAP URL:
```
IMAP_URL_MAIL_STEVENENANJA_NL=imaps://mail%40stevenenanja.nl:password@mail.steven-dejong.nl:993
```

`ImapClient` exposes `get_connection(account: str) -> ImapConnection` — returns a shared `aioimaplib` connection per account.

### 2.5 `ImapWatcher`

One watcher task per unique `(account, folder)` pair. Multiple monitors watching the same folder share a single IDLE connection.

Lifecycle:
1. Connect via `ImapClient`
2. Select folder
3. Enter IDLE
4. On server push with `EXISTS` response: exit IDLE, fetch new UIDs, match against each monitor's `search` criteria
5. For each monitor with matching mail: call `scheduler.trigger(monitor.name, browser)`
6. Re-enter IDLE
7. On connection drop: reconnect with exponential backoff (1s → 2s → 4s → max 60s)
8. If server does not support IDLE: fall back to polling every 60s via NOOP + UID SEARCH

### 2.6 Check function contract

The check function is called by `Runner` exactly as today — `async def check(page, ctx)`. `page` is unused for IMAP monitors. The function connects to IMAP itself using helpers:

```python
@monitor.check
async def check(page, ctx):
    async with imap_connect(monitor.imap_idle, ctx) as imap:
        msgs = await imap_fetch_unseen(imap, monitor.imap_idle.search)
    for msg in msgs:
        ...
        await notify(ctx.apprise, title=..., body=..., tags=monitor.notify_channels)
```

`imap_fetch_unseen` returns only UIDs not yet seen (tracked via `get_last_value` / `set_value` storing the highest seen UID as a string).

### 2.7 Lifespan integration (`main.py`)

```python
_imap_client: ImapClient | None = None

async with lifespan:
    if any monitors have imap_idle:
        _imap_client = ImapClient.from_env()
        watcher = ImapWatcher(_imap_client, monitors_with_idle, scheduler, browser)
        asyncio.create_task(watcher.run())
```

Watcher task is cancelled on shutdown via the lifespan exit.

---

## Section 3 — Zitmaxx Monitor File

Lives in `changewatch-monitors/zitmaxx_order.py`:

```python
import re
from app.helpers import Monitor, ImapIdleConfig, imap_connect, imap_fetch_unseen, get_last_value, set_value, notify

monitor = Monitor(
    name="zitmaxx_order",
    schedule=None,
    imap_idle=ImapIdleConfig(
        account="mail@stevenenanja.nl",
        folder="INBOX",
        search=["FROM", "@zitmaxx.nl"],
    ),
    notify_channels=["telegram"],
    display_url="https://www.zitmaxx.nl/",
)

EMAIL_TYPE = {
    "verkoop@zitmaxx.nl": "Orderbevestiging",
    "automail@zitmaxx.nl": "Review verzoek",
    "aftersales@zitmaxx.nl": "Leveringsprognose",
}

@monitor.check
async def check(page, ctx):
    async with imap_connect(monitor.imap_idle, ctx) as imap:
        msgs = await imap_fetch_unseen(imap, monitor.imap_idle.search)

    for msg in msgs:
        subject = msg.get("Subject", "(geen onderwerp)")
        sender = msg.get("From", "")
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body else ""

        order_nr = next(iter(re.findall(r'\b\d{10}\b', subject + " " + text)), None)
        week_match = re.search(r'week\s+(\d+)', text, re.IGNORECASE)
        email_type = next((label for addr, label in EMAIL_TYPE.items() if addr in sender), "Update")

        lines = [f"📧 {email_type}: {subject}"]
        if order_nr:
            lines.append(f"Order: {order_nr}")
        if week_match:
            lines.append(f"Verwachte aankomst: week {week_match.group(1)}")

        ctx.logger.info("zitmaxx email: %s (order=%s week=%s)", email_type, order_nr, week_match and week_match.group(1))

        if ctx.apprise:
            await notify(ctx.apprise, title="Zitmaxx update", body="\n".join(lines), tags=monitor.notify_channels)
```

---

## Section 4 — Error Handling

| Failure | Behaviour |
|---------|-----------|
| IMAP connection drop | Watcher reconnects with exponential backoff, max 60s |
| Server has no IDLE | Fall back to 60s poll (NOOP + UID SEARCH) |
| Parse error on email body | Log warning, notify with subject only, continue |
| Account not in env | `ImapClient` raises at startup with clear message listing missing var name |
| Monitor triggered but no new mail | `imap_fetch_unseen` returns empty list, check exits cleanly |

---

## Section 5 — Credentials & Secrets

New k8s secret entries (added to `changewatch-secrets`):

```
IMAP_URL_MAIL_STEVENENANJA_NL=imaps://mail%40stevenenanja.nl:<password>@mail.steven-dejong.nl:993
```

Local dev: add to `.env` file (already gitignored).

---

## Section 6 — Testing

- `ImapClient`: URL parsing, normalization edge-cases (`@`, `.`, `-`), missing env var error
- `ImapWatcher`: mock `aioimaplib`; verify IDLE entered, EXISTS triggers `scheduler.trigger`, reconnect on drop, fallback to poll
- `imap_fetch_unseen`: mock connection; verify UID tracking via `get_last_value`/`set_value`
- Coverage gate remains 100%; IMAP lifespan wiring marked `# pragma: no cover`
