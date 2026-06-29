from __future__ import annotations

import json
import re

from app.helpers import Monitor, get_last_value, notify, record_metric, set_value

# (store_name, url, price_selector)
# ponytail: selector=None falls back to body text scan — only use when no specific price element exists
STORES: list[tuple[str, str, str | None]] = [
    ("bauhaus_8000",  "https://nl.bauhaus.nl/split-aircos/midea-split-airco-portasplit-cool-8000-btu/p/33946696", ".price"),
    ("bauhaus_12000", "https://nl.bauhaus.nl/split-aircos/midea-split-airco-portasplit-12000-btu/p/31934233",     ".price"),
    ("praxis_8000",   "https://www.praxis.nl/verwarmingen-airco-s/airco-s/mobiele-airco-s/midea-mobiele-airco-portasplit-8000-btu/10693023", None),
    ("praxis_12000",  "https://www.praxis.nl/verwarmingen-airco-s/airco-s/vaste-airco-s/split-airco-s/midea-mobiele-split-airco-portasplit-12000-btu-koelt-verwarmt/10700978", None),
    ("recharged",     "https://recharged.nl/airco/midea-portasplit/", None),
]

monitor = Monitor(
    name="midea_portasplit_8000",
    schedule="0 */4 * * *",
    notify_channels=["telegram"],
    display_name="Midea PortaSplit 8000",
)

_PRICE_RE = re.compile(r"(\d{1,4}[,.]\d{2})")


def _parse_price(text: str) -> float | None:
    candidates = []
    for m in _PRICE_RE.findall(text):
        try:
            v = float(m.replace(".", "").replace(",", "."))
            if 300 <= v <= 2000:
                candidates.append(v)
        except ValueError:
            pass
    return min(candidates) if candidates else None


async def _fetch(page, name: str, url: str, selector: str | None) -> tuple[str, float] | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        target = page.locator(selector) if selector else page.locator("body")
        text = await target.first.inner_text(timeout=10_000)
        price = _parse_price(text)
        if price is None:
            return None
        return (name, price)
    except Exception as exc:
        return None


@monitor.check
async def check(page, ctx):
    results: list[tuple[str, float]] = []
    for name, url, selector in STORES:
        r = await _fetch(page, name, url, selector)
        if r:
            results.append(r)
            ctx.logger.info("%s: %.2f EUR", r[0], r[1])
        else:
            ctx.logger.warning("%s: no price found", name)

    if not results:
        ctx.logger.error("no prices found across all stores")
        return

    lowest_store, lowest_price = min(results, key=lambda x: x[1])
    payload = {"lowest_price": lowest_price, "lowest_store": lowest_store, "all_prices": dict(results)}

    prev_raw = await get_last_value(ctx.db, monitor.name)
    prev = json.loads(prev_raw) if prev_raw else None

    await set_value(ctx.db, monitor.name, json.dumps(payload))

    if ctx.influx:
        await record_metric(ctx.influx, monitor.name, lowest_price, store=lowest_store)

    if prev and lowest_price < prev["lowest_price"] and ctx.apprise:
        await notify(
            ctx.apprise,
            title="Midea PortaSplit 8000 price drop",
            body=f"€{prev['lowest_price']:.2f} → €{lowest_price:.2f} at {lowest_store}",
            tags=monitor.notify_channels,
        )
