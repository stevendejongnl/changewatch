import { describe, it, expect } from "vitest";
import { tokenize, renderHighlighted } from "./tokenizer";

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
