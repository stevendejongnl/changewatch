from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from playwright.async_api import Page

from app.db import Database

if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.influx import InfluxClient

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
class Monitor:
    name: str
    schedule: str
    notify_channels: list[str]
    url: Optional[str] = None
    metric: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    display_name: str = ""
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
