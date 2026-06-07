# IMAP IDLE Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add IMAP IDLE support to changewatch so monitors react to incoming email in seconds, with an initial Zitmaxx order-tracking monitor on `mail@stevenenanja.nl`.

**Architecture:** A long-running `ImapWatcher` asyncio task (started in the FastAPI lifespan) holds one persistent IMAP IDLE connection per `(account, folder)` pair. When the server pushes an EXISTS notification, the watcher calls `scheduler.trigger()` for each monitor watching that folder. The check function then opens its own short-lived IMAP connection via `imap_connect()` and fetches new messages using UID tracking in the state table.

**Tech Stack:** `aioimaplib` (async IMAP), `contextlib.asynccontextmanager`, `email` stdlib, `unittest.mock.AsyncMock` for tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `app/imap_client.py` | `account_to_env_key()`, `get_imap_url()`, `ImapClient` (credential store) |
| Create | `app/imap_client_test.py` | Tests for normalization + credential resolution |
| Create | `app/imap_watcher.py` | `ImapWatcher` — long-running IDLE task, triggers scheduler |
| Create | `app/imap_watcher_test.py` | Tests for watcher trigger + reconnect logic |
| Modify | `app/helpers.py` | Add `ImapIdleConfig`, `imap_connect()`, `imap_fetch_unseen()` |
| Modify | `app/helpers_test.py` | Tests for new helpers |
| Modify | `app/scheduler.py` | Skip `schedule=None` monitors in `start()` and `reload()` |
| Modify | `app/scheduler_test.py` | Tests for IMAP-only monitors being skipped |
| Modify | `app/main.py` | Lifespan: create + start `ImapWatcher` if IMAP monitors exist |
| Modify | `app/main_test.py` | Test `get_imap_watcher` dependency |
| Modify | `pyproject.toml` | Add `aioimaplib>=1.0` |
| Create | `../changewatch-monitors/zitmaxx_order.py` | Zitmaxx order monitor |

---

## Task 1: Add `aioimaplib` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

In `pyproject.toml`, add `aioimaplib>=1.0` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "apscheduler>=3.10",
    "playwright>=1.49",
    "influxdb-client[async]>=1.45",
    "apprise>=1.9",
    "aiosqlite>=0.20",
    "jinja2>=3.1",
    "python-multipart>=0.0.19",
    "tzdata>=2026.2",
    "cron-descriptor>=2.0.8",
    "aioimaplib>=1.0",
]
```

- [ ] **Step 2: Install**

```bash
uv add aioimaplib
```

Expected: `uv.lock` updated, `aioimaplib` installed.

- [ ] **Step 3: Verify import**

```bash
uv run python -c "import aioimaplib; print(aioimaplib.__version__)"
```

Expected: version string printed, no error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add aioimaplib dependency"
```

---

## Task 2: `ImapIdleConfig` + `Monitor.imap_idle` + scheduler fix for `schedule=None`

**Files:**
- Modify: `app/helpers.py`
- Modify: `app/helpers_test.py`
- Modify: `app/scheduler.py`
- Modify: `app/scheduler_test.py`

- [ ] **Step 1: Write failing tests for `ImapIdleConfig`**

In `app/helpers_test.py`, add after the existing `Monitor` tests:

```python
from app.helpers import ImapIdleConfig


def test_imap_idle_config_stores_fields():
    cfg = ImapIdleConfig(
        account="mail@stevenenanja.nl",
        folder="INBOX",
        search=["FROM", "@zitmaxx.nl"],
    )
    assert cfg.account == "mail@stevenenanja.nl"
    assert cfg.folder == "INBOX"
    assert cfg.search == ["FROM", "@zitmaxx.nl"]


def test_monitor_imap_idle_defaults_to_none():
    m = Monitor(name="test", schedule="*/5 * * * *", notify_channels=[])
    assert m.imap_idle is None


def test_monitor_accepts_imap_idle_config():
    cfg = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=["FROM", "@x.nl"])
    m = Monitor(name="test", schedule=None, notify_channels=[], imap_idle=cfg)
    assert m.imap_idle is cfg
    assert m.schedule is None
```

- [ ] **Step 2: Run tests, verify failure**

```bash
uv run pytest app/helpers_test.py -k "imap" --no-cov -x -q
```

Expected: `ImportError` or `AttributeError` on `ImapIdleConfig` or `imap_idle`.

- [ ] **Step 3: Add `ImapIdleConfig` and `imap_idle` to `helpers.py`**

In `app/helpers.py`, add the `ImapIdleConfig` dataclass and extend `Monitor`:

```python
@dataclass
class ImapIdleConfig:
    account: str
    folder: str
    search: list[str]
```

And update `Monitor`:

