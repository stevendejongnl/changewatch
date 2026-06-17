import { renderHighlighted } from "./tokenizer";
import { parseMonitor, type MonitorConfig } from "./parser";
import { generateMonitor } from "./generator";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[_-]+|[_-]+$/g, "");
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─── Textarea overlay editor ──────────────────────────────────────
interface EditorAPI {
  getValue(): string;
  setValue(source: string): void;
}

function buildEditor(container: HTMLElement, initialSource: string): EditorAPI {
  const sharedStyle = [
    "font-family: var(--font-mono, 'JetBrains Mono', monospace)",
    "font-size: 13px",
    "line-height: 1.6",
    "padding: 12px 16px",
    "letter-spacing: 0",
    "tab-size: 4",
    "white-space: pre",
    "word-wrap: normal",
    "overflow-wrap: normal",
    "margin: 0",
    "border: none",
    "outline: none",
    "box-sizing: border-box",
  ].join(";");

  // Wrapper: flex row (line-numbers | editor area)
  const wrapper = document.createElement("div");
  wrapper.style.cssText = [
    "display: flex",
    "height: 100%",
    "width: 100%",
    "overflow: auto",
    "background: var(--surface, #1e1e2e)",
    "border-radius: 4px",
  ].join(";");

  // Line numbers column
  const lineNumbers = document.createElement("div");
  lineNumbers.id = "line-numbers";
  lineNumbers.style.cssText = [
    "font-family: var(--font-mono, 'JetBrains Mono', monospace)",
    "font-size: 13px",
    "line-height: 1.6",
    "padding: 12px 8px 12px 16px",
    "letter-spacing: 0",
    "tab-size: 4",
    "white-space: pre",
    "color: var(--ink3, #6c7086)",
    "text-align: right",
    "user-select: none",
    "min-width: 40px",
    "flex-shrink: 0",
    "border-right: 1px solid var(--border, #313244)",
    "margin-right: 0",
  ].join(";");

  // Right area: relative container for stacked pre + textarea
  const rightArea = document.createElement("div");
  rightArea.style.cssText = [
    "position: relative",
    "flex: 1",
    "min-width: 0",
  ].join(";");

  // Highlight layer (pre) — renderHighlighted() escapes all token values via escapeHtml
  const pre = document.createElement("pre");
  pre.className = "highlight-layer";
  pre.setAttribute("aria-hidden", "true");
  pre.style.cssText = [
    sharedStyle,
    "pointer-events: none",
    "position: absolute",
    "top: 0",
    "left: 0",
    "right: 0",
    "bottom: 0",
    "width: 100%",
    "height: 100%",
    "overflow: hidden",
    "color: var(--ink, #cdd6f4)",
    "background: transparent",
    "z-index: 1",
  ].join(";");

  // Input layer (textarea)
  const textarea = document.createElement("textarea");
  textarea.className = "input-layer";
  textarea.spellcheck = false;
  textarea.style.cssText = [
    sharedStyle,
    "position: absolute",
    "top: 0",
    "left: 0",
    "right: 0",
    "bottom: 0",
    "width: 100%",
    "height: 100%",
    "background: transparent",
    "color: transparent",
    "caret-color: var(--ink, #cdd6f4)",
    "resize: none",
    "overflow: hidden",
    "z-index: 2",
  ].join(";");

  function countLines(text: string): number {
    let count = 1;
    for (let i = 0; i < text.length; i++) {
      if (text[i] === "\n") count++;
    }
    return count;
  }

  function syncLineNumbers(text: string): void {
    const n = countLines(text);
    const nums: string[] = [];
    for (let i = 1; i <= n; i++) nums.push(String(i));
    lineNumbers.textContent = nums.join("\n");
  }

  function syncHighlight(text: string): void {
    // renderHighlighted escapes all token values via escapeHtml — safe to set as innerHTML
    // Append a trailing space so the last newline renders correctly in the pre layer
    pre.innerHTML = renderHighlighted(text) + " ";
  }

  function sync(): void {
    const text = textarea.value;
    syncLineNumbers(text);
    syncHighlight(text);
    // Keep rightArea height in sync so the wrapper scrolls correctly
    const lineCount = countLines(text);
    const lineHeight = 13 * 1.6; // font-size * line-height
    const minHeight = lineCount * lineHeight + 24; // 24 = top+bottom padding
    rightArea.style.minHeight = minHeight + "px";
    pre.style.minHeight = minHeight + "px";
    textarea.style.minHeight = minHeight + "px";
  }

  // Tab key: insert 4 spaces instead of tabbing out
  textarea.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const value = textarea.value;
      textarea.value = value.slice(0, start) + "    " + value.slice(end);
      textarea.selectionStart = start + 4;
      textarea.selectionEnd = start + 4;
      sync();
    }
  });

  textarea.addEventListener("input", () => {
    sync();
  });

  // Assemble DOM
  rightArea.appendChild(pre);
  rightArea.appendChild(textarea);
  wrapper.appendChild(lineNumbers);
  wrapper.appendChild(rightArea);
  container.appendChild(wrapper);

  // Set initial value
  textarea.value = initialSource;
  sync();

  return {
    getValue(): string {
      return textarea.value;
    },
    setValue(source: string): void {
      textarea.value = source;
      sync();
    },
  };
}

