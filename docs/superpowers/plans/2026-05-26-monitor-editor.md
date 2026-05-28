# Monitor Editor Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** Web-based editor for Python monitor files — form/raw toggle, git commit+push on save, dry-run console.

**Architecture:** Routes `/monitors/new` + `/monitors/{name}/edit` share `monitor_editor.html`. `GitEditor` handles commit/push/rebase. Vite+TS bundle (`app/static/editor.js`) powers textarea overlay editor, Python tokenizer, save/dry-run.

**Tech Stack:** FastAPI/Jinja2, asyncio subprocess (git), Vite + TypeScript, vitest.

---

## File Map

| Path | Action | Purpose |
|------|--------|---------|
| `app/monitor_parser.py` | Create | `MonitorConfig` + `parse_monitor()` + `generate_monitor()` |
| `app/monitor_parser_test.py` | Create | Unit tests |
| `app/git_editor.py` | Create | `GitEditor` + `SaveResult` |
| `app/git_editor_test.py` | Create | Tests with real temp git repos |
| `app/runner.py` | Modify | Add `dry_run: bool = False` to `run()` |
| `app/runner_test.py` | Modify | Add dry-run tests |
| `app/main.py` | Modify | 7 new routes + `GitEditorDep` + `BrowserDep` |
| `app/main_test.py` | Modify | Tests for new routes |
| `app/templates/monitor_editor.html` | Create | 2-panel editor template |
| `frontend/package.json` | Create | npm project |
| `frontend/tsconfig.json` | Create | TypeScript config |
| `frontend/vite.config.ts` | Create | Vite builds to `app/static/editor.js` |
| `frontend/src/tokenizer.ts` | Create | Python syntax tokenizer |
| `frontend/src/parser.ts` | Create | JS-side monitor config parser |
| `frontend/src/generator.ts` | Create | JS-side Python source generator |
| `frontend/src/editor.ts` | Create | Editor component entry point |
| `frontend/src/editor.test.ts` | Create | vitest tests |
| `app/static/editor.js` | Build | `npm run build` output — committed |
| `Dockerfile` | Modify | Add `node:20-slim` build stage |

---

## Task 1 — `app/monitor_parser.py`

**Files:** Create `app/monitor_parser.py`, `app/monitor_parser_test.py`

- [ ] Write tests in `app/monitor_parser_test.py` — import `MonitorConfig, parse_monitor, generate_monitor`. Test: extracts name/schedule/url/selector/channels from a STANDARD_SOURCE string, returns None when name or schedule missing, detects influx/networkidle flags, generate_monitor roundtrip preserves all fields.
- [ ] Run: `uv run pytest app/monitor_parser_test.py --no-cov -x -q` → fail: ModuleNotFoundError
- [ ] Create `app/monitor_parser.py`:
  - `@dataclass MonitorConfig(name, schedule, url, selector, notify_channels, record_to_influx, wait_for_network_idle)`
  - `parse_monitor(source: str) -> MonitorConfig | None` — regex extracts from Monitor() constructor call; returns None if name/schedule absent
  - `generate_monitor(config: MonitorConfig) -> str` — renders standard template string (no f-strings in the template itself, use `.format()`)
- [ ] Run: `uv run pytest app/monitor_parser_test.py --no-cov -x -q` → all pass
- [ ] `git add app/monitor_parser.py app/monitor_parser_test.py && git commit -m "feat(editor): add monitor_parser"`

---

## Task 2 — `app/git_editor.py`

**Files:** Create `app/git_editor.py`, `app/git_editor_test.py`

- [ ] Write tests in `app/git_editor_test.py`:
  - `git_repo` fixture: `tmp_path/bare.git` (bare), `tmp_path/repo` (cloned, initial commit pushed)
  - `test_save_writes_file_and_returns_ok` — SaveResult.status == "ok", file written
  - `test_save_commits_file` — git log contains "monitor: update"
  - `test_save_rebases_on_rejected_push` — clone2 pushes first; original repo's save rebases and returns ok
  - `test_save_without_git_repo_writes_file_only` — non-git tmp_path → ok, file written
