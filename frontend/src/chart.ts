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

function renderSparkline(container: HTMLElement, data: DataPoint[]): void {
  container.innerHTML = "";
  const totalW = container.clientWidth || 200;
  const totalH = 48;

  const svg = d3
    .select(container)
    .append("svg")
    .attr("width", "100%")
    .attr("height", totalH)
    .attr("viewBox", `0 0 ${totalW} ${totalH}`)
    .attr("preserveAspectRatio", "none")
    .style("display", "block");

  const xScale = d3
    .scaleTime()
    .domain(d3.extent(data, (d) => d.t) as [Date, Date])
    .range([0, totalW]);

  const [minV, maxV] = d3.extent(data, (d) => d.v) as [number, number];
  const pad = (maxV - minV) * 0.1 || 1;
  const yScale = d3
    .scaleLinear()
    .domain([minV - pad, maxV + pad])
    .range([totalH, 0]);

  const gradId = "cw-spark-grad-" + Math.random().toString(36).slice(2);
  const defs = svg.append("defs");
  const grad = defs
    .append("linearGradient")
    .attr("id", gradId)
    .attr("x1", "0").attr("y1", "0").attr("x2", "0").attr("y2", "1");
  grad.append("stop").attr("offset", "0%").attr("stop-color", "var(--accent)").attr("stop-opacity", 0.3);
  grad.append("stop").attr("offset", "100%").attr("stop-color", "var(--accent)").attr("stop-opacity", 0);

  const area = d3.area<DataPoint>()
    .x((d) => xScale(d.t))
    .y0(totalH)
    .y1((d) => yScale(d.v))
    .curve(d3.curveMonotoneX);

  svg.append("path").datum(data).attr("fill", `url(#${gradId})`).attr("d", area);

  const line = d3.line<DataPoint>()
    .x((d) => xScale(d.t))
    .y((d) => yScale(d.v))
    .curve(d3.curveMonotoneX);

  svg.append("path")
    .datum(data)
    .attr("fill", "none")
    .attr("stroke", "var(--accent)")
    .attr("stroke-width", 1.5)
    .attr("filter", "drop-shadow(0 0 2px var(--accent-glow))")
    .attr("d", line);

  const last = data[data.length - 1];
  svg.append("circle")
    .attr("cx", xScale(last.t))
    .attr("cy", yScale(last.v))
    .attr("r", 3)
    .attr("fill", "var(--accent)")
    .attr("filter", "drop-shadow(0 0 3px var(--accent-glow))");
}

async function initSparkline(monitorName: string, containerId: string): Promise<void> {
  const container = document.getElementById(containerId);
  if (!container) return;
  try {
    const resp = await fetch(`/api/monitors/${encodeURIComponent(monitorName)}/metrics?hours=48`);
    if (!resp.ok) return;
    const raw: Array<{ t: string; v: number }> = await resp.json();
    if (raw.length < 2) return;
    const data: DataPoint[] = raw.map((d) => ({ t: new Date(d.t), v: d.v }));
    renderSparkline(container, data);
  } catch {
    // silently skip — sparkline is optional decoration
  }
}

(window as any).CWChart = { initChart, initSparkline };
