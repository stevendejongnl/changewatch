from app.helpers import Monitor, tweakers_price_check

monitor = Monitor(
    name="tp-link_deco_x50",
    schedule="0 */2 * * *",
    url="https://tweakers.net/pricewatch/1786790/tp-link-deco-x50-1-pack.html",
    metric="tp-link_deco_x50",
    notify_channels=["telegram"],
    tags=["findthatproduct"],
    display_name="TP-Link Deco X50 (1-pack)",
)

@monitor.check
async def check(page, ctx):
    await page.goto(monitor.url, wait_until="domcontentloaded")
    await tweakers_price_check(page, ctx, monitor.display_name, monitor.notify_channels)
