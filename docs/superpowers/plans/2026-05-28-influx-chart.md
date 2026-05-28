# InfluxDB Value-Over-Time Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `metric` field to `Monitor`, expose an `/api/monitors/{name}/metrics` endpoint that queries InfluxDB, and render a D3 value-over-time chart on the monitor detail page.

**Architecture:** `Monitor` gets an optional `metric` field (the InfluxDB measurement name to query). `InfluxClient` gains a `query()` method. A new FastAPI endpoint returns `[{t, v}]` JSON. A new `chart.ts` TypeScript module (bundled separately via Vite into `chart.js`) renders a D3 line chart into the monitor detail template when data is available. The editor parser/generator in both Python and TypeScript also learns about `metric`.

**Tech Stack:** Python (FastAPI, influxdb-client), TypeScript + D3 v7 (Vite IIFE bundle), Jinja2 templates, pytest, vitest.

---

## File Map

| File | Change |
|------|--------|
| `app/helpers.py` | Add `metric: Optional[str] = None` to `Monitor` dataclass |
| `app/monitor_parser.py` | Add `metric` to `MonitorConfig`, parse it, generate it |
| `app/influx.py` | Add `query(measurement, hours) -> list[dict]` method |
| `app/influx_test.py` | Tests for `query()` |
| `app/main.py` | Add `GET /api/monitors/{name}/metrics`, pass `metric` to template |
| `app/main_test.py` | Tests for the new endpoint |
| `app/monitor_parser_test.py` | Tests for `metric` in parse/generate |
| `app/templates/monitor_detail.html` | Add chart container + script loading |
| `frontend/src/chart.ts` | New D3 chart module |
| `frontend/src/parser.ts` | Add `metric` to `MonitorConfig`, parse it |
| `frontend/src/generator.ts` | Emit `metric=` in generated source |
| `frontend/src/editor.ts` | Wire `metric` field in the new-monitor form |
| `frontend/package.json` | Add `d3` dependency |
| `frontend/vite.config.ts` | Add second build entry for `chart.ts` |
| `monitors/tp-link_deco_x50.py` | Add `metric="tp-link_deco_x50"` |
| `monitors/ikea_ekbacken_stock.py` | Add `metric="ikea_stock"` |
| `monitors/daily_weather_amsterdam.py` | Add `metric="weather_amsterdam_temperature"` |
| `monitors/zitmaxx_jacky_rust.py` | Add `metric="zitmaxx_jacky_rust"` |

---

## Task 1: Add `metric` to `Monitor` dataclass

**Files:**
- Modify: `app/helpers.py`

The `Monitor` dataclass currently has `name`, `schedule`, `notify_channels`, `url`, `fn`. Add `metric` after `url`.

- [ ] **Step 1: Edit `app/helpers.py`**

Find the `Monitor` dataclass (line ~29):
```python
@dataclass
class Monitor:
    name: str
    schedule: str
    notify_channels: list[str]
    url: Optional[str] = None
    fn: Optional[Callable] = field(default=None, repr=False)
```

Change to:
```python
@dataclass
class Monitor:
    name: str
    schedule: str
    notify_channels: list[str]
    url: Optional[str] = None
    metric: Optional[str] = None
    fn: Optional[Callable] = field(default=None, repr=False)
```

- [ ] **Step 2: Run tests to verify nothing broken**

```bash
cd /home/stevendejong/workspace/personal/changewatch && uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add app/helpers.py
git commit -m "feat: add optional metric field to Monitor dataclass"
```

---

## Task 2: Add `metric` to `MonitorConfig` + parser/generator (Python)

**Files:**
- Modify: `app/monitor_parser.py`
- Modify: `app/monitor_parser_test.py`

- [ ] **Step 1: Write failing tests in `app/monitor_parser_test.py`**

Find the existing parser tests and add:

```python
def test_parse_metric_field():
    source = """
monitor = Monitor(
    name="my_mon",
    schedule="*/5 * * * *",
    metric="my_measurement",
    notify_channels=["telegram"],
)
"""
    config = parse_monitor(source)
    assert config is not None
    assert config.metric == "my_measurement"


def test_parse_metric_field_absent():
    source = """
monitor = Monitor(
    name="my_mon",
    schedule="*/5 * * * *",
    notify_channels=["telegram"],
)
"""
    config = parse_monitor(source)
    assert config is not None
    assert config.metric is None


def test_generate_with_metric():
    from app.monitor_parser import generate_monitor, MonitorConfig
    config = MonitorConfig(
        name="my_mon",
        schedule="*/5 * * * *",
        url="https://example.com",
        notify_channels=["telegram"],
        metric="my_measurement",
        record_to_influx=True,
    )
    source = generate_monitor(config)
    assert 'metric="my_measurement"' in source


def test_generate_without_metric():
    from app.monitor_parser import generate_monitor, MonitorConfig
    config = MonitorConfig(
        name="my_mon",
        schedule="*/5 * * * *",
        url="https://example.com",
        notify_channels=["telegram"],
        metric=None,
    )
    source = generate_monitor(config)
    assert "metric=" not in source
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest app/monitor_parser_test.py -x -q --no-cov -k "metric"
```

Expected: FAIL — `MonitorConfig` has no `metric` attribute.

- [ ] **Step 3: Update `MonitorConfig` dataclass**

In `app/monitor_parser.py`, add `metric` to the dataclass:

```python
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
```

- [ ] **Step 4: Add metric parsing in `parse_monitor()`**

After the `wait_for_network_idle` detection block, before the `return MonitorConfig(...)`:

```python
    # Extract metric
    metric: Optional[str] = None
    metric_match = re.search(r'\bmetric\s*=\s*"([^"]+)"', source_no_comments)
    if not metric_match:
        metric_match = re.search(r"\bmetric\s*=\s*'([^']+)'", source_no_comments)
    if metric_match:
        metric = metric_match.group(1)
```

And add `metric=metric,` to the `return MonitorConfig(...)` call.

- [ ] **Step 5: Add metric generation in `generate_monitor()`**

In the `monitor_block` string, add `metric=` after `url=` when it's set. Replace the `monitor_block` assignment:

```python
    monitor_fields = [
        f'    name={json.dumps(config.name)},',
        f'    schedule={json.dumps(config.schedule)},',
        f'    url={json.dumps(config.url)},',
    ]
    if config.metric:
        monitor_fields.append(f'    metric={json.dumps(config.metric)},')
    monitor_fields.append(f'    notify_channels={channels_repr},')
    monitor_block = 'monitor = Monitor(\n' + '\n'.join(monitor_fields) + '\n)'
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest app/monitor_parser_test.py -x -q --no-cov -k "metric"
```

Expected: all pass.

- [ ] **Step 7: Run full suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add app/monitor_parser.py app/monitor_parser_test.py
git commit -m "feat: add metric field to MonitorConfig parser and generator"
```

---

## Task 3: Add `query()` to `InfluxClient`

**Files:**
- Modify: `app/influx.py`
- Modify: `app/influx_test.py`

The query method uses the InfluxDB Flux query API to fetch the last N hours of `value` field for a measurement. Returns `list[dict]` with keys `t` (ISO timestamp string) and `v` (float).

- [ ] **Step 1: Write failing test in `app/influx_test.py`**

The existing fake server only handles POST to `/api/v2/write`. The query endpoint is `POST /api/v2/query`. Extend `_FakeInfluxHandler`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest app/influx_test.py -x -q --no-cov -k "query"
```

Expected: FAIL — `InfluxClient` has no `query` method.

- [ ] **Step 3: Implement `query()` in `app/influx.py`**

