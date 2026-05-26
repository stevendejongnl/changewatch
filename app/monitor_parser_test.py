import ast

from app.monitor_parser import MonitorConfig, parse_monitor, generate_monitor

STANDARD_SOURCE = '''
from app.helpers import Monitor, extract_text, get_last_value, set_value, notify

monitor = Monitor(
    name="test_monitor",
    schedule="*/5 * * * *",
    url="https://example.com",
    notify_channels=["telegram", "email"],
)

@monitor.check
async def check(page, ctx):
    value = await extract_text(page, ".price")
    prev = await get_last_value(ctx.db, "test_monitor")
    await set_value(ctx.db, "test_monitor", value)
'''


def test_parse_monitor_extracts_name():
    config = parse_monitor(STANDARD_SOURCE)
    assert config is not None
    assert config.name == "test_monitor"


def test_parse_monitor_extracts_schedule():
    config = parse_monitor(STANDARD_SOURCE)
    assert config is not None
    assert config.schedule == "*/5 * * * *"


def test_parse_monitor_extracts_url():
    config = parse_monitor(STANDARD_SOURCE)
    assert config is not None
    assert config.url == "https://example.com"


def test_parse_monitor_extracts_channels():
    config = parse_monitor(STANDARD_SOURCE)
    assert config is not None
    assert config.notify_channels == ["telegram", "email"]


def test_parse_monitor_extracts_selector():
    config = parse_monitor(STANDARD_SOURCE)
    assert config is not None
    assert config.selector == ".price"


def test_parse_monitor_returns_none_when_name_missing():
    source = '''
monitor = Monitor(
    schedule="*/5 * * * *",
    url="https://example.com",
    notify_channels=[],
)
'''
    assert parse_monitor(source) is None


def test_parse_monitor_returns_none_when_schedule_missing():
    source = '''
monitor = Monitor(
    name="test_monitor",
    url="https://example.com",
    notify_channels=[],
)
'''
    assert parse_monitor(source) is None


def test_parse_monitor_detects_record_to_influx():
    source = STANDARD_SOURCE + '\n    await record_metric(ctx.influx, "price", 42.0)\n'
    config = parse_monitor(source)
    assert config is not None
    assert config.record_to_influx is True


def test_parse_monitor_detects_wait_for_network_idle():
    source = STANDARD_SOURCE + '\n    await page.wait_for_load_state("networkidle")\n'
    config = parse_monitor(source)
    assert config is not None
    assert config.wait_for_network_idle is True


def test_parse_monitor_defaults_no_influx():
    config = parse_monitor(STANDARD_SOURCE)
    assert config is not None
    assert config.record_to_influx is False


def test_parse_monitor_defaults_no_networkidle():
    config = parse_monitor(STANDARD_SOURCE)
    assert config is not None
    assert config.wait_for_network_idle is False


def test_parse_monitor_empty_channels():
    source = '''
monitor = Monitor(
    name="test_monitor",
    schedule="*/5 * * * *",
    url="https://example.com",
)
'''
    config = parse_monitor(source)
    assert config is not None
    assert config.notify_channels == []


def test_generate_monitor_roundtrip():
    config = MonitorConfig(
        name="my_monitor",
        schedule="0 * * * *",
        url="https://example.com/page",
        selector=".price",
        notify_channels=["telegram"],
        record_to_influx=False,
        wait_for_network_idle=False,
    )
    generated = generate_monitor(config)
    parsed = parse_monitor(generated)
    assert parsed is not None
    assert parsed.name == config.name
    assert parsed.schedule == config.schedule
    assert parsed.url == config.url
    assert parsed.selector == config.selector
    assert parsed.notify_channels == config.notify_channels
    assert parsed.record_to_influx == config.record_to_influx
    assert parsed.wait_for_network_idle == config.wait_for_network_idle


def test_generate_monitor_contains_name():
    config = MonitorConfig(name="my_unique_monitor", schedule="0 * * * *")
    output = generate_monitor(config)
    assert "my_unique_monitor" in output


def test_generate_monitor_networkidle_flag():
    config = MonitorConfig(
        name="idle_monitor",
        schedule="0 * * * *",
        wait_for_network_idle=True,
    )
    output = generate_monitor(config)
    assert 'wait_for_load_state("networkidle")' in output


def test_generate_monitor_influx_flag():
    config = MonitorConfig(
        name="influx_monitor",
        schedule="0 * * * *",
        record_to_influx=True,
    )
    output = generate_monitor(config)
    assert "record_metric" in output


def test_parse_monitor_ignores_base_url():
    source = '''
monitor = Monitor(
    name="my_monitor",
    schedule="*/5 * * * *",
    base_url="https://wrong.com",
    notify_channels=[],
)

@monitor.check
async def check(page, ctx):
    pass
'''
    config = parse_monitor(source)
    assert config is not None
    assert config.url == ""


def test_generate_monitor_valid_python():
    config = MonitorConfig(
        name="price_monitor",
        schedule="*/30 * * * *",
        url="https://example.com/product",
        selector='.price[data-id="1"]',
        notify_channels=["telegram"],
        record_to_influx=False,
        wait_for_network_idle=False,
    )
    generated = generate_monitor(config)
    ast.parse(generated)  # raises SyntaxError if escaping is broken


def test_generate_monitor_uses_navigate_helper():
    config = MonitorConfig(name="nav_monitor", schedule="0 * * * *", url="https://example.com")
    output = generate_monitor(config)
    assert "navigate" in output
    assert "page.goto" not in output


def test_parse_monitor_single_quoted_fields():
    source = """
monitor = Monitor(
    name='my_mon',
    schedule='*/5 * * * *',
    url='https://example.com',
    notify_channels=[],
)
"""
    config = parse_monitor(source)
    assert config is not None
    assert config.name == "my_mon"
