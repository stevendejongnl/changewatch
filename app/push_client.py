import asyncio
import json
import logging
import os

from pywebpush import WebPushException, webpush

from app.db import Database

logger = logging.getLogger(__name__)


def vapid_public_key() -> str:
    return os.environ.get("VAPID_PUBLIC_KEY", "")


def _vapid_private_key() -> str:
    return os.environ.get("VAPID_PRIVATE_KEY", "")


def _vapid_subject() -> str:
    return os.environ.get("VAPID_SUBJECT", "mailto:steven@steven-dejong.nl")


class PushClient:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def enabled(self) -> bool:
        return bool(vapid_public_key() and _vapid_private_key())

    async def notify(self, title: str, body: str, url: str = "/") -> None:
        if not self.enabled:
            return
        subscriptions = await self._db.get_push_subscriptions()
        payload = json.dumps({"title": title, "body": body, "url": url})
        for sub in subscriptions:
            expired = await asyncio.to_thread(self._send, sub, payload)
            if expired:
                await self._db.remove_push_subscription(sub["endpoint"])

    def _send(self, sub: dict, payload: str) -> bool:
        """Send one push message. Returns True if the subscription is
        dead (404/410 - the browser unsubscribed or the endpoint expired)
        and should be removed."""
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=_vapid_private_key(),
                vapid_claims={"sub": _vapid_subject()},
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                return True
            logger.warning("push send failed for %s: %s", sub["endpoint"], exc)
        return False