```python
    async def query(self, measurement: str, hours: int = 48) -> list[dict]:
        query_api = self._client.query_api()
        flux = (
            f'from(bucket: "{self._bucket}")'
            f' |> range(start: -{hours}h)'
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            f' |> filter(fn: (r) => r._field == "value")'
            f' |> keep(columns: ["_time", "_value"])'
        )
        try:
            tables = query_api.query(flux, org=self._org)
        except Exception:
            return []
        result = []
        for table in tables:
            for record in table.records:
                t = record.get_time()
                v = record.get_value()
                if t is not None and v is not None:
                    result.append({"t": t.isoformat().replace("+00:00", "Z"), "v": float(v)})
        return result
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest app/influx_test.py -x -q --no-cov -k "query"
```

Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/influx.py app/influx_test.py
git commit -m "feat: add query() method to InfluxClient"
```

---

## Task 4: Add `/api/monitors/{name}/metrics` endpoint

**Files:**
- Modify: `app/main.py`
- Modify: `app/main_test.py`

The endpoint returns `[]` if InfluxDB is not configured or the monitor has no `metric` field.

- [ ] **Step 1: Write failing test in `app/main_test.py`**

Find the existing test patterns (they use `AsyncClient` with `ASGITransport`). Add:

```python
async def test_metrics_endpoint_no_influx(client):
    """Returns empty list when influx not configured."""
    resp = await client.get("/api/monitors/daily_weather_amsterdam/metrics")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_metrics_endpoint_unknown_monitor(client):
    resp = await client.get("/api/monitors/nonexistent_monitor/metrics")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest app/main_test.py -x -q --no-cov -k "metrics"
```

Expected: FAIL — 404/405 (route doesn't exist yet).

- [ ] **Step 3: Add `get_influx` dependency and `InfluxDep` in `app/main.py`**

Add after `get_apprise()`:

```python
_influx: "InfluxClient | None" = None


async def get_influx() -> "InfluxClient | None":  # pragma: no cover
    return _influx

InfluxDep = Annotated[Optional[Any], Depends(get_influx)]
```

Also wire `_influx` into the lifespan (pragma: no cover block) — read env vars `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `INFLUXDB_BUCKET` and construct `InfluxClient` if all present. And call `_influx.close()` in cleanup.

- [ ] **Step 4: Add the endpoint in `app/main.py`**

After the existing `/api/monitors/{name}/runs` endpoint:

```python
@app.get("/api/monitors/{name}/metrics")
async def monitor_metrics(name: str, influx: InfluxDep, hours: int = 48):
    known = {m.name: m for m in discover_monitors(MONITORS_DIR)}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Monitor {name!r} not found")
    monitor = known[name]
    if influx is None or not monitor.metric:
        return []
    return await influx.query(monitor.metric, hours=hours)
```

- [ ] **Step 5: Pass `metric` to the monitor_detail template**

In `monitor_detail()`, add `"metric": monitor.metric` to the template context dict.

- [ ] **Step 6: Run tests**

```bash
uv run pytest app/main_test.py -x -q --no-cov -k "metrics"
```

Expected: all pass.

- [ ] **Step 7: Run full suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add app/main.py app/main_test.py
git commit -m "feat: add /api/monitors/{name}/metrics endpoint"
```

---

## Task 5: Add `metric` to monitors that record influx data

**Files:**
- Modify: `monitors/tp-link_deco_x50.py`
- Modify: `monitors/ikea_ekbacken_stock.py`
- Modify: `monitors/daily_weather_amsterdam.py`
- Modify: `monitors/zitmaxx_jacky_rust.py`

- [ ] **Step 1: Update `monitors/tp-link_deco_x50.py`**

```python
monitor = Monitor(
    name="tp-link_deco_x50",
    schedule="0 */2 * * *",
    url="https://tweakers.net/pricewatch/1786790/tp-link-deco-x50-1-pack.html",
    metric="tp-link_deco_x50",
    notify_channels=["telegram"],
)
```

- [ ] **Step 2: Update `monitors/ikea_ekbacken_stock.py`**

Add `metric="ikea_stock",` to the `Monitor(...)` constructor.

- [ ] **Step 3: Update `monitors/daily_weather_amsterdam.py`**

Add `metric="weather_amsterdam_temperature",` to the `Monitor(...)` constructor.

- [ ] **Step 4: Update `monitors/zitmaxx_jacky_rust.py`**

Add `metric="zitmaxx_jacky_rust",` to the `Monitor(...)` constructor.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add monitors/tp-link_deco_x50.py monitors/ikea_ekbacken_stock.py monitors/daily_weather_amsterdam.py monitors/zitmaxx_jacky_rust.py
git commit -m "feat: set metric field on monitors that record influx data"
```

