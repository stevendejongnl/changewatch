import asyncio
import logging
from unittest.mock import AsyncMock, patch
import pytest
from aiohttp import web
from aiohttp import web as aio_web
from playwright.async_api import async_playwright

from app.helpers import Monitor, ImapIdleConfig, navigate, get_last_value, set_value, extract_text, extract_json, notify, record_metric, imap_connect, imap_fetch_unseen
from app.db import Database
from app.apprise_client import AppriseClient

# influx_client fixture is provided by conftest.py (skips if InfluxDB unreachable)


# ── Monitor dataclass ──────────────────────────────────────────────────────

def test_monitor_stores_attributes():
    m = Monitor(name="test", schedule="*/5 * * * *", notify_channels=["telegram"])
    assert m.name == "test"
    assert m.schedule == "*/5 * * * *"
    assert m.notify_channels == ["telegram"]


async def test_monitor_check_decorator_stores_function():
    m = Monitor(name="test", schedule="0 * * * *", notify_channels=[])

    @m.check
    async def run(page, ctx):
        pass

    assert m.fn is run
    await run(None, None)


def test_monitor_url_is_optional():
    m = Monitor(name="no_url", schedule="0 * * * *", notify_channels=[])
    assert m.url is None


# ── ImapIdleConfig dataclass ───────────────────────────────────────────────

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


# ── State helpers (use real in-memory SQLite via fixtures) ─────────────────

@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "helpers_test.db"))
    await database.init()
    yield database
    await database.close()


async def test_get_last_value_returns_none_before_set(db):
    result = await get_last_value(db, "my_monitor")
    assert result is None


async def test_set_value_then_get_last_value(db):
    await set_value(db, "my_monitor", "99.0")
    result = await get_last_value(db, "my_monitor")
    assert result == "99.0"


async def test_set_value_overwrites_previous(db):
    await set_value(db, "my_monitor", "99.0")
    await set_value(db, "my_monitor", "89.0")
    assert await get_last_value(db, "my_monitor") == "89.0"


# ── Browser helpers (real Playwright + real aiohttp server) ───────────────

@pytest.fixture
async def html_server():
    pages: dict[str, str] = {}

    async def serve(request: web.Request) -> web.Response:
        path = request.path.lstrip("/")
        body = pages.get(path, "")
        content_type = "application/json" if body.lstrip().startswith(("{", "[")) else "text/html"
        return web.Response(text=body, content_type=content_type)

    app = web.Application()
    app.router.add_get("/{path:.*}", serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", pages
    await runner.cleanup()


@pytest.fixture
async def browser():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        yield b
        await b.close()


async def test_extract_text_returns_element_content(html_server, browser):
    base_url, pages = html_server
    pages["price"] = '<html><body><span class="price">€42.50</span></body></html>'
    page = await browser.new_page()
    await page.goto(f"{base_url}/price")
    result = await extract_text(page, ".price")
    await page.close()
    assert result == "€42.50"


async def test_extract_text_strips_whitespace(html_server, browser):
    base_url, pages = html_server
    pages["padded"] = '<html><body><div id="val">  hello world  </div></body></html>'
    page = await browser.new_page()
    await page.goto(f"{base_url}/padded")
    result = await extract_text(page, "#val")
    await page.close()
    assert result == "hello world"


async def test_extract_json_returns_parsed_response(html_server, browser):
    base_url, pages = html_server
    pages["api/data"] = '{"price": 39.99, "in_stock": true}'
    page = await browser.new_page()
    result = await extract_json(page, f"{base_url}/api/data")
    await page.close()
    assert result["price"] == 39.99
    assert result["in_stock"] is True


async def test_extract_json_raises_runtime_error_for_non_json(html_server, browser):
    base_url, pages = html_server
    pages["bad"] = "<html>Service Unavailable</html>"
    page = await browser.new_page()
    with pytest.raises(RuntimeError, match="non-JSON response"):
        await extract_json(page, f"{base_url}/bad")
    await page.close()


async def test_extract_json_error_includes_status_and_body_snippet(html_server, browser):
    base_url, pages = html_server
    pages["empty"] = ""
    page = await browser.new_page()
    with pytest.raises(RuntimeError) as exc_info:
        await extract_json(page, f"{base_url}/empty")
    await page.close()
    assert "status=" in str(exc_info.value)
    assert "body=" in str(exc_info.value)


# ── navigate helper ────────────────────────────────────────────────────────

async def test_navigate_goes_to_url_directly(html_server, browser):
    base_url, pages = html_server
    pages["product"] = '<html><body>ok</body></html>'
    page = await browser.new_page()
    await navigate(page, f"{base_url}/product")
    assert page.url == f"{base_url}/product"
    await page.close()


async def test_navigate_accepts_consent_and_lands_on_target(browser):
    from aiohttp import web as aio_web

    async def handler(request):
        if request.path == "/product":
            if request.cookies.get("consented") != "1":
                raise aio_web.HTTPFound("/consent")
            return aio_web.Response(text='<html><body>product</body></html>', content_type='text/html')
        if request.path == "/consent":
            return aio_web.Response(
                text="<html><body>"
                     "<button onclick=\"document.cookie='consented=1'; window.location='/product'\">Accept All</button>"
                     "</body></html>",
                content_type='text/html',
            )
        return aio_web.Response(status=404)  # pragma: no cover

    app = aio_web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    try:
        page = await browser.new_page()
        await navigate(page, f"{base}/product")
        assert page.url == f"{base}/product"
        await page.close()
    finally:
        await runner.cleanup()


async def test_navigate_falls_back_when_no_consent_button(browser):
    from aiohttp import web as aio_web

    async def handler(request):
        if request.path == "/product":
            raise aio_web.HTTPFound("/gate")
        if request.path == "/gate":
            return aio_web.Response(text='<html><body>no buttons here</body></html>', content_type='text/html')
        return aio_web.Response(status=404)  # pragma: no cover

    app = aio_web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    try:
        page = await browser.new_page()
        await navigate(page, f"{base}/product")
        assert page.url == f"{base}/gate"
        await page.close()
    finally:
        await runner.cleanup()


async def test_navigate_continues_when_consent_click_does_not_redirect(browser, monkeypatch):
    import app.helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "_CONSENT_URL_TIMEOUT", 200)

    from aiohttp import web as aio_web

    async def handler(request):
        if request.path == "/product":
            raise aio_web.HTTPFound("/gate")
        if request.path == "/gate":
            return aio_web.Response(
                text='<html><body><button onclick="void(0)">Accept</button></body></html>',
                content_type='text/html',
            )
        return aio_web.Response(status=404)  # pragma: no cover

    app = aio_web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    try:
        page = await browser.new_page()
        await navigate(page, f"{base}/product")
        assert page.url == f"{base}/gate"
        await page.close()
    finally:
        await runner.cleanup()


