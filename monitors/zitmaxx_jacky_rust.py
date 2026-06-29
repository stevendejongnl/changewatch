from app.helpers import Monitor, get_last_value, set_value, notify, record_metric

monitor = Monitor(
    name="zitmaxx_jacky_rust",
    schedule="0 */2 * * *",
    notify_channels=["telegram"],
    url="https://pim.zitmaxx.nl/api/material?filterKeyword=jacky%20rust",
    display_name="Zitmaxx Jacky Bank (Rust)",
    display_url="https://www.zitmaxx.nl/kleurstalen-aanvragen",
    tags=["findthatproduct"],
)

STATUS_LABELS = {
    "available": "Beschikbaar",
    "disabled": "Niet beschikbaar",
}


@monitor.check
async def check(page, ctx):
    response = await page.request.get(monitor.url, headers={"User-Agent": "Mozilla/5.0"})

    if response.status == 429:
        ctx.logger.warning("zitmaxx: rate limited (429), skipping run")
        return

    data = await response.json()
    materials = data.get("_embedded", {}).get("material", [])

    available = [
        {"parent": mat["key"], "color": variant["name"]}
        for mat in materials
        for variant in mat.get("materials", [])
        if variant["sampleRequestStatus"] != "disabled"
    ]
    status = "available" if available else "disabled"

    ctx.logger.info("jacky rust status: %s, available: %s", status, available)

    last = await get_last_value(ctx.db, monitor.name)
    if last is not None and last != "available" and status == "available" and ctx.apprise:
        names = ", ".join(f"{v['parent']} {v['color']}" for v in available)
        await notify(
            ctx.apprise,
            title="Zitmaxx: Jacky Rust is beschikbaar!",
            body=f"Beschikbaar als kleurstaal: {names}\nhttps://www.zitmaxx.nl/kleurstalen-aanvragen",
            tags=monitor.notify_channels,
        )

    await set_value(ctx.db, monitor.name, status)
    if ctx.influx:
        await record_metric(ctx.influx, monitor.name, 1 if status == "available" else 0)