- [ ] Run: `uv run pytest app/git_editor_test.py --no-cov -x -q` → fail: ModuleNotFoundError
- [ ] Create `app/git_editor.py`:
  - `@dataclass SaveResult(status: str, diff: Optional[str], message: Optional[str])`
  - `class GitEditor(monitors_dir)`:
    - `_is_git_repo() -> bool` — checks `.git` exists
    - `_run(*args, check=True) -> tuple[int, str, str]` — `asyncio.create_subprocess_exec` with cwd=monitors_dir
    - `save(name, source) -> SaveResult` — write file; if not git repo return ok; else: git add, commit, push; on push rejected: fetch + rebase origin/{branch}; if rebase ok push again; if rebase fails collect diff, abort, return conflict
- [ ] Run: `uv run pytest app/git_editor_test.py --no-cov -x -q` → all pass
- [ ] `git add app/git_editor.py app/git_editor_test.py && git commit -m "feat(editor): add GitEditor"`

---

## Task 3 — `app/runner.py` dry_run

**Files:** Modify `app/runner.py`, `app/runner_test.py`

- [ ] Append 4 tests to `app/runner_test.py`:
  - `test_runner_dry_run_returns_log_lines` — `run(m, dry_run=True)` returns list of `(level, msg)` tuples
  - `test_runner_dry_run_does_not_write_to_db` — `db.get_recent_runs()` returns `[]` after dry run
  - `test_runner_dry_run_suppresses_notifications` — `ctx.apprise is None` inside check fn; StubApprise.calls == []
  - `test_runner_normal_run_returns_empty_list` — normal `run()` returns `[]`
- [ ] Run: `uv run pytest app/runner_test.py::test_runner_dry_run_returns_log_lines --no-cov -x` → TypeError
- [ ] Change `run(self, monitor: Monitor)` signature to `run(self, monitor: Monitor, dry_run: bool = False) -> list[tuple[str, str]]`
- [ ] In `RunContext` construction: `apprise=None if dry_run else self._apprise`, same for influx
- [ ] After `await monitor.fn(page, ctx)`: `if dry_run: return list(log_buffer.lines)`
- [ ] In except block: `if dry_run: log_buffer.lines.append(("ERROR", str(exc))); return list(log_buffer.lines)`
- [ ] At end of method (after finally): `return []`
- [ ] Run: `uv run pytest app/runner_test.py --no-cov -x -q` → all pass
- [ ] `git add app/runner.py app/runner_test.py && git commit -m "feat(editor): runner dry_run mode"`

---

## Task 4 — New routes in `app/main.py`

**Files:** Modify `app/main.py`, `app/main_test.py`

- [ ] Add to `app/main_test.py`:
  - Import: `from unittest.mock import AsyncMock, MagicMock, patch` + `from app.git_editor import GitEditor, SaveResult` + `from app.main import get_git_editor`
  - `editor_client` fixture: overrides `get_git_editor` with mock that has `save = AsyncMock(return_value=SaveResult(status="ok"))`
  - Tests: `GET /monitors/new` → 200; `GET /monitors/{name}/edit` → 200 (with file); `GET /monitors/nonexistent/edit` → 404; `GET /api/monitors/{name}/source` → 200 with source; `POST /api/monitors/{name}/save` → 200 ok; conflict returns diff; `POST /api/monitors/{name}/force-push` → 200; `POST /api/monitors/{name}/discard` → 200; `POST /api/monitors/{name}/dry-run` with mocked browser → 200 with lines
