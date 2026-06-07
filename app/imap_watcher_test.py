import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.helpers import Monitor, ImapIdleConfig
from app.imap_watcher import ImapWatcher


@pytest.fixture
def monitors():
    cfg = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=["FROM", "@x.nl"])
    m = Monitor(name="test_mon", schedule=None, notify_channels=["telegram"], imap_idle=cfg)

    @m.check
    async def check(page, ctx):
        pass  # pragma: no cover

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
    mock_imap.has_capability = MagicMock(return_value=True)
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
    mock_imap.has_capability = MagicMock(return_value=False)
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
        async def check(page, ctx):
            pass  # pragma: no cover

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
