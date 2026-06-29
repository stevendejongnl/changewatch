from app.helpers import Monitor, tweakers_price_check

monitor = Monitor(
    name="ftp_google_pixel_10_5g_12gb_128gb_zwart_obsi",
    schedule="0 */6 * * *",
    url="https://tweakers.net/pricewatch/2247202/google-pixel-10-256gb-opslag-zwart.html",
    metric="ftp_google_pixel_10_5g_12gb_128gb_zwart_obsi",
    notify_channels=["telegram"],
    tags=["findthatproduct"],
    display_name="Google Pixel 10, 256GB",
)

@monitor.check
async def check(page, ctx):
    await page.goto(monitor.url, wait_until="domcontentloaded")
    await tweakers_price_check(page, ctx, monitor.display_name, monitor.notify_channels)