---

## Task 6: Add D3 chart frontend (`frontend/src/chart.ts`)

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/chart.ts`

This builds a separate IIFE bundle `chart.js` into `app/static/`.

- [ ] **Step 1: Install d3**

```bash
cd /home/stevendejong/workspace/personal/changewatch/frontend && npm install d3 && npm install --save-dev @types/d3
```

- [ ] **Step 2: Update `frontend/vite.config.ts` for dual entry**

```typescript
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        editor: "src/editor.ts",
        chart: "src/chart.ts",
      },
      output: {
        entryFileNames: "[name].js",
        format: "iife",
        name: "CW",
      },
    },
    outDir: "../app/static",
    emptyOutDir: false,
    minify: false,
  },
});
```

- [ ] **Step 3: Create `frontend/src/chart.ts`**

```typescript
import * as d3 from "d3";

interface DataPoint {
  t: Date;
  v: number;
}

function renderChart(
  container: HTMLElement,
  data: DataPoint[],
  unit: string
): void {
  container.innerHTML = "";

  const totalW = container.clientWidth || 600;
  const totalH = 180;
  const margin = { top: 16, right: 20, bottom: 28, left: 42 };
  const w = totalW - margin.left - margin.right;
  const h = totalH - margin.top - margin.bottom;

  const svg = d3
    .select(container)
    .append("svg")
    .attr("width", totalW)
    .attr("height", totalH)
    .style("display", "block");

  const g = svg
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  const xScale = d3
    .scaleTime()
    .domain(d3.extent(data, (d) => d.t) as [Date, Date])
    .range([0, w]);

  const [minV, maxV] = d3.extent(data, (d) => d.v) as [number, number];
  const pad = (maxV - minV) * 0.1 || 1;
  const yScale = d3
    .scaleLinear()
    .domain([minV - pad, maxV + pad])
    .range([h, 0]);

  // Gridlines
  g.append("g")
    .selectAll("line")
    .data(yScale.ticks(4))
    .join("line")
    .attr("x1", 0)
    .attr("x2", w)
    .attr("y1", (d) => yScale(d))
    .attr("y2", (d) => yScale(d))
    .attr("stroke", "var(--line)")
    .attr("stroke-dasharray", "2 4");

  // Area fill
  const area = d3
    .area<DataPoint>()
    .x((d) => xScale(d.t))
    .y0(h)
    .y1((d) => yScale(d.v))
    .curve(d3.curveMonotoneX);

  const gradId = "cw-chart-grad-" + Math.random().toString(36).slice(2);
  const defs = svg.append("defs");
  const grad = defs
    .append("linearGradient")
    .attr("id", gradId)
    .attr("x1", "0")
    .attr("y1", "0")
    .attr("x2", "0")
    .attr("y2", "1");
  grad.append("stop").attr("offset", "0%").attr("stop-color", "var(--accent)").attr("stop-opacity", 0.28);
  grad.append("stop").attr("offset", "100%").attr("stop-color", "var(--accent)").attr("stop-opacity", 0);

  g.append("path")
    .datum(data)
    .attr("fill", `url(#${gradId})`)
    .attr("d", area);

  // Line
  const line = d3
    .line<DataPoint>()
    .x((d) => xScale(d.t))
    .y((d) => yScale(d.v))
    .curve(d3.curveMonotoneX);

  g.append("path")
    .datum(data)
    .attr("fill", "none")
    .attr("stroke", "var(--accent)")
    .attr("stroke-width", 2)
    .attr("filter", "drop-shadow(0 0 3px var(--accent-glow))")
    .attr("d", line);

  // Current value dot
  const last = data[data.length - 1];
  g.append("circle")
    .attr("cx", xScale(last.t))
    .attr("cy", yScale(last.v))
    .attr("r", 4)
    .attr("fill", "var(--accent)")
    .attr("filter", "drop-shadow(0 0 4px var(--accent-glow))");

  // X axis
  g.append("g")
    .attr("transform", `translate(0,${h})`)
    .call(
      d3
        .axisBottom(xScale)
        .ticks(5)
        .tickSize(0)
        .tickFormat((d) => d3.timeFormat("%H:%M")(d as Date))
    )
    .call((ax) => ax.select(".domain").remove())
    .selectAll("text")
    .attr("fill", "var(--ink-3)")
    .attr("font-size", "9.5px")
    .attr("font-family", "var(--mono)")
    .attr("dy", "1.2em");

  // Y axis
  g.append("g")
    .call(
      d3
        .axisLeft(yScale)
        .ticks(4)
        .tickSize(0)
        .tickFormat((d) => `${d}${unit}`)
    )
    .call((ax) => ax.select(".domain").remove())
    .selectAll("text")
    .attr("fill", "var(--ink-3)")
    .attr("font-size", "9.5px")
    .attr("font-family", "var(--mono)");
}