# ── notify helper ─────────────────────────────────────────────────────────

@pytest.fixture
async def apprise_capture_server():
    received: list[dict] = []

    async def handler(request: aio_web.Request) -> aio_web.Response:
        received.append(await request.json())
        return aio_web.Response(status=200)

    app = aio_web.Application()
    app.router.add_post("/", handler)
    runner = aio_web.AppRunner(app)
    await runner.setup()
    site = aio_web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield port, received
    await runner.cleanup()


async def test_notify_delegates_to_apprise_client(apprise_capture_server, monkeypatch):
    port, received = apprise_capture_server
    monkeypatch.setenv("APPRISE_URL_TEST", f"json://127.0.0.1:{port}/")
    client = AppriseClient()
    await notify(client, "title", "body", tags=["test"])
    assert len(received) == 1
    assert received[0]["title"] == "title"


# ── record_metric helper ──────────────────────────────────────────────────
# influx_client fixture provided by conftest.py — skipped if InfluxDB unreachable

async def test_record_metric_delegates_to_influx_client():
    class StubInfluxClient:
        def __init__(self):
            self.written: list[tuple] = []

        async def write(self, measurement, value, **tags):
            self.written.append((measurement, value, tags))

    stub = StubInfluxClient()
    await record_metric(stub, "price", 42.5, monitor="test_mon")
    assert len(stub.written) == 1
    assert stub.written[0][0] == "price"
    assert stub.written[0][1] == 42.5
    assert stub.written[0][2]["monitor"] == "test_mon"


# ── imap_connect ──────────────────────────────────────────────────────────

from app.runner import RunContext


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


async def test_imap_connect_suppresses_logout_error_on_exception():
    mock_imap = AsyncMock()
    mock_imap.wait_hello_from_server = AsyncMock()
    mock_imap.login = AsyncMock(return_value=("OK", [b"OK"]))
    mock_imap.select = AsyncMock(return_value=("OK", [b"1"]))
    mock_imap.logout = AsyncMock(side_effect=OSError("connection lost"))

    config = ImapIdleConfig(account="a@b.nl", folder="INBOX", search=[])
    env = {"IMAP_URL_A_B_NL": "imaps://a%40b.nl:p@host:993"}

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_imap):
        with pytest.raises(RuntimeError):
            async with imap_connect(config, env) as _:
                raise RuntimeError("body error")

    mock_imap.logout.assert_called_once()


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
