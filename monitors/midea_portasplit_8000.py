from __future__ import annotations

import json
import re

from app.helpers import Monitor, get_last_value, notify, record_metric, set_value

# (store_name, url, price_selector)
# ponytail: selector=None falls back to body text scan — only use when no specific price element exists
STORES: list[tuple[str, str, str | None]] = [
    ("Bauhaus 8000",   "https://nl.bauhaus/split-aircos/midea-split-airco-portasplit-cool-8000-btu/p/33946696", ".price"),
    ("Bauhaus 12000",  "https://nl.bauhaus/split-aircos/midea-split-airco-portasplit-12000-btu/p/31934233",     ".price"),
    ("Praxis 8000",    "https://www.praxis.nl/verwarmingen-airco-s/airco-s/mobiele-airco-s/midea-mobiele-airco-portasplit-8000-btu/10693023", None),
    ("Praxis 12000",   "https://www.praxis.nl/verwarmingen-airco-s/airco-s/vaste-airco-s/split-airco-s/midea-mobiele-split-airco-portasplit-12000-btu-koelt-verwarmt/10700978", None),
    ("Recharged",      "https://recharged.nl/airco/midea-portasplit/", None),
]

monitor = Monitor(
    name="midea_portasplit_8000",
    schedule="0 */4 * * *",
    notify_channels=["telegram"],
    display_name="Midea PortaSplit 8000",
    check_urls=[(name, url) for name, url, _ in STORES],
)

# Matches prices like "1.299,00" or "1299,00" or "1.299.00" — comma or dot as decimal separator
# Thousands separator dot only appears before exactly 3 digits (e.g. 1.299), never in "5.00"
_PRICE_RE = re.compile(r"(\d{1,3}(?:[.,]\d{3})?[.,]\d{2})")


def _parse_price(text: str) -> float | None:
    candidates = []
    for m in _PRICE_RE.findall(text):
        try:
            # Strip thousands separator (dot/comma before 3 digits), normalise decimal to dot
            normalised = re.sub(r"[.,](\d{3})", r"\1", m).replace(",", ".")
            v = float(normalised)
            if 300 <= v <= 2000:
                candidates.append(v)
        except ValueError:
            pass
    return min(candidates) if candidates else None


async def _fetch(page, name: str, url: str, selector: str | None) -> tuple[str, float] | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        if selector:
            text = await page.locator(selector).first.inner_text(timeout=10_000)
        else:
            text = await page.evaluate("() => document.body.innerText")
        price = _parse_price(text)
        if price is None:
            return None
        return (name, price)
    except Exception:
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
