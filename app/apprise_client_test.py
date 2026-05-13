import pytest
from aiohttp import web

from app.apprise_client import AppriseClient


@pytest.fixture
async def capture_server():
    """Real HTTP server that records Apprise JSON notifications."""
    received: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        received.append(await request.json())
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield port, received
    await runner.cleanup()


@pytest.fixture
def client_with_test_channel(capture_server, monkeypatch):
    port, _ = capture_server
    monkeypatch.setenv("APPRISE_URL_TEST", f"json://127.0.0.1:{port}/")
    return AppriseClient(), capture_server


async def test_notify_delivers_to_configured_channel(client_with_test_channel):
    client, (_, received) = client_with_test_channel
    await client.notify("Price drop", "€50 → €39", tags=["test"])
    assert len(received) == 1
    assert received[0]["title"] == "Price drop"


async def test_notify_missing_channel_does_not_raise(client_with_test_channel):
    client, _ = client_with_test_channel
    await client.notify("Alert", "body", tags=["unknown_channel"])


async def test_notify_multiple_tags_delivers_to_each_channel(capture_server, monkeypatch):
    port, received = capture_server
    monkeypatch.setenv("APPRISE_URL_CHANNEL_A", f"json://127.0.0.1:{port}/")
    monkeypatch.setenv("APPRISE_URL_CHANNEL_B", f"json://127.0.0.1:{port}/")
    client = AppriseClient()
    await client.notify("Multi", "body", tags=["channel_a", "channel_b"])
    assert len(received) == 2


async def test_resolve_channels_reads_from_env(monkeypatch):
    monkeypatch.setenv("APPRISE_URL_TELEGRAM", "tgram://token/chatid")
    client = AppriseClient()
    assert "telegram" in client.resolved_channels()
