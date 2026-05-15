from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from playwright.async_api import Page

from app.db import Database

if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.influx import InfluxClient


@dataclass
class Monitor:
    name: str
    schedule: str
    notify_channels: list[str]
    url: Optional[str] = None
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


async def extract_json(page: Page, url: str, timeout: int = 10_000) -> Any:
    """Fetch a JSON URL directly using the browser request context (respects cookies/auth)."""
    import json
    response = await page.request.get(url, timeout=timeout)
    text = await response.text()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"non-JSON response from {url}: status={response.status} body={text[:200]!r}"
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
