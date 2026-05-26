from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class MonitorConfig:
    name: str
    schedule: str
    url: str = ""
    selector: str = ""
    notify_channels: list[str] = field(default_factory=list)
    record_to_influx: bool = False
    wait_for_network_idle: bool = False


def parse_monitor(source: str) -> Optional[MonitorConfig]:
    """Extract monitor configuration from a Python monitor source file."""

    # Strip comment lines before parsing to avoid false positives
    non_comment_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    ]
    source_no_comments = "\n".join(non_comment_lines)

    # Extract name
    name_match = re.search(r'\bname\s*=\s*"([^"]+)"', source_no_comments)
    if not name_match:
        name_match = re.search(r"\bname\s*=\s*'([^']+)'", source_no_comments)
    if not name_match:
        return None
    name = name_match.group(1)

    # Extract schedule
    schedule_match = re.search(r'\bschedule\s*=\s*"([^"]+)"', source_no_comments)
    if not schedule_match:
        schedule_match = re.search(r"\bschedule\s*=\s*'([^']+)'", source_no_comments)
    if not schedule_match:
        return None
    schedule = schedule_match.group(1)

    # Extract url
    url = ""
    url_match = re.search(r'\burl\s*=\s*"([^"]+)"', source_no_comments)
    if not url_match:
        url_match = re.search(r"\burl\s*=\s*'([^']+)'", source_no_comments)
    if url_match:
        url = url_match.group(1)

    # Extract notify_channels list
    notify_channels: list[str] = []
    channels_match = re.search(r'notify_channels\s*=\s*\[([^\]]*)\]', source_no_comments, re.DOTALL)
    if channels_match:
        raw = channels_match.group(1)
        notify_channels = re.findall(r'["\']([^"\']+)["\']', raw)

    # Extract selector from extract_text call
    selector = ""
    selector_match = re.search(r'extract_text\s*\(\s*\w+\s*,\s*"([^"]+)"', source_no_comments)
    if not selector_match:
        selector_match = re.search(r"extract_text\s*\(\s*\w+\s*,\s*'([^']+)'", source_no_comments)
    if selector_match:
        selector = selector_match.group(1)

    # Detect record_to_influx
    record_to_influx = "record_metric" in source_no_comments

    # Detect wait_for_network_idle
    wait_for_network_idle = 'wait_for_load_state("networkidle")' in source_no_comments or \
                            "wait_for_load_state('networkidle')" in source_no_comments

    return MonitorConfig(
        name=name,
        schedule=schedule,
        url=url,
        selector=selector,
        notify_channels=notify_channels,
        record_to_influx=record_to_influx,
        wait_for_network_idle=wait_for_network_idle,
    )


def generate_monitor(config: MonitorConfig) -> str:
    """Generate a Python monitor source file from a MonitorConfig."""

    channels_repr = repr(config.notify_channels)

    # Build imports
    if config.record_to_influx:
        imports = "from app.helpers import Monitor, extract_text, get_last_value, set_value, notify, record_metric"
    else:
        imports = "from app.helpers import Monitor, extract_text, get_last_value, set_value, notify"

    # Build monitor constructor
    monitor_block = 'monitor = Monitor(\n    name={name},\n    schedule={schedule},\n    url={url},\n    notify_channels={channels_repr},\n)'.format(
        name=repr(config.name),
        schedule=repr(config.schedule),
        url=repr(config.url),
        channels_repr=channels_repr,
    )

    # Build check function body
    body_lines = []

    goto_line = '    await page.goto({url})'.format(url=repr(config.url))
    body_lines.append(goto_line)

    if config.wait_for_network_idle:
        body_lines.append('    await page.wait_for_load_state("networkidle")')

    body_lines.append('    value = await extract_text(page, {selector})'.format(selector=repr(config.selector)))
    body_lines.append('    prev = await get_last_value(ctx.db, {name})'.format(name=repr(config.name)))
    body_lines.append('    await set_value(ctx.db, {name}, value)'.format(name=repr(config.name)))
    body_lines.append('    if prev is not None and value != prev and ctx.apprise:')
    body_lines.append('        await notify(ctx.apprise, title={title}, body=value, tags={channels_repr})'.format(
        title=repr(config.name + " changed"),
        channels_repr=channels_repr,
    ))

    if config.record_to_influx:
        body_lines.append('    if ctx.influx:')
        body_lines.append('        await record_metric(ctx.influx, {name}, value)'.format(name=repr(config.name)))

    check_fn = "@monitor.check\nasync def check(page, ctx):\n" + "\n".join(body_lines)

    return "{imports}\n\n{monitor_block}\n\n\n{check_fn}\n".format(
        imports=imports,
        monitor_block=monitor_block,
        check_fn=check_fn,
    )