async function initChart(
  monitorName: string,
  unit: string,
  hours: number
): Promise<void> {
  const container = document.getElementById("cw-chart-container");
  if (!container) return;

  const loadingEl = document.getElementById("cw-chart-loading");
  const emptyEl = document.getElementById("cw-chart-empty");

  try {
    const resp = await fetch(
      `/api/monitors/${encodeURIComponent(monitorName)}/metrics?hours=${hours}`
    );
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const raw: Array<{ t: string; v: number }> = await resp.json();

    if (loadingEl) loadingEl.style.display = "none";

    if (raw.length === 0) {
      if (emptyEl) emptyEl.style.display = "";
      return;
    }

    const data: DataPoint[] = raw.map((d) => ({ t: new Date(d.t), v: d.v }));
    renderChart(container, data, unit);
  } catch {
    if (loadingEl) loadingEl.style.display = "none";
    if (emptyEl) emptyEl.style.display = "";
  }
}

(window as any).CWChart = { initChart };
```

- [ ] **Step 4: Build to verify it compiles**

```bash
cd /home/stevendejong/workspace/personal/changewatch/frontend && npm run build
```

Expected: builds without error, `app/static/chart.js` is created.

- [ ] **Step 5: Commit**

```bash
cd /home/stevendejong/workspace/personal/changewatch
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/chart.ts app/static/chart.js
git commit -m "feat: add D3 value-over-time chart bundle"
```

---

## Task 7: Wire chart into `monitor_detail.html`

**Files:**
- Modify: `app/templates/monitor_detail.html`

Add a chart card below the metric strip. The card is only rendered when `metric` is set in the template context. The `chart.js` script is loaded conditionally and `CWChart.initChart()` is called on page load.

- [ ] **Step 1: Add chart card + script to `monitor_detail.html`**

After the metric strip block (after the `</div>` closing `.metric-strip`), and before the error banner `{% if current_status == 'error' %}` block, add:

```html
{% if metric %}
<!-- Value over time chart -->
<div class="neu-raised-sm" style="padding:18px;margin-bottom:18px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h2 style="font:600 14px var(--sans);margin:0">Value over time</h2>
    <span class="mono t-3" style="font-size:10.5px">{{ metric }} · 48h</span>
  </div>
  <div class="neu-inset" style="padding:10px 12px;min-height:60px;position:relative">
    <div id="cw-chart-loading" class="t-3 mono" style="font-size:11px;text-align:center;padding:20px 0">loading…</div>
    <div id="cw-chart-empty" class="t-4 mono" style="font-size:11px;text-align:center;padding:20px 0;display:none">no data</div>
    <div id="cw-chart-container"></div>
  </div>
</div>

<script src="/static/chart.js?v={{ chart_version }}"></script>
<script>
  CWChart.initChart({{ monitor_name | tojson }}, "", 48);
