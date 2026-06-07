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
    import re as _re
    from email.policy import default as _default_policy

    uid_key = f"{ctx.monitor_name}:_imap_uid"
    last_uid_str = await get_last_value(ctx.db, uid_key)

    if last_uid_str is None:
        # First run: seed by finding max existing UID via SEARCH + FETCH (not UID SEARCH)
        typ, data = await imap.search("ALL")
        seqnums = data[0].decode().split() if data[0] else []
        if seqnums:
            typ, fetch_data = await imap.fetch(seqnums[-1], "(UID)")
            max_uid = 0
            for item in fetch_data:
                raw = item[0] if isinstance(item, tuple) else item
                m = _re.search(rb"UID (\d+)", raw)
                if m:
                    max_uid = int(m.group(1))
                    break
        else:
            max_uid = 0
        await set_value(ctx.db, uid_key, str(max_uid))
        return []

    last_uid = int(last_uid_str)
    next_uid = last_uid + 1
    # "UID uid-set" is a valid SEARCH criterion (unlike UID SEARCH which some servers reject)
    criteria = list(search) + ["UID", f"{next_uid}:*"]
    typ, data = await imap.search(*criteria)
    seqnums = data[0].decode().split() if data[0] else []

    if not seqnums:
        return []

    messages = []
    max_new_uid = last_uid

    for seqnum in seqnums:
        typ, msg_data = await imap.fetch(seqnum, "(UID RFC822)")
        # aioimaplib returns flat list: [header_bytes, body_bytearray, b')', status_str]
        if len(msg_data) >= 2 and isinstance(msg_data[0], (bytes, bytearray)):
            uid_match = _re.search(rb"UID (\d+)", msg_data[0])
            uid = int(uid_match.group(1)) if uid_match else 0
            if uid >= next_uid and isinstance(msg_data[1], (bytes, bytearray)):
                msg = _email.message_from_bytes(bytes(msg_data[1]), policy=_default_policy)
                messages.append(msg)
                max_new_uid = max(max_new_uid, uid)

    if max_new_uid > last_uid:
        await set_value(ctx.db, uid_key, str(max_new_uid))
    return messages