```python
@dataclass
class Monitor:
    name: str
    schedule: Optional[str]
    notify_channels: list[str]
    url: Optional[str] = None
    metric: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    display_name: str = ""
    display_url: str = ""
    imap_idle: Optional["ImapIdleConfig"] = None
    fn: Optional[Callable] = field(default=None, repr=False)

    def check(self, func: Callable) -> Callable:
        self.fn = func
        return func
```

Note: `schedule` changes from `str` to `Optional[str]`.

- [ ] **Step 4: Run tests, verify helpers pass**

```bash
uv run pytest app/helpers_test.py -k "imap" --no-cov -x -q
```

Expected: 3 tests pass.

- [ ] **Step 5: Write failing tests for scheduler skipping `schedule=None` monitors**

In `app/scheduler_test.py`, add:

```python
from app.helpers import ImapIdleConfig


def _make_imap_monitor_module(monitors_dir: Path, name: str) -> Path:
    monitors_dir.mkdir(exist_ok=True)
    code = f"""
from app.helpers import Monitor, ImapIdleConfig

monitor = Monitor(
    name="{name}",
    schedule=None,
    notify_channels=["telegram"],
    imap_idle=ImapIdleConfig(account="a@b.nl", folder="INBOX", search=["FROM", "@x.nl"]),
)

@monitor.check
async def check(page, ctx):
    pass
"""
    path = monitors_dir / f"{name}.py"
    path.write_text(code)
    return path


def test_discover_monitors_finds_imap_only_monitor(monitors_dir):
    _make_imap_monitor_module(monitors_dir, "imap_check")
    monitors = discover_monitors(monitors_dir)
    assert any(m.name == "imap_check" for m in monitors)


def test_discover_monitors_imap_monitor_has_none_schedule(monitors_dir):
    _make_imap_monitor_module(monitors_dir, "imap_check")
    monitors = discover_monitors(monitors_dir)
    m = next(m for m in monitors if m.name == "imap_check")
    assert m.schedule is None


async def test_scheduler_start_skips_imap_only_monitors(monitors_dir, db):
    _make_imap_monitor_module(monitors_dir, "imap_check")
    sched = Scheduler(monitors_dir=monitors_dir, db=db)
    await sched.start()
    jobs = sched.list_jobs()
    assert not any(j["id"] == "imap_check" for j in jobs)
    await sched.stop()


async def test_scheduler_reload_skips_imap_only_monitors(monitors_dir, db):
    _make_imap_monitor_module(monitors_dir, "imap_check")
    sched = Scheduler(monitors_dir=monitors_dir, db=db)
    await sched.start()
    await sched.reload()
    jobs = sched.list_jobs()
    assert not any(j["id"] == "imap_check" for j in jobs)
    await sched.stop()
```

- [ ] **Step 6: Run tests, verify failure**

```bash
uv run pytest app/scheduler_test.py -k "imap" --no-cov -x -q
```

Expected: `TypeError` from `CronTrigger.from_crontab(None, ...)`.

- [ ] **Step 7: Fix `scheduler.py` to skip `schedule=None` monitors**

In `app/scheduler.py`, in `start()`, change the loop:

```python
for monitor in self._monitors:
    if monitor.schedule is None:
        continue
    self._scheduler.add_job(
        self._make_job_fn(runner, monitor),
        CronTrigger.from_crontab(monitor.schedule, timezone=self._timezone),
        id=monitor.name,
        name=monitor.name,
        misfire_grace_time=60,
        replace_existing=True,
    )
```

In `reload()`, same change — add `if monitor.schedule is None: continue` at the top of the `for monitor in new_monitors:` loop.

- [ ] **Step 8: Run all scheduler tests**

```bash
uv run pytest app/scheduler_test.py --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add app/helpers.py app/helpers_test.py app/scheduler.py app/scheduler_test.py
git commit -m "feat: add ImapIdleConfig to Monitor, skip schedule=None monitors in scheduler"
```

---

## Task 3: `ImapClient` — credential resolution

**Files:**
- Create: `app/imap_client.py`
- Create: `app/imap_client_test.py`

- [ ] **Step 1: Write failing tests**

Create `app/imap_client_test.py`:

```python
import pytest
from app.imap_client import account_to_env_key, ImapClient


def test_account_to_env_key_basic():
    assert account_to_env_key("mail@stevenenanja.nl") == "MAIL_STEVENENANJA_NL"


def test_account_to_env_key_hyphen_in_domain():
    assert account_to_env_key("steven@steven-dejong.nl") == "STEVEN_STEVEN_DEJONG_NL"


def test_account_to_env_key_uppercase_input():
    assert account_to_env_key("MAIL@STEVENENANJA.NL") == "MAIL_STEVENENANJA_NL"


def test_imap_client_from_env_finds_account():
    env = {"IMAP_URL_MAIL_STEVENENANJA_NL": "imaps://u:p@host:993"}
    client = ImapClient.from_env(env)
    assert client.get_url("mail@stevenenanja.nl") == "imaps://u:p@host:993"


def test_imap_client_from_env_empty():
    client = ImapClient.from_env({})
    assert client.known_accounts() == []


def test_imap_client_known_accounts_returns_env_key_suffixes():
    env = {
        "IMAP_URL_MAIL_STEVENENANJA_NL": "imaps://a:b@host:993",
        "IMAP_URL_STEVEN_STEVEN_DEJONG_NL": "imaps://c:d@host:993",
    }
    client = ImapClient.from_env(env)
    keys = client.known_accounts()
    assert "MAIL_STEVENENANJA_NL" in keys
    assert "STEVEN_STEVEN_DEJONG_NL" in keys


def test_imap_client_get_url_missing_raises_with_key_name():
    client = ImapClient.from_env({})
    with pytest.raises(ValueError, match="IMAP_URL_MAIL_STEVENENANJA_NL"):
        client.get_url("mail@stevenenanja.nl")


def test_imap_client_get_url_multiple_accounts():
    env = {
        "IMAP_URL_A_B_NL": "imaps://a:p@host:993",
        "IMAP_URL_C_D_NL": "imaps://c:q@host:993",
    }
    client = ImapClient.from_env(env)
    assert client.get_url("a@b.nl") == "imaps://a:p@host:993"
    assert client.get_url("c@d.nl") == "imaps://c:q@host:993"
```

- [ ] **Step 2: Run tests, verify failure**

```bash
uv run pytest app/imap_client_test.py --no-cov -x -q
```

Expected: `ModuleNotFoundError: No module named 'app.imap_client'`.

- [ ] **Step 3: Implement `imap_client.py`**

Create `app/imap_client.py`:

```python
import os
import re


def account_to_env_key(account: str) -> str:
    return re.sub(r'[^A-Z0-9]', '_', account.upper())


class ImapClient:
    _PREFIX = "IMAP_URL_"

    def __init__(self, accounts: dict[str, str]) -> None:
        self._accounts = accounts

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ImapClient":
        if env is None:
            env = dict(os.environ)
        accounts = {
            k[len(cls._PREFIX):]: v
            for k, v in env.items()
            if k.startswith(cls._PREFIX)
        }
        return cls(accounts)

    def get_url(self, account: str) -> str:
        key = account_to_env_key(account)
        url = self._accounts.get(key)
        if not url:
            raise ValueError(
                f"Missing env var IMAP_URL_{key!s} for IMAP account {account!r}"
            )
        return url

    def known_accounts(self) -> list[str]:
        return list(self._accounts.keys())
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest app/imap_client_test.py --no-cov -x -q
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/imap_client.py app/imap_client_test.py
git commit -m "feat: add ImapClient for IMAP_URL_* credential resolution"
```

---

## Task 4: IMAP helpers — `imap_connect` and `imap_fetch_unseen`

**Files:**
- Modify: `app/helpers.py`
- Modify: `app/helpers_test.py`

- [ ] **Step 1: Write failing tests**

In `app/helpers_test.py`, add at the bottom:

```python
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.helpers import ImapIdleConfig, imap_connect, imap_fetch_unseen
from app.runner import RunContext


# ── imap_connect ──────────────────────────────────────────────────────────

async def test_imap_connect_logs_in_and_selects_folder():
    mock_imap = AsyncMock()
    mock_imap.wait_hello_from_server = AsyncMock()
    mock_imap.login = AsyncMock(return_value=("OK", [b"Logged in"]))
    mock_imap.select = AsyncMock(return_value=("OK", [b"1"]))
    mock_imap.logout = AsyncMock(return_value=("OK", [b"Bye"]))

    config = ImapIdleConfig(
        account="mail@stevenenanja.nl",
        folder="INBOX",
        search=["FROM", "@zitmaxx.nl"],
    )
    env = {"IMAP_URL_MAIL_STEVENENANJA_NL": "imaps://mail%40stevenenanja.nl:secret@host.nl:993"}

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_imap):
        async with imap_connect(config, env) as imap:
            assert imap is mock_imap

    mock_imap.login.assert_called_once_with("mail@stevenenanja.nl", "secret")
    mock_imap.select.assert_called_once_with("INBOX")
    mock_imap.logout.assert_called_once()


async def test_imap_connect_logs_out_even_on_exception():
    mock_imap = AsyncMock()
    mock_imap.wait_hello_from_server = AsyncMock()
    mock_imap.login = AsyncMock(return_value=("OK", [b"OK"]))
    mock_imap.select = AsyncMock(return_value=("OK", [b"1"]))
    mock_imap.logout = AsyncMock(return_value=("OK", [b"Bye"]))

    config = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=[])
    env = {"IMAP_URL_A_B_NL": "imaps://a%40b.nl:p@host:993"}

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_imap):
        with pytest.raises(RuntimeError):
            async with imap_connect(config, env) as _:
                raise RuntimeError("boom")

    mock_imap.logout.assert_called_once()


async def test_imap_connect_uses_default_port_993():
    mock_imap = AsyncMock()
    mock_imap.wait_hello_from_server = AsyncMock()
    mock_imap.login = AsyncMock(return_value=("OK", [b"OK"]))
    mock_imap.select = AsyncMock(return_value=("OK", [b"1"]))
    mock_imap.logout = AsyncMock(return_value=("OK", [b"Bye"]))

    config = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=[])
    env = {"IMAP_URL_A_B_NL": "imaps://a%40b.nl:p@mail.host.nl"}

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_imap) as mock_cls:
        async with imap_connect(config, env) as _:
            pass

    mock_cls.assert_called_once_with(host="mail.host.nl", port=993)


# ── imap_fetch_unseen ─────────────────────────────────────────────────────

@pytest.fixture
async def imap_ctx(db):
    return RunContext(
        monitor_name="test_monitor",
        logger=logging.getLogger("test"),
        db=db,
    )


async def test_imap_fetch_unseen_first_run_stores_max_uid_returns_empty(db, imap_ctx):
    mock_imap = AsyncMock()
    mock_imap.uid = AsyncMock(return_value=("OK", [b"100 101 102"]))

    result = await imap_fetch_unseen(mock_imap, ["FROM", "@x.nl"], imap_ctx)

    assert result == []
    assert await get_last_value(db, "test_monitor") == "102"
    mock_imap.uid.assert_called_once_with("search", None, "ALL")


async def test_imap_fetch_unseen_first_run_empty_inbox(db, imap_ctx):
    mock_imap = AsyncMock()
    mock_imap.uid = AsyncMock(return_value=("OK", [b""]))

    result = await imap_fetch_unseen(mock_imap, ["FROM", "@x.nl"], imap_ctx)

    assert result == []
    assert await get_last_value(db, "test_monitor") == "0"


async def test_imap_fetch_unseen_returns_new_messages(db, imap_ctx):
    await set_value(db, "test_monitor", "102")

    raw = b"From: sender@x.nl\r\nSubject: Test\r\n\r\nBody text"
    mock_imap = AsyncMock()
    mock_imap.uid = AsyncMock(side_effect=[
        ("OK", [b"103"]),
        ("OK", [(b"1 (UID 103 RFC822 {N})", raw), b")"]),
    ])

    result = await imap_fetch_unseen(mock_imap, ["FROM", "@x.nl"], imap_ctx)

    assert len(result) == 1
    assert result[0]["Subject"] == "Test"
    assert await get_last_value(db, "test_monitor") == "103"


async def test_imap_fetch_unseen_updates_max_uid(db, imap_ctx):
    await set_value(db, "test_monitor", "100")

    raw = b"From: a@x.nl\r\nSubject: S\r\n\r\nB"
    mock_imap = AsyncMock()
    mock_imap.uid = AsyncMock(side_effect=[
        ("OK", [b"101 102 103"]),
        ("OK", [(b"1 (UID 101 RFC822 {N})", raw), b")"]),
        ("OK", [(b"2 (UID 102 RFC822 {N})", raw), b")"]),
        ("OK", [(b"3 (UID 103 RFC822 {N})", raw), b")"]),
    ])

    result = await imap_fetch_unseen(mock_imap, ["FROM", "@x.nl"], imap_ctx)

    assert len(result) == 3
    assert await get_last_value(db, "test_monitor") == "103"


async def test_imap_fetch_unseen_no_new_messages(db, imap_ctx):
    await set_value(db, "test_monitor", "102")

    mock_imap = AsyncMock()
    mock_imap.uid = AsyncMock(return_value=("OK", [b""]))

    result = await imap_fetch_unseen(mock_imap, ["FROM", "@x.nl"], imap_ctx)

    assert result == []
    assert await get_last_value(db, "test_monitor") == "102"


async def test_imap_fetch_unseen_filters_uids_below_threshold(db, imap_ctx):
    await set_value(db, "test_monitor", "102")

    mock_imap = AsyncMock()
    mock_imap.uid = AsyncMock(return_value=("OK", [b"102"]))

    result = await imap_fetch_unseen(mock_imap, ["FROM", "@x.nl"], imap_ctx)

    assert result == []
```

- [ ] **Step 2: Run tests, verify failure**

