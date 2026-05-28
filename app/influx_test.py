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


async def test_write_with_timestamp_includes_epoch():
    server, port = _start_fake_influx()
    _FakeInfluxHandler.received = []

    client = InfluxClient(url=f"http://127.0.0.1:{port}", token="t", org="o", bucket="b")
    await client.write("price", 10.0, timestamp=1748000000)
    client.close()
    server.shutdown()

    assert any("price" in line and "1748000000" in line for line in _FakeInfluxHandler.received)


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


class _FakeInfluxQueryHandler(BaseHTTPRequestHandler):
    """Fake InfluxDB server that returns a Flux CSV response for query requests."""
    csv_response: str = (
        "#datatype,string,long,dateTime:RFC3339,double\n"
        "#group,false,false,false,false\n"
        "#default,_result,,,\n"
        ",result,table,_time,_value\n"
        ",,0,2026-05-28T10:00:00Z,22.5\n"
        ",,0,2026-05-28T11:00:00Z,23.1\n"
    )

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/csv")
        body = self.csv_response.encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _start_fake_influx_query() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), _FakeInfluxQueryHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


async def test_query_returns_time_value_pairs():
    server, port = _start_fake_influx_query()
    client = InfluxClient(url=f"http://127.0.0.1:{port}", token="t", org="o", bucket="b")
    result = await client.query("temperature", hours=48)
    client.close()
    server.shutdown()

    assert len(result) == 2
    assert result[0]["t"] == "2026-05-28T10:00:00Z"
    assert result[0]["v"] == 22.5
    assert result[1]["t"] == "2026-05-28T11:00:00Z"
    assert result[1]["v"] == 23.1


async def test_query_returns_empty_on_exception():
    client = InfluxClient(url="http://127.0.0.1:1", token="t", org="o", bucket="b")
    result = await client.query("temperature", hours=48)
    client.close()
    assert result == []


async def test_query_empty_response():
    class _EmptyHandler(_FakeInfluxQueryHandler):
        csv_response = (
            "#datatype,string,long,dateTime:RFC3339,double\n"
            "#group,false,false,false,false\n"
            "#default,_result,,,\n"
            ",result,table,_time,_value\n"
        )
    server = HTTPServer(("127.0.0.1", 0), _EmptyHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    client = InfluxClient(url=f"http://127.0.0.1:{port}", token="t", org="o", bucket="b")
    result = await client.query("temperature", hours=48)
    client.close()
    server.shutdown()

    assert result == []