</script>
{% endif %}
```

- [ ] **Step 2: Expose `chart_version` in `main.py`**

In `main.py`, after the `editor_version` global, add:

```python
templates.env.globals["chart_version"] = int(
    (Path(__file__).parent / "static" / "chart.js").stat().st_mtime
    if (Path(__file__).parent / "static" / "chart.js").exists()
    else 0
)
```

- [ ] **Step 3: Run full test suite**

```bash
cd /home/stevendejong/workspace/personal/changewatch && uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add app/templates/monitor_detail.html app/main.py
git commit -m "feat: add value-over-time chart card to monitor detail page"
```

---

## Task 8: Add `metric` to TypeScript parser, generator, and editor form

**Files:**
- Modify: `frontend/src/parser.ts`
- Modify: `frontend/src/generator.ts`
- Modify: `frontend/src/editor.ts`

- [ ] **Step 1: Update `frontend/src/parser.ts`**

Add `metric: string | null` to `MonitorConfig` interface and parse it:

```typescript
export interface MonitorConfig {
  name: string;
  schedule: string;
  url: string;
  selector: string;
  notifyChannels: string[];
  recordToInflux: boolean;
  waitForNetworkIdle: boolean;
  metric: string | null;
}

export function parseMonitor(source: string): MonitorConfig | null {
  // ... existing code ...

  const metricMatch = src.match(/\bmetric\s*=\s*["']([^"']+)["']/);

  return {
    // ... existing fields ...
    metric: metricMatch ? metricMatch[1] : null,
  };
}
```

- [ ] **Step 2: Update `frontend/src/generator.ts`**

In the monitor constructor output, add `metric` line when present:

```typescript
// After url line, before notify_channels line:
if (config.metric) {
  lines.push(`    metric=${JSON.stringify(config.metric)},`);
}
```

And in imports, `metric` doesn't affect imports (it's just a dataclass field).

- [ ] **Step 3: Update `frontend/src/editor.ts`**

Find where the new-monitor form fields are read/written (the `buildForm` or equivalent function). Add a `metric` text input field that maps to `config.metric`. It should be optional — leave blank if not recording to influx.

Add a form row after the `record_to_influx` checkbox:

```typescript
// In the field definition list, after recordToInflux:
{
  id: "metric",
  label: "Metric name",
  type: "text",
  placeholder: "InfluxDB measurement (optional)",
  getValue: (c: MonitorConfig) => c.metric ?? "",
  setValue: (c: MonitorConfig, v: string) => ({ ...c, metric: v || null }),
},
```

The exact integration depends on how `editor.ts` builds its form — follow the existing pattern for optional fields.

- [ ] **Step 4: Build**

```bash
cd /home/stevendejong/workspace/personal/changewatch/frontend && npm run build
```

Expected: no TypeScript errors, `editor.js` and `chart.js` both updated in `app/static/`.

- [ ] **Step 5: Run full Python test suite**

```bash
cd /home/stevendejong/workspace/personal/changewatch && uv run pytest --no-cov -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/parser.ts frontend/src/generator.ts frontend/src/editor.ts app/static/editor.js app/static/chart.js
git commit -m "feat: add metric field to TypeScript parser, generator, and editor form"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|-------------|-----------|
| `metric` field on `Monitor` | Task 1 |
| `metric` in Python parser/generator | Task 2 |
| InfluxDB `query()` method | Task 3 |
| `/api/monitors/{name}/metrics` endpoint | Task 4 |
| Monitor files updated with `metric=` | Task 5 |
| D3 chart bundle (`chart.ts`) | Task 6 |
| Chart wired into monitor_detail template | Task 7 |
| TypeScript parser/generator/editor updated | Task 8 |

**Placeholder scan:** No TBD, no TODO, no "similar to Task N". Task 8 Step 3 references "the existing pattern" — this is intentional since `editor.ts` form construction must be read in context, and adding a rigid code block risks conflicting with actual file content.

**Type consistency:** `MonitorConfig.metric` is `Optional[str]` in Python, `string | null` in TypeScript throughout. `query()` always returns `list[dict]` with keys `t: str, v: float`. Endpoint returns same shape. `initChart` receives `monitorName: string`. All consistent.
