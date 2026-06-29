from __future__ import annotations

import json
import re

from app.helpers import Monitor, get_last_value, notify, record_metric, set_value

# (store_name, url, price_selector)
# selector=None → body text scan; price_selector only used when available
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

# Matches Dutch price format: 599,00 or 1.299,00 (dot thousands, comma decimal)
_PRICE_RE = re.compile(r"\d{1,3}(?:\.\d{3})?(?:,\d{2})")

# Unavailability signals per store (lowercase match)
_UNAVAILABLE_SIGNALS = [
    "niet te koop",
    "uitverkocht",
    "niet beschikbaar",
    "niet leverbaar",
    "out of stock",
]


def _parse_price(text: str) -> float | None:
    for m in _PRICE_RE.findall(text):
        try:
            v = float(m.replace(".", "").replace(",", "."))
            if 300 <= v <= 2000:
                return v
        except ValueError:
            pass
    return None


def _is_unavailable(text: str) -> bool:
    lower = text.lower()
    return any(s in lower for s in _UNAVAILABLE_SIGNALS)


async def _fetch(page, name: str, url: str, selector: str | None) -> dict:
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        # Redirect away from product page = not found
        if resp and resp.url != url and "product" not in resp.url:
            return {"store": name, "available": False, "price": None, "reason": "redirected"}

        if selector:
            try:
                loc = page.locator(selector).first
                await loc.wait_for(state="visible", timeout=8_000)
                # Wait up to 5s for JS to replace template placeholder with real price
                for _ in range(10):
                    sel_text = await loc.inner_text(timeout=2_000)
                    if sel_text and "{{" not in sel_text:
                        break
                    await page.wait_for_timeout(500)
                text = sel_text if sel_text and "{{" not in sel_text else await page.evaluate("() => document.body.innerText")
            except Exception:
                text = await page.evaluate("() => document.body.innerText")
        else:
            text = await page.evaluate("() => document.body.innerText")

        if _is_unavailable(text):
            return {"store": name, "available": False, "price": None, "reason": "unavailable"}

        price = _parse_price(text)
        if price is None:
            return {"store": name, "available": False, "price": None, "reason": "no price found"}

        return {"store": name, "available": True, "price": price}
    except Exception as e:
        return {"store": name, "available": False, "price": None, "reason": str(e)[:80]}


@monitor.check
async def check(page, ctx):
    results = []
    for name, url, selector in STORES:
        r = await _fetch(page, name, url, selector)
        results.append(r)
        if r["available"]:
            ctx.logger.info("%s: available at €%.2f", name, r["price"])
        else:
            ctx.logger.info("%s: unavailable (%s)", name, r.get("reason", ""))

    payload = {s["store"]: {"available": s["available"], "price": s["price"]} for s in results}

    prev_raw = await get_last_value(ctx.db, monitor.name)
    prev = json.loads(prev_raw) if prev_raw else {}

    await set_value(ctx.db, monitor.name, json.dumps(payload))

    # Track lowest available price for InfluxDB
    available = [s for s in results if s["available"] and s["price"]]
    if available and ctx.influx:
        lowest = min(available, key=lambda s: s["price"])
        await record_metric(ctx.influx, monitor.name, lowest["price"], store=lowest["store"])

    if not ctx.apprise:
        return

    # Notify on availability change: unavailable → available
    newly_available = [
        s for s in results
        if s["available"]
        and not prev.get(s["store"], {}).get("available", False)
    ]
    for s in newly_available:
        await notify(
            ctx.apprise,
            title=f"Midea PortaSplit beschikbaar bij {s['store']}!",
            body=f"€{s['price']:.2f}" if s["price"] else "Prijs onbekend",
            tags=monitor.notify_channels,
        )

    # Notify on price drop (only for available stores that were already available)
    for s in results:
        if not s["available"] or not s["price"]:
            continue
        prev_store = prev.get(s["store"], {})
        if prev_store.get("available") and prev_store.get("price") and s["price"] < prev_store["price"]:
            await notify(
                ctx.apprise,
                title=f"Midea PortaSplit prijsdaling bij {s['store']}",
                body=f"€{prev_store['price']:.2f} → €{s['price']:.2f}",
                tags=monitor.notify_channels,
            )
