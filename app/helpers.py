from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from playwright.async_api import Page

from app.db import Database

if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.influx import InfluxClient
    from app.runner import RunContext

_CONSENT_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Akkoord')",
    "button:has-text('Accept')",
    "button:has-text('Agree')",
    "button:has-text('I agree')",
    "button:has-text('Tout accepter')",
    "button:has-text('Alles accepteren')",
    "#accept-all",
    "[aria-label='Accept all']",
]
_CONSENT_CLICK_TIMEOUT = 2_000
_CONSENT_URL_TIMEOUT = 5_000


@dataclass
class ImapIdleConfig:
    account: str
    folder: str
    search: list[str]


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


async def get_last_value(db: Database, monitor_name: str) -> Optional[str]:
    return await db.get_last_value(monitor_name)


async def set_value(db: Database, monitor_name: str, value: str) -> None:
    await db.set_value(monitor_name, value)


async def extract_text(page: Page, selector: str, timeout: int = 10_000) -> str:
    element = await page.wait_for_selector(selector, timeout=timeout)
    text = await element.inner_text()
    return text.strip()


async def navigate(page: Page, url: str) -> None:
    """Navigate to url, auto-accepting inline consent gates when redirected."""
    await page.goto(url)
    if page.url == url:
        return
    for sel in _CONSENT_SELECTORS:
        loc = page.locator(sel)
        if await loc.count() > 0:
            try:
                await loc.first.click(timeout=_CONSENT_CLICK_TIMEOUT)
                await page.wait_for_url(url, timeout=_CONSENT_URL_TIMEOUT)
                return
            except Exception:
                pass
    await page.goto(url)


async def extract_json(page: Page, url: str, timeout: int = 10_000) -> Any:
    """Fetch a JSON URL via httpx. The page parameter is kept for API compatibility."""
    import httpx
    timeout_s = timeout / 1000
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, timeout=timeout_s)
    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(
            f"non-JSON response from {url}: status={response.status_code} body={response.text[:200]!r}"
        ) from exc


async def notify(
    apprise_client: "AppriseClient",
    title: str,
    body: str,
    tags: list[str] | None = None,
) -> None:
    await apprise_client.notify(title=title, body=body, tags=tags or [])


async def record_metric(
    influx_client: "InfluxClient",
    measurement: str,
    value: float | int,
    **tags: str,
) -> None:
    await influx_client.write(measurement, value, **tags)


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
