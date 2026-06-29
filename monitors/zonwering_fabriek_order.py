from datetime import date

from app.helpers import Monitor, get_last_value, set_value, notify

monitor = Monitor(
    name="zonwering_fabriek_order",
    schedule="0 */2 * * *",
    notify_channels=["telegram"],
    url="https://www.zonwering-fabriek.nl/wp-admin/admin-ajax.php",
    display_name="Zonwering-fabriek Bestelling",
    display_url="https://www.zonwering-fabriek.nl/orderstatus/?orderstatus_nr=3768301&orderstatus_mail=mail@stevenenanja.nl",
)

ORDER_NR = "3768301"
EMAIL = "mail@stevenenanja.nl"
PAGE_ID = "1023126"

# ponytail: ISO weekday numbers for Dutch day names from the API
_WEEKDAYS = {"MAANDAG": 1, "DINSDAG": 2, "WOENSDAG": 3, "DONDERDAG": 4, "VRIJDAG": 5, "ZATERDAG": 6, "ZONDAG": 7}

STATUS_LABELS = {
    "processing": "In behandeling",
    "dealer": "Order definitief",
    "productie": "In productie",
    "order_ready": "Klaar voor verzending",
    "order_shipped": "Onderweg",
    "take_away": "Klaar voor afhalen",
    "completed": "Afgerond",
    "cancelled": "Geannuleerd",
}


@monitor.check
async def check(page, ctx):
    response = await page.request.post(
        monitor.url,
        form={
            "action": "orderstatus",
            "order_nr": ORDER_NR,
            "order_mail": EMAIL,
            "page_id": PAGE_ID,
        },
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    data = await response.json()

    status = data.get("order_status")
    label = STATUS_LABELS.get(status, status) if status else "Geen status gevonden"
    ctx.logger.info("zonwering order %s status: %s (%s)", ORDER_NR, label, status)

    last = await get_last_value(ctx.db, monitor.name)
    if last is not None and last != status and status and ctx.apprise:
        addr = data.get("address") or {}
        dlv = data.get("delivery") or {}
        extra = "\n".join(
            line for line in (
                f"Adres: {', '.join(p for p in (addr.get('street'), addr.get('city')) if p)}",
                f"Geleverd door: {dlv['condition']}" if dlv.get("condition") else "",
                (
                    f"Levering: {date.fromisocalendar(date.today().year, int(dlv['date']), _WEEKDAYS[dlv['day']]).strftime('%d-%m-%Y')} ({dlv['day'].capitalize()})"
                    if dlv.get("date") and _WEEKDAYS.get(dlv.get("day", ""))
                    else f"Verw. leverweek: Week {dlv['date']}" if dlv.get("date") else ""
                ),
            ) if line
        )
        await notify(
            ctx.apprise,
            title="Zonwering-fabriek: Order status gewijzigd!",
            body=f"Order {ORDER_NR}: {label}\n\n{extra}",
            tags=monitor.notify_channels,
        )

    if status:
        await set_value(ctx.db, monitor.name, status)
