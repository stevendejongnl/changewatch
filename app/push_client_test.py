from unittest.mock import MagicMock, patch

import pytest
from pywebpush import WebPushException

from app.db import Database
from app.push_client import PushClient


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


def test_enabled_false_without_keys(monkeypatch):
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert PushClient(db=None).enabled is False


def test_enabled_true_with_both_keys(monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    assert PushClient(db=None).enabled is True


async def test_notify_is_a_noop_when_disabled(db, monkeypatch):
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    await db.add_push_subscription("https://push.example/ep1", "p", "a")
    with patch("app.push_client.webpush") as mock_webpush:
        await PushClient(db).notify("title", "body")
    mock_webpush.assert_not_called()


async def test_notify_sends_to_every_subscription(db, monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")
    await db.add_push_subscription("https://push.example/ep1", "p1", "a1")
    await db.add_push_subscription("https://push.example/ep2", "p2", "a2")

    with patch("app.push_client.webpush") as mock_webpush:
        await PushClient(db).notify("title", "body", url="/monitors/x")

    assert mock_webpush.call_count == 2
    endpoints = {c.kwargs["subscription_info"]["endpoint"] for c in mock_webpush.call_args_list}
    assert endpoints == {"https://push.example/ep1", "https://push.example/ep2"}


async def test_notify_removes_expired_subscription_on_410(db, monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    await db.add_push_subscription("https://push.example/dead", "p", "a")

    response = MagicMock(status_code=410)
    with patch("app.push_client.webpush", side_effect=WebPushException("gone", response=response)):
        await PushClient(db).notify("title", "body")

    assert await db.get_push_subscriptions() == []


async def test_notify_keeps_subscription_on_other_errors(db, monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    await db.add_push_subscription("https://push.example/flaky", "p", "a")

    response = MagicMock(status_code=500)
    with patch("app.push_client.webpush", side_effect=WebPushException("server error", response=response)):
        await PushClient(db).notify("title", "body")

    subs = await db.get_push_subscriptions()
    assert len(subs) == 1
