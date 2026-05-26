import { describe, it, expect } from "vitest";
import { tokenize, renderHighlighted } from "./tokenizer";
import { parseMonitor, type MonitorConfig } from "./parser";
import { generateMonitor } from "./generator";

describe("tokenize", () => {
  it("identifies keywords", () => {
    const tokens = tokenize("async def");
    expect(tokens.some(t => t.type === "keyword" && t.value === "async")).toBe(true);
    expect(tokens.some(t => t.type === "keyword" && t.value === "def")).toBe(true);
  });

  it("identifies double-quoted strings", () => {
    const tokens = tokenize('"hello"');
    expect(tokens.some(t => t.type === "string" && t.value === '"hello"')).toBe(true);
  });

  it("identifies single-quoted strings", () => {
    const tokens = tokenize("'world'");
    expect(tokens.some(t => t.type === "string" && t.value === "'world'")).toBe(true);
  });

  it("identifies comments", () => {
    const tokens = tokenize("# a comment");
    expect(tokens.some(t => t.type === "comment")).toBe(true);
  });

  it("identifies decorators", () => {
    const tokens = tokenize("@monitor.check");
    expect(tokens.some(t => t.type === "decorator")).toBe(true);
  });

  it("identifies numbers", () => {
    const tokens = tokenize("42");
    expect(tokens.some(t => t.type === "number" && t.value === "42")).toBe(true);
  });

  it("identifies builtins", () => {
    const tokens = tokenize("print");
    expect(tokens.some(t => t.type === "builtin" && t.value === "print")).toBe(true);
  });

  it("identifies triple-quoted strings", () => {
    const tokens = tokenize('"""hello world"""');
    expect(tokens.some(t => t.type === "string")).toBe(true);
  });

  it("identifies plain identifiers as text", () => {
    const tokens = tokenize("my_variable");
    expect(tokens.some(t => t.type === "text" && t.value === "my_variable")).toBe(true);
  });

  it("handles f-strings (f prefix followed by quoted string)", () => {
    const tokens = tokenize('f"hello"');
    // The 'f' is scanned as identifier first, then '"hello"' as a string
    expect(tokens.some(t => t.type === "text" && t.value === "f")).toBe(true);
    expect(tokens.some(t => t.type === "string" && t.value === '"hello"')).toBe(true);
  });

  it("handles r-strings (r prefix followed by quoted string)", () => {
    const tokens = tokenize('r"hello"');
    expect(tokens.some(t => t.type === "text" && t.value === "r")).toBe(true);
    expect(tokens.some(t => t.type === "string" && t.value === '"hello"')).toBe(true);
  });

  it("handles fr-strings (fr prefix followed by quoted string)", () => {
    const tokens = tokenize('fr"hello"');
    expect(tokens.some(t => t.type === "text" && t.value === "fr")).toBe(true);
    expect(tokens.some(t => t.type === "string" && t.value === '"hello"')).toBe(true);
  });
});

describe("renderHighlighted", () => {
  it("wraps keywords in t-acc spans", () => {
    const html = renderHighlighted("async def");
    expect(html).toContain('<span class="t-acc">async</span>');
    expect(html).toContain('<span class="t-acc">def</span>');
  });

  it("wraps strings in t-ok spans", () => {
    const html = renderHighlighted('"test"');
    expect(html).toContain('<span class="t-ok">');
  });

  it("wraps comments in t-3 spans", () => {
    const html = renderHighlighted("# comment");
    expect(html).toContain('<span class="t-3">');
  });

  it("escapes HTML special characters", () => {
    const html = renderHighlighted("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });

  it("wraps plain text without span (or as text span)", () => {
    const html = renderHighlighted("my_var");
    // plain text should appear in the output
    expect(html).toContain("my_var");
  });
});

const SAMPLE_SOURCE = `
from app.helpers import Monitor, extract_text, get_last_value, set_value, notify

monitor = Monitor(
    name="price_check",
    schedule="*/10 * * * *",
    url="https://example.com/product",
    notify_channels=["telegram", "discord"],
)

@monitor.check
async def check(page, ctx):
    await page.goto("https://example.com/product")
    value = await extract_text(page, ".price-tag")
    prev = await get_last_value(ctx.db, "price_check")
    await set_value(ctx.db, "price_check", value)
`;

describe("parseMonitor", () => {
  it("extracts name", () => {
    expect(parseMonitor(SAMPLE_SOURCE)?.name).toBe("price_check");
  });

  it("extracts schedule", () => {
    expect(parseMonitor(SAMPLE_SOURCE)?.schedule).toBe("*/10 * * * *");
  });

  it("extracts url", () => {
    expect(parseMonitor(SAMPLE_SOURCE)?.url).toBe("https://example.com/product");
  });

  it("extracts selector", () => {
    expect(parseMonitor(SAMPLE_SOURCE)?.selector).toBe(".price-tag");
  });

  it("extracts notify channels", () => {
    expect(parseMonitor(SAMPLE_SOURCE)?.notifyChannels).toEqual(["telegram", "discord"]);
  });

  it("returns null for unparseable source", () => {
    expect(parseMonitor("x = 1")).toBeNull();
  });

  it("detects recordToInflux", () => {
    const src = SAMPLE_SOURCE + "\n    await record_metric(ctx.influx, 'p', value)\n";
    expect(parseMonitor(src)?.recordToInflux).toBe(true);
  });

  it("detects waitForNetworkIdle", () => {
    const src = SAMPLE_SOURCE + '\n    await page.wait_for_load_state("networkidle")\n';
    expect(parseMonitor(src)?.waitForNetworkIdle).toBe(true);
  });

  it("defaults recordToInflux to false", () => {
    expect(parseMonitor(SAMPLE_SOURCE)?.recordToInflux).toBe(false);
  });

  it("defaults waitForNetworkIdle to false", () => {
    expect(parseMonitor(SAMPLE_SOURCE)?.waitForNetworkIdle).toBe(false);
  });
});

describe("generateMonitor", () => {
  it("roundtrip: parse(generate(config)) matches config", () => {
    const config: MonitorConfig = {
      name: "rt_test",
      schedule: "0 * * * *",
      url: "https://rt.example.com",
      selector: ".value",
      notifyChannels: ["slack"],
      recordToInflux: false,
      waitForNetworkIdle: false,
    };
    const generated = generateMonitor(config);
    const parsed = parseMonitor(generated);
    expect(parsed?.name).toBe(config.name);
    expect(parsed?.schedule).toBe(config.schedule);
    expect(parsed?.url).toBe(config.url);
    expect(parsed?.selector).toBe(config.selector);
    expect(parsed?.notifyChannels).toEqual(config.notifyChannels);
  });

  it("includes waitForNetworkIdle when flag is true", () => {
    const config: MonitorConfig = {
      name: "n", schedule: "* * * * *", url: "u", selector: "", notifyChannels: [],
      recordToInflux: false, waitForNetworkIdle: true,
    };
    expect(generateMonitor(config)).toContain("wait_for_load_state");
  });

  it("includes record_metric when recordToInflux is true", () => {
    const config: MonitorConfig = {
      name: "n", schedule: "* * * * *", url: "u", selector: "", notifyChannels: [],
      recordToInflux: true, waitForNetworkIdle: false,
    };
    expect(generateMonitor(config)).toContain("record_metric");
  });
});
