(function() {
  "use strict";
  const KEYWORDS = /* @__PURE__ */ new Set([
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "False",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "None",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "True",
    "try",
    "while",
    "with",
    "yield"
  ]);
  const BUILTINS = /* @__PURE__ */ new Set([
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "callable",
    "chr",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "eval",
    "exec",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "globals",
    "hasattr",
    "hash",
    "help",
    "hex",
    "id",
    "input",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "locals",
    "map",
    "max",
    "min",
    "next",
    "object",
    "oct",
    "open",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip"
  ]);
  function tokenize(code) {
    const tokens = [];
    let i = 0;
    while (i < code.length) {
      if (code[i] === "#") {
        const end = code.indexOf("\n", i);
        const value = end === -1 ? code.slice(i) : code.slice(i, end);
        tokens.push({ type: "comment", value });
        i += value.length;
        continue;
      }
      if (code[i] === "@") {
        let end = i + 1;
        while (end < code.length && /[\w.]/.test(code[end])) end++;
        tokens.push({ type: "decorator", value: code.slice(i, end) });
        i = end;
        continue;
      }
      if (code[i] === '"' && code.slice(i, i + 3) === '"""' || code[i] === "'" && code.slice(i, i + 3) === "'''") {
        const quote = code.slice(i, i + 3);
        const end = code.indexOf(quote, i + 3);
        if (end === -1) {
          tokens.push({ type: "string", value: code.slice(i) });
          i = code.length;
        } else {
          tokens.push({ type: "string", value: code.slice(i, end + 3) });
          i = end + 3;
        }
        continue;
      }
      if (code[i] === '"' || code[i] === "'") {
        const quote = code[i];
        let end = i + 1;
        while (end < code.length && code[end] !== quote && code[end] !== "\n") {
          if (code[end] === "\\") end++;
          end++;
        }
        if (end < code.length) end++;
        tokens.push({ type: "string", value: code.slice(i, end) });
        i = end;
        continue;
      }
      if (/[0-9]/.test(code[i])) {
        let end = i;
        while (end < code.length && /[0-9._xXoObBa-fA-F]/.test(code[end])) end++;
        tokens.push({ type: "number", value: code.slice(i, end) });
        i = end;
        continue;
      }
      if (/[a-zA-Z_]/.test(code[i])) {
        let end = i;
        while (end < code.length && /[a-zA-Z0-9_]/.test(code[end])) end++;
        const word = code.slice(i, end);
        if (KEYWORDS.has(word)) {
          tokens.push({ type: "keyword", value: word });
        } else if (BUILTINS.has(word)) {
          tokens.push({ type: "builtin", value: word });
        } else {
          tokens.push({ type: "text", value: word });
        }
        i = end;
        continue;
      }
      tokens.push({ type: "text", value: code[i] });
      i++;
    }
    return tokens;
  }
  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  const TOKEN_CLASS = {
    keyword: "t-acc",
    string: "t-ok",
    comment: "t-3",
    decorator: "t-3",
    builtin: "t-chg",
    number: "t-pen",
    text: null
  };
  function renderHighlighted(code) {
    return tokenize(code).map((tok) => {
      const cls = TOKEN_CLASS[tok.type];
      const escaped = escapeHtml(tok.value);
      return cls ? `<span class="${cls}">${escaped}</span>` : escaped;
    }).join("");
  }
  function parseMonitor(source) {
    const lines = source.split("\n").filter((l) => !l.trim().startsWith("#"));
    const src = lines.join("\n");
    const nameMatch = src.match(/\bname\s*=\s*["']([^"']+)["']/);
    const scheduleMatch = src.match(/\bschedule\s*=\s*["']([^"']+)["']/);
    if (!nameMatch || !scheduleMatch) return null;
    const urlMatch = src.match(/\burl\s*=\s*["']([^"']+)["']/);
    const selectorMatch = src.match(/extract_text\s*\(\s*page\s*,\s*["']([^"']+)["']/);
    const channelsMatch = src.match(/notify_channels\s*=\s*\[([^\]]*)\]/);
    let notifyChannels = [];
    if (channelsMatch) {
      notifyChannels = [...channelsMatch[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1]);
    }
    return {
      name: nameMatch[1],
      schedule: scheduleMatch[1],
      url: urlMatch ? urlMatch[1] : "",
      selector: selectorMatch ? selectorMatch[1] : "",
      notifyChannels,
      recordToInflux: src.includes("record_metric("),
      waitForNetworkIdle: src.includes('wait_for_load_state("networkidle")') || src.includes("wait_for_load_state('networkidle')")
    };
  }
  function generateMonitor(config) {
    const channels = JSON.stringify(config.notifyChannels);
    const imports = ["Monitor", "extract_text", "get_last_value", "set_value", "notify"];
    if (config.recordToInflux) imports.push("record_metric");
    const importLine = "from app.helpers import " + imports.join(", ");
    let checkBody = "";
    if (config.waitForNetworkIdle) {
      checkBody += '    await page.wait_for_load_state("networkidle")\n';
    }
    checkBody += `    value = await extract_text(page, ${JSON.stringify(config.selector)})
`;
    checkBody += `    prev = await get_last_value(ctx.db, ${JSON.stringify(config.name)})
`;
    checkBody += `    await set_value(ctx.db, ${JSON.stringify(config.name)}, value)
`;
    if (config.notifyChannels.length > 0) {
      checkBody += `    if prev is not None and value != prev and ctx.apprise:
`;
      checkBody += `        await notify(ctx.apprise, title=${JSON.stringify(config.name + " changed")}, body=value, tags=${channels})
`;
    }
    if (config.recordToInflux) {
      checkBody += `    if ctx.influx:
`;
      checkBody += `        await record_metric(ctx.influx, ${JSON.stringify(config.name)}, value)
`;
    }
    return [
      importLine,
      "",
      "monitor = Monitor(",
      `    name=${JSON.stringify(config.name)},`,
      `    schedule=${JSON.stringify(config.schedule)},`,
      `    url=${JSON.stringify(config.url)},`,
      `    notify_channels=${channels},`,
      ")",
      "",
      "@monitor.check",
      "async def check(page, ctx):",
      `    await page.goto(${JSON.stringify(config.url)})`,
      checkBody.trimEnd()
    ].join("\n") + "\n";
  }
  function buildEditor(container, initialSource) {
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
      "box-sizing: border-box"
    ].join(";");
    const wrapper = document.createElement("div");
    wrapper.style.cssText = [
      "display: flex",
      "height: 100%",
      "width: 100%",
      "overflow: auto",
      "background: var(--surface, #1e1e2e)",
      "border-radius: 4px"
    ].join(";");
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
      "margin-right: 0"
    ].join(";");
    const rightArea = document.createElement("div");
    rightArea.style.cssText = [
      "position: relative",
      "flex: 1",
      "min-width: 0"
    ].join(";");
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
      "z-index: 1"
    ].join(";");
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
      "z-index: 2"
    ].join(";");
    function countLines(text) {
      let count = 1;
      for (let i = 0; i < text.length; i++) {
        if (text[i] === "\n") count++;
      }
      return count;
    }
    function syncLineNumbers(text) {
      const n = countLines(text);
      const nums = [];
      for (let i = 1; i <= n; i++) nums.push(String(i));
      lineNumbers.textContent = nums.join("\n");
    }
    function syncHighlight(text) {
      pre.innerHTML = renderHighlighted(text) + " ";
    }
    function sync() {
      const text = textarea.value;
      syncLineNumbers(text);
      syncHighlight(text);
      const lineCount = countLines(text);
      const lineHeight = 13 * 1.6;
      const minHeight = lineCount * lineHeight + 24;
      rightArea.style.minHeight = minHeight + "px";
      pre.style.minHeight = minHeight + "px";
      textarea.style.minHeight = minHeight + "px";
    }
    textarea.addEventListener("keydown", (e) => {
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
    rightArea.appendChild(pre);
    rightArea.appendChild(textarea);
    wrapper.appendChild(lineNumbers);
    wrapper.appendChild(rightArea);
    container.appendChild(wrapper);
    textarea.value = initialSource;
    sync();
    return {
      getValue() {
        return textarea.value;
      },
      setValue(source) {
        textarea.value = source;
        sync();
      }
    };
  }
  function setGitStatus(el, state, msg = "") {
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
  function init() {
    const container = document.getElementById("raw-editor-container");
    if (!container) return;
    const initialSource = container.dataset.source ?? "";
    const customFile = container.dataset.customFile === "true";
    const monitorName = document.body.dataset.monitorName ?? "";
    const editor = buildEditor(container, initialSource);
    const gitStatusEl = document.getElementById("git-status");
    const codePreview = document.getElementById("code-preview");
    const dryRunConsole = document.getElementById("dry-run-console");
    const conflictPanel = document.getElementById("conflict-panel");
    const conflictDiff = document.getElementById("conflict-diff");
    const btnSave = document.getElementById("btn-save");
    const btnDryRun = document.getElementById("btn-dry-run");
    const btnForce = document.getElementById("btn-force");
    const btnDiscard = document.getElementById("btn-discard");
    const tabForm = document.getElementById("tab-form");
    const tabRaw = document.getElementById("tab-raw");
    const panelForm = document.getElementById("panel-form");
    const panelRaw = document.getElementById("panel-raw");
    const fieldName = document.getElementById("field-name");
    const fieldUrl = document.getElementById("field-url");
    const fieldSchedule = document.getElementById("field-schedule");
    const fieldSelector = document.getElementById("field-selector");
    const fieldInflux = document.getElementById("field-influx");
    const fieldNetworkIdle = document.getElementById("field-networkidle");
    function readForm() {
      const channels = [...document.querySelectorAll(".channel-checkbox:checked")].map((cb) => cb.value);
      return {
        name: fieldName.value,
        schedule: fieldSchedule.value,
        url: fieldUrl.value,
        selector: fieldSelector.value,
        notifyChannels: channels,
        recordToInflux: fieldInflux.checked,
        waitForNetworkIdle: fieldNetworkIdle.checked
      };
    }
    function fillForm(config) {
      fieldName.value = config.name;
      fieldUrl.value = config.url;
      fieldSchedule.value = config.schedule;
      fieldSelector.value = config.selector;
      fieldInflux.checked = config.recordToInflux;
      fieldNetworkIdle.checked = config.waitForNetworkIdle;
      document.querySelectorAll(".channel-checkbox").forEach((cb) => {
        cb.checked = config.notifyChannels.includes(cb.value);
      });
    }
    function updatePreview() {
      const source = generateMonitor(readForm());
      if (codePreview) codePreview.innerHTML = renderHighlighted(source);
      editor.setValue(source);
    }
    document.querySelectorAll("button[data-cron]").forEach((btn) => {
      btn.addEventListener("click", () => {
        fieldSchedule.value = btn.dataset.cron;
        updatePreview();
      });
    });
    [fieldName, fieldUrl, fieldSchedule, fieldSelector].forEach((el) => {
      el == null ? void 0 : el.addEventListener("input", updatePreview);
    });
    [fieldInflux, fieldNetworkIdle].forEach((el) => {
      el == null ? void 0 : el.addEventListener("change", updatePreview);
    });
    document.querySelectorAll(".channel-checkbox").forEach((el) => {
      el.addEventListener("change", updatePreview);
    });
    tabForm == null ? void 0 : tabForm.addEventListener("click", () => {
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
    tabRaw == null ? void 0 : tabRaw.addEventListener("click", () => {
      const source = generateMonitor(readForm());
      editor.setValue(source);
      if (codePreview) codePreview.innerHTML = renderHighlighted(source);
      panelForm.style.display = "none";
      panelRaw.style.display = "";
      tabRaw.classList.add("active");
      tabForm.classList.remove("active");
    });
    btnSave == null ? void 0 : btnSave.addEventListener("click", async () => {
      const source = panelRaw.style.display === "none" ? generateMonitor(readForm()) : editor.getValue();
      setGitStatus(gitStatusEl, "saving");
      try {
        const resp = await fetch(`/api/monitors/${monitorName}/save`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source })
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
    btnForce == null ? void 0 : btnForce.addEventListener("click", async () => {
      const source = editor.getValue();
      try {
        await fetch(`/api/monitors/${monitorName}/force-push`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source })
        });
        setGitStatus(gitStatusEl, "ok");
        if (conflictPanel) conflictPanel.style.display = "none";
      } catch (e) {
        setGitStatus(gitStatusEl, "error", String(e));
      }
    });
    btnDiscard == null ? void 0 : btnDiscard.addEventListener("click", async () => {
      try {
        const resp = await fetch(`/api/monitors/${monitorName}/discard`, { method: "POST" });
        const data = await resp.json();
        editor.setValue(data.source ?? "");
        if (codePreview) codePreview.innerHTML = renderHighlighted(data.source ?? "");
        setGitStatus(gitStatusEl, "idle");
        if (conflictPanel) conflictPanel.style.display = "none";
      } catch (e) {
        setGitStatus(gitStatusEl, "error", String(e));
      }
    });
    btnDryRun == null ? void 0 : btnDryRun.addEventListener("click", async () => {
      const source = editor.getValue();
      if (dryRunConsole) {
        dryRunConsole.textContent = "Running…";
      }
      try {
        const resp = await fetch(`/api/monitors/${monitorName}/dry-run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source })
        });
        const data = await resp.json();
        if (dryRunConsole) {
          if (!data.lines || data.lines.length === 0) {
            dryRunConsole.textContent = "No output";
            dryRunConsole.style.color = "var(--ink3)";
          } else {
            dryRunConsole.textContent = "";
            for (const l of data.lines) {
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
    if (customFile) {
      panelForm.style.display = "none";
      panelRaw.style.display = "";
      tabRaw.classList.add("active");
      tabForm.classList.remove("active");
      if (codePreview) codePreview.innerHTML = renderHighlighted(initialSource);
    } else {
      const config = parseMonitor(initialSource);
      if (config) fillForm(config);
      panelForm.style.display = "";
      panelRaw.style.display = "none";
      tabForm.classList.add("active");
      updatePreview();
    }
  }
  document.addEventListener("DOMContentLoaded", init);
})();
