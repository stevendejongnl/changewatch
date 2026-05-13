import os
import socket
import pytest

from app.influx import InfluxClient

INFLUXDB_HOST = "192.168.1.22"
INFLUXDB_PORT = 8086
INFLUXDB_TEST_BUCKET = "changewatch-test"


def _influxdb_reachable() -> bool:  # pragma: no cover
    try:
        sock = socket.create_connection((INFLUXDB_HOST, INFLUXDB_PORT), timeout=2)
        sock.close()
        return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def influx_client():  # pragma: no cover
    if not _influxdb_reachable():  # pragma: no cover
        pytest.skip(f"InfluxDB not reachable at {INFLUXDB_HOST}:{INFLUXDB_PORT} (no LAN/VPN?)")

    token = os.environ.get("INFLUXDB_TOKEN")
    org = os.environ.get("INFLUXDB_ORG")
    if not token or not org:  # pragma: no cover
        pytest.skip("INFLUXDB_TOKEN or INFLUXDB_ORG not set — skipping influx tests")

    client = InfluxClient(
        url=f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}",
        token=token,
        org=org,
        bucket=INFLUXDB_TEST_BUCKET,
    )
    yield client
    client.close()
