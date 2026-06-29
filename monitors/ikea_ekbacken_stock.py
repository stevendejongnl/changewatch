from app.helpers import Monitor, get_last_value, notify, record_metric, set_value

monitor = Monitor(
    name="ikea_ekbacken_stock",
    schedule="0 8-21 * * *",
    notify_channels=["telegram"],
    url="https://www.ikea.com/nl/nl/p/ekbacken-werkblad-essenpatroon-laminaat-90337620/",
    metric="ikea_stock",
    tags=["findthatproduct"],
    display_name="IKEA EKBACKEN Werkblad Essenpatroon",
)

TARGET_STORES = ["Amsterdam", "Delft", "Haarlem", "Utrecht"]


@monitor.check
async def check(page, ctx):
    await page.goto(monitor.url, wait_until="domcontentloaded", timeout=30000)

    # Dismiss OneTrust cookie consent if present (fresh context has no cookies)
    try:
        await page.locator("#onetrust-accept-btn-handler").click(timeout=5000)
    except Exception:
        pass

    # Give the SPA time to hydrate; networkidle may not settle on ad-heavy IKEA pages
    # ponytail: 20s cap — if it doesn't settle we proceed and let btn.wait_for catch it
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    # Open the in-store availability modal
    btn = page.get_by_role("button", name="Bekijk de winkelvoorraad")
    await btn.wait_for(state="visible", timeout=30000)
    await btn.click()
    await page.wait_for_selector("text=IKEA Amsterdam", timeout=15000)

    # Extract stock status for each target store
    stock: dict[str, bool] = {}
    for store in TARGET_STORES:
        btn = page.locator(f"button:has-text('IKEA {store}')").first
        text = await btn.inner_text(timeout=5000)
        stock[store] = "Op voorraad" in text or "Weinig voorraad" in text

    # Build a compact state string, e.g. "Amsterdam:0|Haarlem:1|Utrecht:0"
    state = "|".join(f"{s}:{int(v)}" for s, v in sorted(stock.items()))
    last = await get_last_value(ctx.db, monitor.name)

    # Notify for any store that just came in stock
    if last is not None:
        last_stock = {
            part.split(":")[0]: part.split(":")[1] == "1"
            for part in last.split("|")
            if ":" in part
        }
        newly_in_stock = [
            s for s in TARGET_STORES if stock.get(s) and not last_stock.get(s)
        ]
        if newly_in_stock and ctx.apprise:
            stores_str = ", ".join(newly_in_stock)
            await notify(
                ctx.apprise,
                title="IKEA EKBACKEN: op voorraad!",
                body=f"Nu beschikbaar in: {stores_str}\n{monitor.url}",
                tags=monitor.notify_channels,
            )

    if ctx.influx:
        for store, in_stock in stock.items():
            await record_metric(ctx.influx, "ikea_stock", int(in_stock), monitor=monitor.name, store=store)

    await set_value(ctx.db, monitor.name, state)
    ctx.logger.info("EKBACKEN stock: %s", state)
