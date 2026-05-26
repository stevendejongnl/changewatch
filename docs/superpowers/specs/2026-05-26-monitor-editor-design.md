# Monitor Editor — Design Spec

_2026-05-26_

## Overview

A web-based editor for creating and adjusting Python monitor files. Saves commit and push to the monitors git repo automatically. Follows the dark neumorphic design system (cyan accent, Inter + JetBrains Mono) established in the project design reference.

---

## Routes & API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/monitors/new` | New monitor form |
| `GET` | `/monitors/{name}/edit` | Edit existing monitor |
| `GET` | `/api/monitors/{name}/source` | Return raw `.py` source |
| `POST` | `/api/monitors/{name}/save` | Write file + git commit/push |
| `POST` | `/api/monitors/{name}/dry-run` | Run check once, stream logs via SSE |

- `/monitors/new` registered before `/monitors/{name}` so FastAPI doesn't treat `"new"` as a monitor name.
- One shared template `monitor_editor.html` for both new and edit — `mode` flag (`"new"` | `"edit"`) controls title, breadcrumb, and whether to pre-fill.

---

## Frontend Build

- `frontend/` directory at repo root — `package.json`, `vite.config.js`, TypeScript source
- `npm run build` bundles to `app/static/editor.js`
- `npm test` runs vitest for frontend unit tests
- Dockerfile: `npm ci && npm run build` before Python stage
- Bundle committed to repo — `uv run uvicorn` works without running npm

---

## Custom Python Editor

Textarea overlay pattern — two layers stacked in a wrapper:

```
<div class="editor-wrap">
  <pre  class="highlight-layer" aria-hidden>…colored spans…</pre>
  <textarea class="input-layer" spellcheck="false">…raw text…</textarea>
</div>
```

- `textarea` sits on top (transparent background), handles all keyboard input
- `pre` mirrors content, renders syntax-colored HTML
- Scroll kept in sync between the two
- Line numbers in a third sibling column

**Python tokenizer** written in-house (~80 lines, `frontend/tokenizer.ts`). Regex-based, covers: keywords, strings, comments, decorators, builtins, numbers. No npm dependency for this — simple enough to own.

**JS-side monitor parser** (`frontend/parser.ts`): mirrors `monitor_parser.py` — regex-extracts `name`, `schedule`, `url`, `notify_channels`, `selector` from source so the Raw→Form switch works client-side without a round-trip.

---

## Form ↔ Raw Toggle

Left panel has two tabs: **Form** and **Raw**.

- **Form → Raw**: generate Python from current form state, load into editor
- **Raw → Form**: parse Python, pre-fill form fields (best-effort via `monitor_parser.py`); if unparseable, stay in raw mode and show a muted "Custom file — form view unavailable" note
- Unsaved dot indicator in the tab when content differs from last-saved state

---

## UI Layout

### Desktop — 2-panel split

```
┌─ TopBar ──────────────────────────────────────────────────┐
│ ← monitors › {name}    "Adjust a Python monitor file"     │
│                              [Cancel]  [Save & deploy]    │
└───────────────────────────────────────────────────────────┘
┌─ Git status strip ────────────────────────────────────────┐
│  Saving… / ✓ Committed abc1234 / ⚠ Conflict              │
└───────────────────────────────────────────────────────────┘
┌─ Left panel (neu-raised) ───┐  ┌─ Right panel (neu-raised) ─┐
│ [Form] [Raw]  toggle tabs   │  │  Generated monitor          │
│                             │  │  chip: monitors/name.py     │
│ 1 · Basics                  │  │  ┌─ console (neu-inset) ──┐ │
│   Name (mono input)         │  │  │  …python source…       │ │
│   URL  (mono input)         │  │  └────────────────────────┘ │
│   Schedule + quick buttons  │  │                             │
│   Extraction CSS selector   │  │  ┌─ Dry-run (neu-inset) ──┐ │
│                             │  │  │  → navigating…         │ │
│ 2 · Notify on change        │  │  │  ✓ dry run OK · 1.2s   │ │
│   channel checkboxes        │  │  └────────────────────────┘ │
│   (one per APPRISE_URL_*)   │  │  [▶ Run dry-run]            │
│                             │  └─────────────────────────────┘
│ 3 · Advanced                │
│   InfluxDB toggle           │
│   Wait for network idle     │
└─────────────────────────────┘
```

