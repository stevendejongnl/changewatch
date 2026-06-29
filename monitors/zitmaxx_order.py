import re

from app.helpers import Monitor, ImapIdleConfig, imap_connect, imap_fetch_unseen, notify, set_value

monitor = Monitor(
    name="zitmaxx_order",
    schedule=None,
    imap_idle=ImapIdleConfig(
        account="mail@stevenenanja.nl",
        folder="INBOX",
        search=["FROM", "@zitmaxx.nl"],
    ),
    notify_channels=["telegram"],
    display_url="https://www.zitmaxx.nl/",
)

_EMAIL_TYPES = {
    "verkoop@zitmaxx.nl": "Orderbevestiging",
    "automail@zitmaxx.nl": "Review verzoek",
    "aftersales@zitmaxx.nl": "Leveringsprognose",
}


@monitor.check
async def check(page, ctx):
    async with imap_connect(monitor.imap_idle) as imap:
        msgs = await imap_fetch_unseen(imap, monitor.imap_idle.search, ctx)

    last_summary = None
    for msg in msgs:
        subject = msg.get("Subject", "(geen onderwerp)")
        sender = msg.get("From", "")
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body else ""

        order_nr = next(iter(re.findall(r"\b\d{10}\b", subject + " " + text)), None)
        week_match = re.search(r"week\s+(\d+)", text, re.IGNORECASE)
        email_type = next(
            (label for addr, label in _EMAIL_TYPES.items() if addr in sender),
            "Update",
        )

        parts = [email_type]
        if order_nr:
            parts.append(f"order {order_nr}")
        if week_match:
            parts.append(f"week {week_match.group(1)}")
        last_summary = " | ".join(parts)

        lines = [f"{email_type}: {subject}"]
        if order_nr:
            lines.append(f"Order: {order_nr}")
        if week_match:
            lines.append(f"Verwachte aankomst: week {week_match.group(1)}")

        ctx.logger.info(
            "zitmaxx email: %s (order=%s week=%s)",
            email_type,
            order_nr,
            week_match and week_match.group(1),
        )

        if ctx.apprise:
            await notify(
                ctx.apprise,
                title="Zitmaxx update",
                body="\n".join(lines),
                tags=monitor.notify_channels,
            )

    if last_summary:
        await set_value(ctx.db, monitor.name, last_summary)