- [ ] Run tests → fail (routes not added)
- [ ] Add to `app/main.py` imports: `import importlib.util`, `import tempfile`, `from pydantic import BaseModel`, `from app.git_editor import GitEditor, SaveResult as _SaveResult`, `from app.helpers import Monitor`, `from app.monitor_parser import parse_monitor`
- [ ] Add globals/deps: `_git_editor: GitEditor | None = None`; `get_git_editor()` pragma no cover; `get_browser()` pragma no cover; `GitEditorDep`; `BrowserDep`; `_SaveBody(BaseModel)`; `_DryRunBody(BaseModel)`; `_load_monitor_from_source(source, name) -> Monitor` — writes to tempdir, importlib loads it
- [ ] Add 7 routes BEFORE existing `@app.get("/monitors/{name}")`: `/monitors/new`, `/{name}/edit`, `/api/monitors/{name}/source`, `/save`, `/force-push`, `/discard`, `/dry-run`
- [ ] Run: `uv run pytest app/ --no-cov -x -q` → all pass
- [ ] `git add app/main.py app/main_test.py && git commit -m "feat(editor): add 7 editor routes"`

---

## Task 5 — Frontend build setup

**Files:** Create `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/src/editor.ts` (placeholder)

- [ ] `frontend/package.json`: scripts `build` = `vite build`, `test` = `vitest run`; devDeps: typescript ^5.4, vite ^5.2, vitest ^1.6
- [ ] `frontend/tsconfig.json`: target ES2020, moduleResolution bundler, strict true, noEmit true
- [ ] `frontend/vite.config.ts`: lib entry `src/editor.ts`, format iife, name CWEditor, fileName `() => 'editor.js'`, outDir `../app/static`, emptyOutDir false, minify false
- [ ] `frontend/src/editor.ts`: `export {}`
- [ ] `cd frontend && npm install && npm run build` → `app/static/editor.js` created
- [ ] `git add frontend/ app/static/editor.js && git commit -m "feat(editor): frontend build setup"`

---

## Task 6 — Frontend tokenizer

**Files:** Create `frontend/src/tokenizer.ts`, `frontend/src/editor.test.ts`

- [ ] Create `frontend/src/editor.test.ts` with vitest tests for `tokenize` and `renderHighlighted`:
  - keywords → type 'keyword'; strings → 'string'; comments → 'comment'; decorators → 'decorator'; numbers → 'number'; builtins → 'builtin'; triple-quoted strings → 'string'; plain identifiers → 'text'
  - `renderHighlighted('async def')` contains `<span class="t-acc">async</span>`; HTML chars escaped; strings wrapped in t-ok; comments in t-3
- [ ] `npm test` → fail: Cannot find module './tokenizer'
- [ ] Create `frontend/src/tokenizer.ts`:
  - `export interface Token { type: ..., value: string }`
  - KEYWORDS Set (and/as/async/await/def/for/if/import/return/etc), BUILTINS Set
  - `export function tokenize(code: string): Token[]` — walks char by char: #→comment, @→decorator, `"""`→triple-string, f"/'/\"→string, digits→number, alpha→keyword|builtin|text, else→text
  - `export function renderHighlighted(code: string): string` — maps token types to CSS classes (keyword→t-acc, string→t-ok, comment→t-3, decorator→t-3, builtin→t-chg, number→t-pen), escapes HTML
- [ ] `npm test` → all pass
- [ ] `git add frontend/src/tokenizer.ts frontend/src/editor.test.ts && git commit -m "feat(editor): Python tokenizer"`

---

## Task 7 — Frontend parser and generator

**Files:** Create `frontend/src/parser.ts`, `frontend/src/generator.ts`; modify `frontend/src/editor.test.ts`

- [ ] Append tests to `editor.test.ts`: parseMonitor extracts name/schedule/url/selector/channels; returns null for unparseable; detects recordToInflux/waitForNetworkIdle. generateMonitor roundtrip; includes networkidle/record_metric when flags set.
- [ ] `npm test` → fail: Cannot find './parser'
- [ ] Create `frontend/src/parser.ts`: `MonitorConfig` interface + `parseMonitor(source)` — regex mirrors Python `parse_monitor`
- [ ] Create `frontend/src/generator.ts`: `generateMonitor(config: MonitorConfig): string` — builds Python source via string concatenation (no template literals with backticks around Python f-strings to avoid TS conflicts)
- [ ] `npm test` → all pass
- [ ] `git add frontend/src/parser.ts frontend/src/generator.ts frontend/src/editor.test.ts && git commit -m "feat(editor): JS monitor parser and generator"`