Raw tab: replaces left panel with the textarea overlay editor + line numbers.

### Mobile — single column

Panels stack vertically (form first). Right panel collapses to show only the file chip + dry-run button. Schedule quick-buttons rendered as a full-width segmented control.

### Conflict UI

When a conflict is detected, the dry-run panel is replaced by a conflict panel:

- Renders the unified diff (added lines green, removed lines red, neumorphic inset well)
- **Force mine** button — `git push --force-with-lease`
- **Discard mine** button — reset to remote HEAD
- No manual merge; for monitor files one of these two choices always applies

---

## Git Operations (`app/git_editor.py`)

`GitEditor` class, same `asyncio.create_subprocess_exec` pattern as `git_sync.py`.

```
save(name: str, source: str) → SaveResult

  1. Write source to monitors_dir / name.py
  2. git add <file>
  3. git commit -m "monitor: update {name}"
  4. git push
  5. If push rejected (exit != 0, "rejected" in stderr):
       git fetch origin
       git rebase origin/<branch>   # branch detected via `git branch --show-current`
       if rebase OK → git push (retry once) → SaveResult(status="ok")
       if rebase fails → git rebase --abort → SaveResult(status="conflict", diff=…)
  6. return SaveResult(status="ok") on success
     return SaveResult(status="error", message=…) on unexpected failure
```

**`POST /api/monitors/{name}/save` response:**
```json
{ "status": "ok" }
{ "status": "conflict", "diff": "…unified diff…" }
{ "status": "error", "message": "…" }
```

No new Python dependencies — git operations via subprocess, same as existing code.

---

## Monitor Parser (`app/monitor_parser.py`)

```python
def parse_monitor(source: str) -> MonitorConfig | None
```

Regex-extracts: `name`, `schedule`, `url`, `notify_channels` from the `Monitor(...)` constructor call. Returns `None` if file doesn't match the expected shape.

```python
def generate_monitor(config: MonitorConfig) -> str
```

Renders the standard monitor template from form fields (name, schedule, url, selector, notify_channels, influx flag, wait_for_network_idle flag). When `wait_for_network_idle=True`, generated code includes `await page.wait_for_load_state("networkidle")` before extraction.

---

## Dry-Run

- `POST /api/monitors/{name}/dry-run` → SSE stream of log lines
- `Runner.run()` gets a new `dry_run: bool = False` parameter; when `True`, `ctx.apprise` and `ctx.influx` are set to `None` so no notifications or metrics are written
- Lines streamed as `data: {"level": "info", "message": "…"}` events
- Frontend appends lines to the console panel in real time
- Stream closes with a summary line: `✓ dry run OK · {duration}s` or `✗ error: {message}`

---

## Testing

Same project rules: `*_test.py`, `asyncio_mode = "auto"`, 100% pytest coverage gate.

### `app/monitor_parser_test.py`
- Known valid source → correct fields extracted
- Custom/non-standard source → returns `None`
- Roundtrip: `generate_monitor(config)` → `parse_monitor(source)` → same config

### `app/git_editor_test.py`
- Uses `tmp_path` fixture with a real `git init` + bare remote
- Clean push → `SaveResult(status="ok")`
- Push rejected → rebase succeeds → push succeeds → `SaveResult(status="ok")`
- Push rejected → rebase fails → `SaveResult(status="conflict", diff=…)` + working tree clean after abort

### `app/main_test.py` additions
- `GET /monitors/new` → 200
- `GET /monitors/{name}/edit` → 200
- `POST /api/monitors/{name}/save` → mocked `GitEditor`
- `POST /api/monitors/{name}/dry-run` → SSE stream

### `frontend/editor.test.ts` (vitest)
- Python tokenizer: keywords highlighted, strings, comments, decorators
- `parse_monitor` JS-side best-effort parser matches expected fields
- Runs via `npm test`, separate from pytest suite
