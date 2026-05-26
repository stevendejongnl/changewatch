import { renderHighlighted } from "./tokenizer";
import { parseMonitor, type MonitorConfig } from "./parser";
import { generateMonitor } from "./generator";

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

  const editor = buildEditor(container, initialSource);

  // DOM refs
  const gitStatusEl = document.getElementById("git-status") as HTMLElement;
  const codePreview = document.getElementById("code-preview") as HTMLElement;
  const dryRunConsole = document.getElementById("dry-run-console") as HTMLElement;
  const conflictPanel = document.getElementById("conflict-panel") as HTMLElement;
  const conflictDiff = document.getElementById("conflict-diff") as HTMLElement;
  const btnSave = document.getElementById("btn-save") as HTMLButtonElement;
  const btnDryRun = document.getElementById("btn-dry-run") as HTMLButtonElement;
  const btnForce = document.getElementById("btn-force") as HTMLButtonElement;
  const btnDiscard = document.getElementById("btn-discard") as HTMLButtonElement;
  const tabForm = document.getElementById("tab-form") as HTMLButtonElement;
  const tabRaw = document.getElementById("tab-raw") as HTMLButtonElement;
  const panelForm = document.getElementById("panel-form") as HTMLElement;
  const panelRaw = document.getElementById("panel-raw") as HTMLElement;

  // Form field refs
  const fieldName = document.getElementById("field-name") as HTMLInputElement;
  const fieldUrl = document.getElementById("field-url") as HTMLInputElement;
  const fieldSchedule = document.getElementById("field-schedule") as HTMLInputElement;
  const fieldSelector = document.getElementById("field-selector") as HTMLInputElement;
  const fieldInflux = document.getElementById("field-influx") as HTMLInputElement;
  const fieldNetworkIdle = document.getElementById("field-networkidle") as HTMLInputElement;

  function readForm(): MonitorConfig {
    const channels = [...document.querySelectorAll<HTMLInputElement>(".channel-checkbox:checked")]
      .map(cb => cb.value);
    return {
      name: fieldName.value,
      schedule: fieldSchedule.value,
      url: fieldUrl.value,
      selector: fieldSelector.value,
      notifyChannels: channels,
      recordToInflux: fieldInflux.checked,
      waitForNetworkIdle: fieldNetworkIdle.checked,
    };
  }

  function fillForm(config: MonitorConfig): void {
    fieldName.value = config.name;
    fieldUrl.value = config.url;
    fieldSchedule.value = config.schedule;
    fieldSelector.value = config.selector;
    fieldInflux.checked = config.recordToInflux;
    fieldNetworkIdle.checked = config.waitForNetworkIdle;
    document.querySelectorAll<HTMLInputElement>(".channel-checkbox").forEach(cb => {
      cb.checked = config.notifyChannels.includes(cb.value);
    });
  }

  function updatePreview(): void {
    const source = generateMonitor(readForm());
    // renderHighlighted escapes all content via escapeHtml — safe to assign as innerHTML
    if (codePreview) codePreview.innerHTML = renderHighlighted(source);
    editor.setValue(source);
  }

  // Schedule quick-select buttons
  document.querySelectorAll<HTMLButtonElement>("button[data-cron]").forEach(btn => {
    btn.addEventListener("click", () => {
      fieldSchedule.value = btn.dataset.cron!;
      updatePreview();
    });
  });

  // Form field changes → update preview
  [fieldName, fieldUrl, fieldSchedule, fieldSelector].forEach(el => {
    el?.addEventListener("input", updatePreview);
  });
  [fieldInflux, fieldNetworkIdle].forEach(el => {
    el?.addEventListener("change", updatePreview);
  });
  document.querySelectorAll(".channel-checkbox").forEach(el => {
    el.addEventListener("change", updatePreview);
  });

  // Tab switching
  tabForm?.addEventListener("click", () => {
    const source = editor.getValue();
    const config = parseMonitor(source);
    if (config) {
      fillForm(config);
    }
    panelForm.style.display = "";
    panelRaw.style.display = "none";
    tabForm.classList.add("active");
    tabRaw.classList.remove("active");
    updatePreview();
  });

  tabRaw?.addEventListener("click", () => {
    const source = generateMonitor(readForm());
    editor.setValue(source);
    // renderHighlighted escapes all content via escapeHtml — safe to assign as innerHTML
    if (codePreview) codePreview.innerHTML = renderHighlighted(source);
    panelForm.style.display = "none";
    panelRaw.style.display = "";
    tabRaw.classList.add("active");
    tabForm.classList.remove("active");
  });

  // Save button
  btnSave?.addEventListener("click", async () => {
    const source = panelRaw.style.display === "none"
      ? generateMonitor(readForm())
      : editor.getValue();
    setGitStatus(gitStatusEl, "saving");
    try {
      const resp = await fetch(`/api/monitors/${monitorName}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      });
      const data = await resp.json();
      if (data.status === "ok") {
        setGitStatus(gitStatusEl, "ok");
        if (conflictPanel) conflictPanel.style.display = "none";
      } else if (data.status === "conflict") {
        setGitStatus(gitStatusEl, "conflict");
        if (conflictPanel) conflictPanel.style.display = "";
        if (conflictDiff) conflictDiff.textContent = data.diff ?? "";
      } else {
        setGitStatus(gitStatusEl, "error", data.message ?? "Unknown error");
      }
    } catch (e) {
      setGitStatus(gitStatusEl, "error", String(e));
    }
  });

  // Force push button
  btnForce?.addEventListener("click", async () => {
    const source = editor.getValue();
    try {
      await fetch(`/api/monitors/${monitorName}/force-push`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      });
      setGitStatus(gitStatusEl, "ok");
      if (conflictPanel) conflictPanel.style.display = "none";
    } catch (e) {
      setGitStatus(gitStatusEl, "error", String(e));
    }
  });

  // Discard button
  btnDiscard?.addEventListener("click", async () => {
    try {
      const resp = await fetch(`/api/monitors/${monitorName}/discard`, { method: "POST" });
      const data = await resp.json();
      editor.setValue(data.source ?? "");
      // renderHighlighted escapes all content via escapeHtml — safe to assign as innerHTML
      if (codePreview) codePreview.innerHTML = renderHighlighted(data.source ?? "");
      setGitStatus(gitStatusEl, "idle");
      if (conflictPanel) conflictPanel.style.display = "none";
    } catch (e) {
      setGitStatus(gitStatusEl, "error", String(e));
    }
  });

  // Dry-run button
  btnDryRun?.addEventListener("click", async () => {
    const source = editor.getValue();
    if (dryRunConsole) {
      dryRunConsole.textContent = "Running…";
    }
    try {
      const resp = await fetch(`/api/monitors/${monitorName}/dry-run`, {
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

  // Initial state
  if (customFile) {
    // Custom file: start in raw mode
    panelForm.style.display = "none";
    panelRaw.style.display = "";
    tabRaw.classList.add("active");
    tabForm.classList.remove("active");
    // renderHighlighted escapes all content via escapeHtml — safe to assign as innerHTML
    if (codePreview) codePreview.innerHTML = renderHighlighted(initialSource);
  } else {
    // Standard file: start in form mode
    const config = parseMonitor(initialSource);
    if (config) fillForm(config);
    panelForm.style.display = "";
    panelRaw.style.display = "none";
    tabForm.classList.add("active");
    updatePreview();
  }
}

document.addEventListener("DOMContentLoaded", init);
