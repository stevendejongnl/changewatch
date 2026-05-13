import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.influx import InfluxClient

# influx_client fixture (real InfluxDB integration) is provided by conftest.py
# and skipped automatically when InfluxDB is unreachable or credentials absent.
# The unit tests below use a local fake server and always run.


class _FakeInfluxHandler(BaseHTTPRequestHandler):
    received: list[str] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        _FakeInfluxHandler.received.append(body)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def _start_fake_influx() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), _FakeInfluxHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


async def test_write_single_tag_sends_line_protocol():
    server, port = _start_fake_influx()
    _FakeInfluxHandler.received = []

    client = InfluxClient(url=f"http://127.0.0.1:{port}", token="t", org="o", bucket="b")
    await client.write("price", 42.5, monitor="test_mon")
    client.close()
    server.shutdown()

    assert any("price" in line and "value=42.5" in line for line in _FakeInfluxHandler.received)


async def test_write_no_tags_sends_bare_measurement():
    server, port = _start_fake_influx()
    _FakeInfluxHandler.received = []

    client = InfluxClient(url=f"http://127.0.0.1:{port}", token="t", org="o", bucket="b")
    await client.write("temperature", 22)
    client.close()
    server.shutdown()

    assert any("temperature" in line and "value=22" in line for line in _FakeInfluxHandler.received)


async def test_write_multiple_tags():
    server, port = _start_fake_influx()
    _FakeInfluxHandler.received = []

    client = InfluxClient(url=f"http://127.0.0.1:{port}", token="t", org="o", bucket="b")
    await client.write("stock", 1, monitor="mon", source="web")
    client.close()
    server.shutdown()

    assert any("stock" in line for line in _FakeInfluxHandler.received)


async def test_close_does_not_raise():
    server, port = _start_fake_influx()
    client = InfluxClient(url=f"http://127.0.0.1:{port}", token="t", org="o", bucket="b")
    client.close()
    server.shutdown()
