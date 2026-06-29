from app.helpers import Monitor, tweakers_price_check

monitor = Monitor(
    name="tp-link_tapo_p300",
    schedule="0 */2 * * *",
    url="https://tweakers.net/pricewatch/1934180/tp-link-tapo-p300-smart-wifi-stekkerdoos.html",
    metric="tp-link_tapo_p300",
    notify_channels=["telegram"],
    tags=["findthatproduct"],
    display_name="TP-Link Tapo P300 Smart WiFi Stekkerdoos",
)

@monitor.check
async def check(page, ctx):
    await page.goto(monitor.url, wait_until="domcontentloaded")
    await tweakers_price_check(page, ctx, monitor.display_name, monitor.notify_channels)
