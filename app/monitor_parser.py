from dataclasses import dataclass, field
from typing import Optional
import json
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
    metric: Optional[str] = None


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

    # Extract metric
    metric: Optional[str] = None
    metric_match = re.search(r'\bmetric\s*=\s*"([^"]+)"', source_no_comments)
    if not metric_match:
        metric_match = re.search(r"\bmetric\s*=\s*'([^']+)'", source_no_comments)
    if metric_match:
        metric = metric_match.group(1)

    return MonitorConfig(
        name=name,
        schedule=schedule,
        url=url,
        selector=selector,
        notify_channels=notify_channels,
        record_to_influx=record_to_influx,
        wait_for_network_idle=wait_for_network_idle,
        metric=metric,
    )


def slugify(name: str) -> str:
    """Lowercase, URL-safe identifier: spaces → _, strip non-alphanum/-/_, collapse."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9_-]", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_-")


def generate_monitor(config: MonitorConfig) -> str:
    """Generate a Python monitor source file from a MonitorConfig."""

    channels_repr = json.dumps(config.notify_channels)

    # Build imports
    if config.record_to_influx:
        imports = "from app.helpers import Monitor, navigate, extract_text, get_last_value, set_value, notify, record_metric"
    else:
        imports = "from app.helpers import Monitor, navigate, extract_text, get_last_value, set_value, notify"

    # Build monitor constructor
    monitor_fields = [
        f'    name={json.dumps(config.name)},',
        f'    schedule={json.dumps(config.schedule)},',
        f'    url={json.dumps(config.url)},',
    ]
    if config.metric:
        monitor_fields.append(f'    metric={json.dumps(config.metric)},')
    monitor_fields.append(f'    notify_channels={channels_repr},')
    monitor_block = 'monitor = Monitor(\n' + '\n'.join(monitor_fields) + '\n)'

    # Build check function body
    body_lines = []

    body_lines.append('    await navigate(page, {url})'.format(url=json.dumps(config.url)))

    if config.wait_for_network_idle:
        body_lines.append('    await page.wait_for_load_state("networkidle")')

    body_lines.append('    value = await extract_text(page, {selector})'.format(selector=json.dumps(config.selector)))
    body_lines.append('    prev = await get_last_value(ctx.db, {name})'.format(name=json.dumps(config.name)))
    body_lines.append('    await set_value(ctx.db, {name}, value)'.format(name=json.dumps(config.name)))
    body_lines.append('    if prev is not None and value != prev and ctx.apprise:')
    body_lines.append('        await notify(ctx.apprise, title={title}, body=value, tags={channels_repr})'.format(
        title=json.dumps(config.name + " changed"),
        channels_repr=channels_repr,
    ))

    if config.record_to_influx:
        body_lines.append('    if ctx.influx:')
        body_lines.append('        await record_metric(ctx.influx, {name}, value)'.format(name=json.dumps(config.name)))

    check_fn = "@monitor.check\nasync def check(page, ctx):\n" + "\n".join(body_lines)

    return "{imports}\n\n{monitor_block}\n\n{check_fn}\n".format(
        imports=imports,
        monitor_block=monitor_block,
        check_fn=check_fn,
    )