```bash
uv run pytest app/helpers_test.py -k "imap" --no-cov -x -q
```

Expected: `ImportError` on `imap_connect` and `imap_fetch_unseen`.

- [ ] **Step 3: Implement `imap_connect` and `imap_fetch_unseen` in `helpers.py`**

Add to the top of `app/helpers.py`:

```python
from contextlib import asynccontextmanager
```

Add at the bottom of `app/helpers.py`:

```python
@asynccontextmanager
async def imap_connect(config: "ImapIdleConfig", env: dict[str, str] | None = None):
    import aioimaplib
    from urllib.parse import urlparse, unquote
    from app.imap_client import ImapClient

    client = ImapClient.from_env(env)
    url = client.get_url(config.account)
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 993
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")

    imap = aioimaplib.IMAP4_SSL(host=host, port=port)
    await imap.wait_hello_from_server()
    await imap.login(user, password)
    await imap.select(config.folder)
    try:
        yield imap
    finally:
        try:
            await imap.logout()
        except Exception:
            pass


async def imap_fetch_unseen(
    imap: Any,
    search: list[str],
    ctx: "RunContext",
) -> list[Any]:
    import email as _email
    from email.policy import default as _default_policy

    last_uid_str = await get_last_value(ctx.db, ctx.monitor_name)

    if last_uid_str is None:
        typ, data = await imap.uid("search", None, "ALL")
        uid_strs = data[0].decode().split() if data[0] else []
        max_uid = max((int(u) for u in uid_strs), default=0)
        await set_value(ctx.db, ctx.monitor_name, str(max_uid))
        return []

    last_uid = int(last_uid_str)
    next_uid = last_uid + 1
    criteria = list(search) + ["UID", f"{next_uid}:*"]

    typ, data = await imap.uid("search", None, *criteria)
    raw_uids = data[0].decode().split() if data[0] else []
    uid_strs = [u for u in raw_uids if int(u) >= next_uid]

    if not uid_strs:
        return []

    messages = []
    for uid_str in uid_strs:
        typ, msg_data = await imap.uid("fetch", uid_str, "(RFC822)")
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                msg = _email.message_from_bytes(item[1], policy=_default_policy)
                messages.append(msg)
                break

    max_new_uid = max(int(u) for u in uid_strs)
    await set_value(ctx.db, ctx.monitor_name, str(max_new_uid))
    return messages
```

Add `"RunContext"` to the `TYPE_CHECKING` block in `helpers.py`:

```python
if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.influx import InfluxClient
    from app.runner import RunContext
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest app/helpers_test.py -k "imap" --no-cov -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/helpers.py app/helpers_test.py
git commit -m "feat: add imap_connect and imap_fetch_unseen helpers"
```

---

## Task 5: `ImapWatcher`

**Files:**
- Create: `app/imap_watcher.py`
- Create: `app/imap_watcher_test.py`

- [ ] **Step 1: Write failing tests**

Create `app/imap_watcher_test.py`:

```python
import asyncio
import logging
import pytest
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.helpers import Monitor, ImapIdleConfig
from app.imap_watcher import ImapWatcher


@pytest.fixture
def monitors():
    cfg = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=["FROM", "@x.nl"])
    m = Monitor(name="test_mon", schedule=None, notify_channels=["telegram"], imap_idle=cfg)

    @m.check
    async def check(page, ctx):
        pass

    return [m]


@pytest.fixture
def mock_scheduler():
    s = MagicMock()
    s.trigger = AsyncMock()
    return s


async def test_imap_watcher_triggers_monitor_on_exists(monitors, mock_scheduler):
    mock_imap = AsyncMock()
    mock_imap.wait_hello_from_server = AsyncMock()
    mock_imap.login = AsyncMock(return_value=("OK", [b"OK"]))
    mock_imap.select = AsyncMock(return_value=("OK", [b"1"]))
    mock_imap.logout = AsyncMock(return_value=("OK", [b"Bye"]))
    mock_imap.capability = AsyncMock(return_value=("OK", [b"IMAP4rev1 IDLE UIDPLUS"]))
    mock_imap.idle_start = AsyncMock()

    call_count = 0

    async def wait_server_push():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [b"* 5 EXISTS"]
        raise asyncio.CancelledError()

    mock_imap.wait_server_push = wait_server_push
    mock_imap.idle_done = AsyncMock()

    env = {"IMAP_URL_A_B_NL": "imaps://a%40b.nl:p@host:993"}

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_imap):
        with patch("app.imap_watcher.IMAP_ENV", env):
            watcher = ImapWatcher(monitors=monitors, scheduler=mock_scheduler, browser=None)
            with pytest.raises(asyncio.CancelledError):
                await watcher._idle_loop("a@b.nl", "INBOX", monitors)

    mock_scheduler.trigger.assert_awaited_once_with("test_mon", None)


async def test_imap_watcher_falls_back_to_poll_without_idle(monitors, mock_scheduler):
    mock_imap = AsyncMock()
    mock_imap.wait_hello_from_server = AsyncMock()
    mock_imap.login = AsyncMock(return_value=("OK", [b"OK"]))
    mock_imap.select = AsyncMock(return_value=("OK", [b"1"]))
    mock_imap.logout = AsyncMock(return_value=("OK", [b"Bye"]))
    mock_imap.capability = AsyncMock(return_value=("OK", [b"IMAP4rev1 UIDPLUS"]))
    mock_imap.noop = AsyncMock(return_value=("OK", [b"NOOP completed"]))

    call_count = 0

    async def fake_sleep(secs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    env = {"IMAP_URL_A_B_NL": "imaps://a%40b.nl:p@host:993"}

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_imap):
        with patch("app.imap_watcher.IMAP_ENV", env):
            with patch("asyncio.sleep", fake_sleep):
                watcher = ImapWatcher(monitors=monitors, scheduler=mock_scheduler, browser=None)
                with pytest.raises(asyncio.CancelledError):
                    await watcher._idle_loop("a@b.nl", "INBOX", monitors)

    assert mock_scheduler.trigger.await_count >= 1


async def test_imap_watcher_watch_folder_reconnects_on_error(monitors, mock_scheduler):
    call_count = 0

    async def fail_then_cancel(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("dropped")
        raise asyncio.CancelledError()

    env = {"IMAP_URL_A_B_NL": "imaps://a%40b.nl:p@host:993"}
    watcher = ImapWatcher(monitors=monitors, scheduler=mock_scheduler, browser=None)
    watcher._idle_loop = fail_then_cancel

    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(asyncio.CancelledError):
            await watcher._watch_folder("a@b.nl", "INBOX", monitors)

    assert call_count == 2


async def test_imap_watcher_run_groups_monitors_by_account_folder(mock_scheduler):
    cfg1 = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=[])
    cfg2 = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=[])
    cfg3 = ImapIdleConfig(account="c@d.nl", folder="INBOX", search=[])

    m1 = Monitor(name="m1", schedule=None, notify_channels=[], imap_idle=cfg1)
    m2 = Monitor(name="m2", schedule=None, notify_channels=[], imap_idle=cfg2)
    m3 = Monitor(name="m3", schedule=None, notify_channels=[], imap_idle=cfg3)
    for m in [m1, m2, m3]:
        @m.check
        async def check(page, ctx): pass

    groups_seen = []

    async def fake_watch(account, folder, mons):
        groups_seen.append((account, folder, [m.name for m in mons]))

    watcher = ImapWatcher(monitors=[m1, m2, m3], scheduler=mock_scheduler, browser=None)
    watcher._watch_folder = fake_watch

    await watcher.run()

    assert len(groups_seen) == 2
    ab_group = next(g for g in groups_seen if g[0] == "a@b.nl")
    assert set(ab_group[2]) == {"m1", "m2"}
    cd_group = next(g for g in groups_seen if g[0] == "c@d.nl")
    assert cd_group[2] == ["m3"]
```

- [ ] **Step 2: Run tests, verify failure**

```bash
uv run pytest app/imap_watcher_test.py --no-cov -x -q
```

Expected: `ModuleNotFoundError: No module named 'app.imap_watcher'`.

- [ ] **Step 3: Implement `imap_watcher.py`**

Create `app/imap_watcher.py`:

```python
import asyncio
import logging
import os
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.helpers import Monitor
    from app.scheduler import Scheduler

logger = logging.getLogger(__name__)

IMAP_ENV: dict[str, str] | None = None


class ImapWatcher:
    def __init__(
        self,
        monitors: list["Monitor"],
        scheduler: "Scheduler",
        browser: Any,
    ) -> None:
        self._monitors = monitors
        self._scheduler = scheduler
        self._browser = browser

    async def run(self) -> None:
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for m in self._monitors:
            if m.imap_idle:
                groups[(m.imap_idle.account, m.imap_idle.folder)].append(m)

        tasks = [
            asyncio.create_task(
                self._watch_folder(account, folder, mons),
                name=f"imap-idle-{account}-{folder}",
            )
            for (account, folder), mons in groups.items()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _watch_folder(
        self,
        account: str,
        folder: str,
        monitors: list,
    ) -> None:
        backoff = 1
        while True:
            try:
                await self._idle_loop(account, folder, monitors)
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "IMAP watcher error for %s/%s: %s — retry in %ds",
                    account, folder, exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _idle_loop(
        self,
        account: str,
        folder: str,
        monitors: list,
    ) -> None:
        from app.helpers import ImapIdleConfig, imap_connect

        config = ImapIdleConfig(account=account, folder=folder, search=[])
        async with imap_connect(config, IMAP_ENV) as imap:
            typ, caps_data = await imap.capability()
            has_idle = b"IDLE" in caps_data[0] if caps_data else False

            if has_idle:
                await self._idle_wait(imap, monitors)
            else:
                await self._poll_wait(imap, monitors)

    async def _idle_wait(self, imap: Any, monitors: list) -> None:
        while True:
            await imap.idle_start(timeout=300)
            push = await imap.wait_server_push()
            await imap.idle_done()
            if any(b"EXISTS" in (line if isinstance(line, bytes) else str(line).encode()) for line in push):
                for m in monitors:
                    await self._scheduler.trigger(m.name, self._browser)

    async def _poll_wait(self, imap: Any, monitors: list) -> None:
        while True:
            await asyncio.sleep(60)
            await imap.noop()
            for m in monitors:
                await self._scheduler.trigger(m.name, self._browser)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest app/imap_watcher_test.py --no-cov -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/imap_watcher.py app/imap_watcher_test.py
git commit -m "feat: add ImapWatcher for IMAP IDLE connection management"
```

---

## Task 6: Wire `ImapWatcher` into `main.py` lifespan

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

- [ ] **Step 1: Write failing test**

In `app/main_test.py`, add:

```python
from app.main import get_imap_watcher


async def test_get_imap_watcher_returns_none_by_default():
    result = await get_imap_watcher()
    assert result is None
```

- [ ] **Step 2: Run test, verify failure**

```bash
uv run pytest app/main_test.py -k "imap_watcher" --no-cov -x -q
```

Expected: `ImportError` on `get_imap_watcher`.

- [ ] **Step 3: Add `get_imap_watcher` to `main.py`**

In `app/main.py`, add alongside the other module-level singletons (near `_git_sync`):

```python
_imap_watcher_task: asyncio.Task | None = None  # pragma: no cover
```

Add the dependency function alongside `get_git_sync`:

```python
async def get_imap_watcher() -> Optional[asyncio.Task]:  # pragma: no cover
    return _imap_watcher_task
```

In `main.py` imports, add:
```python
import asyncio
```
(if not already imported — check first).

- [ ] **Step 4: Run test**

```bash
uv run pytest app/main_test.py -k "imap_watcher" --no-cov -x -q
```

Expected: passes.

- [ ] **Step 5: Add lifespan wiring (pragma: no cover)**

In `app/main.py` inside the `lifespan` function, after `await _scheduler.start(_browser)`, add:

```python
    imap_monitors = [m for m in _scheduler._monitors if m.imap_idle]  # pragma: no cover
    if imap_monitors:  # pragma: no cover
        from app.imap_watcher import ImapWatcher  # pragma: no cover
        _imap_watcher_task = asyncio.create_task(  # pragma: no cover
            ImapWatcher(  # pragma: no cover
                monitors=imap_monitors,  # pragma: no cover
                scheduler=_scheduler,  # pragma: no cover
                browser=_browser,  # pragma: no cover
            ).run()  # pragma: no cover
        )  # pragma: no cover
```

In the lifespan cleanup section (before `await _browser.close()`), add:

```python
    if _imap_watcher_task is not None:  # pragma: no cover
        _imap_watcher_task.cancel()  # pragma: no cover
        try:  # pragma: no cover
            await _imap_watcher_task  # pragma: no cover
        except asyncio.CancelledError:  # pragma: no cover
            pass  # pragma: no cover
```

- [ ] **Step 6: Run full suite with coverage**

```bash
uv run pytest -x -q
```

Expected: all pass, 100% coverage.

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat: wire ImapWatcher into FastAPI lifespan"
```

---

## Task 7: Zitmaxx order monitor

**Files:**
- Create: `../changewatch-monitors/zitmaxx_order.py`

Note: this file lives in the `changewatch-monitors` repo, not the `changewatch` repo. Run these steps from `/home/stevendejong/workspace/personal/changewatch-monitors/`.

- [ ] **Step 1: Create the monitor file**

Create `zitmaxx_order.py` in `changewatch-monitors/`:

```python
_PRODUCT_NAME = "Zitmaxx Bestelling"

import re

from app.helpers import Monitor, ImapIdleConfig, imap_connect, imap_fetch_unseen, notify

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

_EMAIL_TYPES = {
    "verkoop@zitmaxx.nl": "Orderbevestiging",
    "automail@zitmaxx.nl": "Review verzoek",
    "aftersales@zitmaxx.nl": "Leveringsprognose",
}