---

## Task 8 — Frontend editor component

**Files:** Modify `frontend/src/editor.ts`

- [ ] Replace placeholder with full implementation:
  - `buildEditor(container)` — creates wrapper div; line-number div (fixed width, white-space:pre); pre (syntax highlight mirror, pointer-events:none, absolute); textarea (transparent bg, caret-color ink, absolute on top); sync() updates pre innerHTML and line nums on input; Tab key inserts 4 spaces; returns `{getValue, setValue}`
  - `setGitStatus(el, state, msg)` — sets text and color for idle/saving/ok/conflict/error states
  - `init()` — querySelector all panels/buttons; build editor from `#raw-editor-container` (data-source attr); `readForm()` reads all form fields into MonitorConfig; `fillForm(config)` sets all inputs; `updatePreview()` calls generateMonitor → renderHighlighted → set codePreview innerHTML; form field `.form-field` listeners call updatePreview; schedule buttons set field-schedule value; tab-form/tab-raw toggle visibility (raw→form: parseMonitor editor value; form→raw: generateMonitor from form); save btn: POST to /api/monitors/{name}/save, handle ok/conflict/error; force btn: POST to /force-push; discard btn: POST to /discard then reload source; dry-run btn: POST to /dry-run, render log lines; if data-custom-file=true start in raw mode
  - DOMContentLoaded guard
- [ ] `npm run build && npm test` → build ok, tests pass
- [ ] `git add frontend/src/editor.ts app/static/editor.js && git commit -m "feat(editor): editor component — textarea overlay, save/dry-run wiring"`

---

## Task 9 — `monitor_editor.html` template

**Files:** Create `app/templates/monitor_editor.html`

- [ ] Create template extending `base.html`:
  - Block title: "New monitor" or "Edit · {name}"
  - Topbar: breadcrumb (monitors › name › edit), h1, Cancel + "Save & deploy" buttons
  - Git status strip: `<span id="git-status">`
  - 2-column grid (`grid-template-columns: 1.1fr 1fr`):
    - Left `neu-raised`: Form/Raw seg tabs; form panel with sections (Basics: name/url/schedule+seg/selector; Notify: channel checkboxes with neumorphic check boxes; Advanced: InfluxDB toggle + network idle toggle); raw panel (hidden by default) with `<div id="raw-editor-container" data-source="..." data-custom-file="...">`
    - Right `neu-raised`: filename chip; `<div id="code-preview" class="console">`; conflict panel (hidden) with diff pre + Force/Discard btns; dry-run section with `<div id="dry-run-console">` + Run btn
  - Inline style: CSS `:has()` for toggle switches; `.channel-checkbox:not(:checked) ~ .check-icon { display:none }` for checkbox icons; mobile grid override to 1fr
  - Scripts block: `/static/editor.js`; `document.body.dataset.monitorName = {{ monitor_name | tojson }}`
- [ ] `uv run pytest --no-cov -x -q` → all pass
- [ ] `git add app/templates/monitor_editor.html && git commit -m "feat(editor): monitor_editor.html template"`

---

## Task 10 — Dockerfile + coverage gate

**Files:** Modify `Dockerfile`

- [ ] Update Dockerfile — add `FROM node:20-slim AS frontend` first stage: `npm ci` + `npm run build`; second stage copies `COPY --from=frontend /build/../app/static/editor.js ./app/static/editor.js`
- [ ] `uv run pytest` → 100% coverage. If gate fails on new files: add `# pragma: no cover` to `get_git_editor()` and `get_browser()` only (same as existing `get_db`, `get_scheduler`)
- [ ] `cd frontend && npm test` → all pass
- [ ] `git add Dockerfile && git commit -m "feat(editor): Dockerfile — npm frontend build stage"`