// ─── Git status strip ─────────────────────────────────────────────
type StatusState = "idle" | "saving" | "ok" | "conflict" | "error";

function setGitStatus(el: HTMLElement, state: StatusState, msg = ""): void {
  switch (state) {
    case "idle":
      el.textContent = "";
      el.style.color = "inherit";
      break;
    case "saving":
      el.textContent = "Saving…";
      el.style.color = "inherit";
      break;
    case "ok":
      el.textContent = "✓ Saved";
      el.style.color = "var(--ok, #a6e3a1)";
      break;
    case "conflict":
      el.textContent = "⚠ Conflict";
      el.style.color = "var(--err, #f38ba8)";
      break;
    case "error":
      el.textContent = `✗ Error: ${msg}`;
      el.style.color = "var(--err, #f38ba8)";
      break;
  }
}

// ─── Main init ────────────────────────────────────────────────────
function init(): void {
  const container = document.getElementById("raw-editor-container") as HTMLElement;
  if (!container) return;

  const initialSource = container.dataset.source ?? "";
  const customFile = container.dataset.customFile === "true";
  const monitorName = document.body.dataset.monitorName ?? "";

  // Custom files: build textarea overlay in the right panel container
  // Standard files: container is hidden, only used to carry initialSource
  const editor: EditorAPI | null = customFile ? buildEditor(container, initialSource) : null;

  // DOM refs
  const gitStatusEl = document.getElementById("git-status") as HTMLElement;
  const codePreview = document.getElementById("code-preview") as HTMLElement | null;
  const dryRunConsole = document.getElementById("dry-run-console") as HTMLElement;
  const conflictPanel = document.getElementById("conflict-panel") as HTMLElement;
  const conflictDiff = document.getElementById("conflict-diff") as HTMLElement;
  const btnSave = document.getElementById("btn-save") as HTMLButtonElement;
  const btnDryRun = document.getElementById("btn-dry-run") as HTMLButtonElement;
  const btnForce = document.getElementById("btn-force") as HTMLButtonElement;
  const btnDiscard = document.getElementById("btn-discard") as HTMLButtonElement;

  // Form field refs (null-safe for custom mode where form is hidden)
  const fieldName = document.getElementById("field-name") as HTMLInputElement | null;
  const fieldUrl = document.getElementById("field-url") as HTMLInputElement | null;
  const fieldSchedule = document.getElementById("field-schedule") as HTMLInputElement | null;
  const fieldSelector = document.getElementById("field-selector") as HTMLInputElement | null;
  const fieldMetric = document.getElementById("field-metric") as HTMLInputElement | null;
  const fieldInflux = document.getElementById("field-influx") as HTMLInputElement | null;
  const fieldNetworkIdle = document.getElementById("field-networkidle") as HTMLInputElement | null;

  // Cron builder
  const cronPartEls = ['cron-min', 'cron-hour', 'cron-dom', 'cron-mon', 'cron-dow']
    .map(id => document.getElementById(id) as HTMLInputElement | null);
  const cronDescEl = document.getElementById('cron-desc');

  function describeCron(expr: string): string {
    const p = expr.trim().split(/\s+/);
    if (p.length !== 5) return '';
    const [min, hr, dom, mon, dow] = p;
    if (p.every(x => x === '*')) return 'every minute';
    if (/^\*\/\d+$/.test(min) && hr === '*' && dom === '*' && mon === '*' && dow === '*') {
      const n = min.slice(2);
      return n === '1' ? 'every minute' : `every ${n} minutes`;
    }
    if (min === '0' && hr === '*' && dom === '*' && mon === '*' && dow === '*') return 'every hour';
    if (min === '0' && /^\*\/\d+$/.test(hr) && dom === '*' && mon === '*' && dow === '*') return `every ${hr.slice(2)} hours`;
    if (min === '0' && hr === '0' && dom === '*' && mon === '*' && dow === '*') return 'every day at midnight';
    if (min === '0' && hr === '12' && dom === '*' && mon === '*' && dow === '*') return 'every day at noon';
    if (/^\d+$/.test(min) && /^\d+$/.test(hr) && dom === '*' && mon === '*' && dow === '*') {
      const h = parseInt(hr).toString().padStart(2, '0');
      const m = parseInt(min).toString().padStart(2, '0');
      return `every day at ${h}:${m}`;
    }
    return '';
  }

  function syncBuilderFromExpr(expr: string): void {
    const p = expr.trim().split(/\s+/);
    if (p.length !== 5) return;
    cronPartEls.forEach((el, i) => { if (el) el.value = p[i] === '*' ? '' : p[i]; });
    if (cronDescEl) cronDescEl.textContent = describeCron(expr);
  }

  function getSource(): string {
    if (customFile) return editor!.getValue();
    const config = readForm();
    config.name = slugify(config.name);
    return generateMonitor(config);
  }

  function getEffectiveName(): string {
    if (monitorName) return monitorName;
    if (!customFile) return slugify(fieldName?.value.trim() ?? "");
    const config = parseMonitor(getSource());
    return config?.name ?? "";
  }

  function readForm(): MonitorConfig {
    const channels = [...document.querySelectorAll<HTMLInputElement>(".channel-checkbox:checked")]
      .map(cb => cb.value);
    return {
      name: fieldName?.value ?? "",
      schedule: fieldSchedule?.value ?? "",
      url: fieldUrl?.value ?? "",
      selector: fieldSelector?.value ?? "",
      notifyChannels: channels,
      metric: fieldMetric?.value.trim() || null,
      recordToInflux: fieldInflux?.checked ?? false,
      waitForNetworkIdle: fieldNetworkIdle?.checked ?? false,
    };
  }

  function fillForm(config: MonitorConfig): void {
    if (fieldName) fieldName.value = config.name;
    if (fieldUrl) fieldUrl.value = config.url;
    if (fieldSchedule) fieldSchedule.value = config.schedule;
    syncBuilderFromExpr(config.schedule);
    if (fieldSelector) fieldSelector.value = config.selector;
    if (fieldMetric) fieldMetric.value = config.metric ?? "";
    if (fieldInflux) fieldInflux.checked = config.recordToInflux;
    if (fieldNetworkIdle) fieldNetworkIdle.checked = config.waitForNetworkIdle;
    document.querySelectorAll<HTMLInputElement>(".channel-checkbox").forEach(cb => {
      cb.checked = config.notifyChannels.includes(cb.value);
    });
    // Sync checkbox icons after programmatic update
    document.querySelectorAll<HTMLInputElement>(".channel-checkbox").forEach(cb => {
      const icon = cb.parentElement?.querySelector("svg") as HTMLElement | null;
      if (icon) icon.style.display = cb.checked ? "" : "none";
    });
  }

  function updatePreview(): void {
    // Only update code-preview (right panel); never touch the raw editor
    if (codePreview) {
      const source = generateMonitor(readForm());
      // renderHighlighted escapes all content via escapeHtml — safe to assign as innerHTML
      codePreview.innerHTML = renderHighlighted(source);
    }
  }

  // Standard file: pre-fill form from parsed source and render initial preview
  if (!customFile) {
    const config = parseMonitor(initialSource);
    if (config) fillForm(config);
    updatePreview();
  }

  // Schedule quick-select buttons
  document.querySelectorAll<HTMLButtonElement>("button[data-cron]").forEach(btn => {
    btn.addEventListener("click", () => {
      if (fieldSchedule) fieldSchedule.value = btn.dataset.cron!;
      syncBuilderFromExpr(btn.dataset.cron!);
      updatePreview();
    });
  });

  // Cron builder parts → update schedule input
  cronPartEls.forEach(el => {
    el?.addEventListener('input', () => {
      const expr = cronPartEls.map(e => e?.value.trim() || '*').join(' ');
      if (fieldSchedule) fieldSchedule.value = expr;
      if (cronDescEl) cronDescEl.textContent = describeCron(expr);
      updatePreview();
    });
  });

  // Form field changes → update preview (standard files only; custom has no form)
  [fieldName, fieldUrl, fieldSelector, fieldMetric].forEach(el => {
    el?.addEventListener("input", updatePreview);
  });
  fieldSchedule?.addEventListener("input", () => {
    syncBuilderFromExpr(fieldSchedule.value);
    updatePreview();
  });
  [fieldInflux, fieldNetworkIdle].forEach(el => {
    el?.addEventListener("change", updatePreview);
  });
  document.querySelectorAll(".channel-checkbox").forEach(el => {
    el.addEventListener("change", updatePreview);
  });

  // Save button
  btnSave?.addEventListener("click", async () => {
    const name = getEffectiveName();
    if (!name) {
      setGitStatus(gitStatusEl, "error", "Name is required");
      return;
    }
    const source = getSource();
    btnSave.disabled = true;
    btnSave.textContent = "Saving…";
    setGitStatus(gitStatusEl, "saving");
    try {
      const resp = await fetch(`/api/monitors/${name}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      });
      const data = await resp.json();
      if (data.status === "ok") {
        window.location.href = `/monitors/${name}`;
      } else if (data.status === "conflict") {
        btnSave.disabled = false;
        btnSave.textContent = "Save & deploy";
        setGitStatus(gitStatusEl, "conflict");
        if (conflictPanel) conflictPanel.style.display = "";
        if (conflictDiff) conflictDiff.textContent = data.diff ?? "";
      } else {
        btnSave.disabled = false;
        btnSave.textContent = "Save & deploy";
        setGitStatus(gitStatusEl, "error", data.message ?? "Unknown error");
      }
    } catch (e) {
      btnSave.disabled = false;
      btnSave.textContent = "Save & deploy";
      setGitStatus(gitStatusEl, "error", String(e));
    }
  });

  // Force push button
  btnForce?.addEventListener("click", async () => {
    const name = getEffectiveName();
    const source = getSource();
    try {
      await fetch(`/api/monitors/${name}/force-push`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      });
      window.location.href = `/monitors/${name}`;
    } catch (e) {
      setGitStatus(gitStatusEl, "error", String(e));
    }
  });

  // Discard button
  btnDiscard?.addEventListener("click", async () => {
    const name = getEffectiveName();
    try {
      const resp = await fetch(`/api/monitors/${name}/discard`, { method: "POST" });
      const data = await resp.json();
      const src = data.source ?? "";
      if (customFile && editor) {
        editor.setValue(src);
      } else {
        const config = parseMonitor(src);
        if (config) fillForm(config);
        updatePreview();
      }
      setGitStatus(gitStatusEl, "idle");
      if (conflictPanel) conflictPanel.style.display = "none";
    } catch (e) {
      setGitStatus(gitStatusEl, "error", String(e));
    }
  });

  // Dry-run button
  btnDryRun?.addEventListener("click", async () => {
    const name = getEffectiveName();
    const source = getSource();
    if (dryRunConsole) {
      dryRunConsole.textContent = "Running…";
    }
    try {
      const resp = await fetch(`/api/monitors/${name}/dry-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      });
      const data = await resp.json();
      if (dryRunConsole) {
        if (!data.lines || data.lines.length === 0) {
          dryRunConsole.textContent = "No output";
          dryRunConsole.style.color = "var(--ink3)";
        } else {
          // Build DOM nodes to avoid innerHTML with server-provided content
          dryRunConsole.textContent = "";
          for (const l of data.lines as { level: string; message: string }[]) {
            const div = document.createElement("div");
            div.className = l.level === "ERROR" ? "t-err" : l.level === "WARNING" ? "t-chg" : "t-ok";
            div.textContent = `[${l.level}] ${l.message}`;
            dryRunConsole.appendChild(div);
          }
        }
      }
    } catch (e) {
      if (dryRunConsole) dryRunConsole.textContent = `Error: ${e}`;
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
