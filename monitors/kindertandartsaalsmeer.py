from app.helpers import Monitor, get_last_value, notify, set_value

monitor = Monitor(
    name="kindertandartsaalsmeer",
    schedule="0 * * * *",
    notify_channels=["telegram"],
    url="https://www.kindertandartsaalsmeer.nl/",
)

_PARKED_SIGNALS = [
    "domain",
    "parking",
    "coming soon",
    "under construction",
    "te koop",
    "for sale",
    "buy this domain",
    "something amazing will be constructed",  # directadmin placeholder
    "directadmin",
    "upload your website",
]


@monitor.check
async def check(page, ctx):
    try:
        response = await page.goto(monitor.url, wait_until="domcontentloaded", timeout=30000)
        status = response.status if response else 0
    except Exception:
        status = 0

    if status == 200:
        title = (await page.title()).lower()
        body = (await page.inner_text("body")).lower()[:500]
        combined = title + " " + body
        is_parked = any(signal in combined for signal in _PARKED_SIGNALS)
        state = "not_live" if is_parked else "live"
    else:
        state = "not_live"

    prev = await get_last_value(ctx.db, monitor.name)
    await set_value(ctx.db, monitor.name, state)
    ctx.logger.info("kindertandartsaalsmeer: %s (was %s)", state, prev)

    if prev is not None and prev != "live" and state == "live" and ctx.apprise:
        await notify(
            ctx.apprise,
            title="Kindertandarts Aalsmeer is live!",
            body=f"Website online: {monitor.url}",
            tags=monitor.notify_channels,
        )
