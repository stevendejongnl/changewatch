from app.helpers import Monitor, extract_text, get_last_value, set_value, notify

monitor = Monitor(
    name="example_price",
    schedule="*/30 * * * *",
    notify_channels=[],
    url="https://example.com",
)


@monitor.check
async def check(page, ctx):
    await page.goto(monitor.url)
    heading = await extract_text(page, "h1")

    last = await get_last_value(ctx.db, monitor.name)
    if last is not None and heading != last and ctx.apprise:
        await notify(
            ctx.apprise,
            title=f"{monitor.name}: content changed",
            body=f"{last!r} → {heading!r}",
            tags=monitor.notify_channels,
        )

    await set_value(ctx.db, monitor.name, heading)
