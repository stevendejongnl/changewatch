from app.helpers import Monitor, extract_text, get_last_value, set_value, notify, record_metric

monitor = Monitor(
    name="example_price",
    schedule="*/30 * * * *",
    notify_channels=["telegram"],
    url="https://example.com/product",
)


@monitor.check
async def check(page, ctx):
    await page.goto(monitor.url)
    raw = await extract_text(page, ".price")
    price = float(raw.replace("€", "").replace(",", ".").strip())

    if ctx.influx:
        await record_metric(ctx.influx, "price", price, monitor=monitor.name)

    last = await get_last_value(ctx.db, monitor.name)
    if last is not None and price < float(last) and ctx.apprise:
        await notify(
            ctx.apprise,
            title=f"{monitor.name}: price dropped",
            body=f"€{last} → €{price}",
            tags=monitor.notify_channels,
        )

    await set_value(ctx.db, monitor.name, str(price))