@monitor.check
async def check(page, ctx):
    async with imap_connect(monitor.imap_idle) as imap:
        msgs = await imap_fetch_unseen(imap, monitor.imap_idle.search, ctx)

    for msg in msgs:
        subject = msg.get("Subject", "(geen onderwerp)")
        sender = msg.get("From", "")
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body else ""

        order_nr = next(iter(re.findall(r"\b\d{10}\b", subject + " " + text)), None)
        week_match = re.search(r"week\s+(\d+)", text, re.IGNORECASE)
        email_type = next(
            (label for addr, label in _EMAIL_TYPES.items() if addr in sender),
            "Update",
        )

        lines = [f"{email_type}: {subject}"]
        if order_nr:
            lines.append(f"Order: {order_nr}")
        if week_match:
            lines.append(f"Verwachte aankomst: week {week_match.group(1)}")

        ctx.logger.info(
            "zitmaxx email: %s (order=%s week=%s)",
            email_type,
            order_nr,
            week_match and week_match.group(1),
        )

        if ctx.apprise:
            await notify(
                ctx.apprise,
                title="Zitmaxx update",
                body="\n".join(lines),
                tags=monitor.notify_channels,
            )
```

- [ ] **Step 2: Commit and push to changewatch-monitors**

```bash
cd /home/stevendejong/workspace/personal/changewatch-monitors
git add zitmaxx_order.py
git commit -m "feat: add zitmaxx order IMAP IDLE monitor"
git pull --rebase && git push
```

- [ ] **Step 3: Add aerc account for `mail@stevenenanja.nl`**

In `~/.config/aerc/accounts.conf`, add below the existing account:

```ini
[mail@stevenenanja.nl]
source        = imaps://mail%40stevenenanja.nl:<url-encoded-password>@mail.steven-dejong.nl:993
outgoing      = smtps://mail%40stevenenanja.nl:<url-encoded-password>@mail.steven-dejong.nl:465
default       = INBOX
from          = Steven & Anja <mail@stevenenanja.nl>
copy-to       = Sent
```

The password special chars need URL-encoding: `*` → `%2A`.

---

## Task 8: k8s secret and deploy

**Files:**
- k8s secret `changewatch-secrets` (in-cluster)

- [ ] **Step 1: Add IMAP env var to k8s secret**

```bash
kubectl --kubeconfig ~/.kube/config-direct -n changewatch get secret changewatch-secrets -o json \
  | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
d['data']['IMAP_URL_MAIL_STEVENENANJA_NL'] = base64.b64encode(
    b'imaps://mail%40stevenenanja.nl:<PASSWORD>@mail.steven-dejong.nl:993'
).decode()
print(json.dumps(d))
" | kubectl --kubeconfig ~/.kube/config-direct apply -f -
```

Replace `<PASSWORD>` with the URL-encoded password (`*` → `%2A`).

- [ ] **Step 2: Add to local `.env` for dev**

In `/home/stevendejong/workspace/personal/changewatch/.env` (gitignored), add:

```
IMAP_URL_MAIL_STEVENENANJA_NL=imaps://mail%40stevenenanja.nl:<PASSWORD>@mail.steven-dejong.nl:993
```

- [ ] **Step 3: Run full test suite one final time**

```bash
cd /home/stevendejong/workspace/personal/changewatch
uv run pytest -x -q
```

Expected: all pass, 100% coverage.

- [ ] **Step 4: Push `changewatch` and sync**

```bash
git push
```

Then trigger sync:

```bash
curl -s -X POST https://changewatch.madebysteven.nl/sync
```

(If behind auth, use the internal cluster URL via the method established earlier in this session.)

- [ ] **Step 5: Verify watcher is running**

Check pod logs for IMAP watcher startup message:

```bash
kubectl --kubeconfig ~/.kube/config-direct -n changewatch logs -l app=changewatch --tail=50 | grep -i imap
```

Expected: log line showing IMAP watcher connected and IDLE on `INBOX` for `mail@stevenenanja.nl`.

---

## Self-Review Notes

- **Task 2** must land before any other task — `schedule=None` on `Monitor` is a breaking change without the scheduler fix.
- **Task 4 Step 3**: `RunContext` is referenced via `TYPE_CHECKING` in `helpers.py` to avoid a circular import (`helpers` → `runner` → `helpers`). The actual import is guarded.
- **Coverage**: all `imap_watcher.py` code is tested. The `# pragma: no cover` lines in `main.py` are limited to the lifespan wiring block only.
- **aioimaplib fetch response format**: `imap_fetch_unseen` looks for `tuple` items in the fetch response. If a future aioimaplib version changes this format, the helper is the single place to fix it.
- **IDLE keepalive**: `idle_start(timeout=300)` sends a keepalive every 5 minutes to prevent the server from dropping the connection silently.
