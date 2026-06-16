# Mobile-First Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all pages in changewatch fully usable on mobile (390px–375px), fixing tap targets, collapsed layouts, hidden filters, and adding a sticky action bar on the monitor detail page.

**Architecture:** Pure CSS + HTML changes across 5 Jinja2 templates and base.html. No Python changes. No build step. Each task is isolated to one or two template files. Order is low-risk first.

**Tech Stack:** HTML/CSS (Jinja2 templates), vanilla JS — served by FastAPI+Jinja2. No NPM, no bundler.

---

## Files Modified

| File | Tasks |
|---|---|
| `app/templates/tags.html` | Task 1 |
| `app/templates/base.html` | Task 2 |
| `app/templates/activity.html` | Task 3 |
| `app/templates/settings.html` | Task 4 |
| `app/templates/dashboard.html` | Task 5 |
| `app/templates/monitor_detail.html` | Task 6 |
| `app/templates/monitor_editor.html` | Task 7 |

---

## Task 1: Tags page — add mobile breakpoint

**Files:**
- Modify: `app/templates/tags.html:16`

**Problem:** Line 16 is `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:18px">`. There is no mobile breakpoint, so on 390px the three columns each become ~120px — too narrow, text overflows.

- [ ] **Step 1: Read the current file**

Open `app/templates/tags.html`. Confirm line 16 is the grid div and there are no existing `<style>` blocks or `{% block head %}` blocks.

- [ ] **Step 2: Replace inline grid style with a CSS class**

Replace:
```html
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:18px">
```

With:
```html
<div class="tags-grid">
```

Then add a `{% block head %}` block at the top (after `{% block mob_tags %}active{% endblock %}`):

```html
{% block head %}
<style>
  .tags-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 18px;
  }
  @media (max-width: 700px) {
    .tags-grid { grid-template-columns: 1fr; gap: 10px; }
  }
</style>
{% endblock %}
```

- [ ] **Step 3: Verify visually (manual)**

Start the dev server (`uv run uvicorn app.main:app --reload`) and open `/tags` at both 1200px and 390px width. At 1200px: 3 columns. At 390px: 1 column, full-width rows.

- [ ] **Step 4: Commit**

```bash
git add app/templates/tags.html
git commit -m "fix(tags): add 1-col grid breakpoint at ≤700px"
```

---

## Task 2: Tap targets — mobile tab bar and icon buttons

**Files:**
- Modify: `app/templates/base.html:370-386`

**Problem:** `.mobile-tab-icon` is `width:36px;height:28px` — below the 48×48px WCAG minimum. The outer `.mobile-tab` has only `padding:6px 4px` so total height is 28+12=40px. Icon buttons (`.btn.icon`) use `padding:9px` giving 9+9+14=32px total.

- [ ] **Step 1: Increase mobile tab touch area**

In `app/templates/base.html`, find the `@media (max-width: 700px)` block (around line 337). Locate the `.mobile-tab` and `.mobile-tab-icon` rules.

Change:
```css
      .mobile-tab {
        flex: 1;
        display: flex; flex-direction: column; align-items: center; gap: 3px;
        background: transparent; border: 0;
        color: var(--ink-3);
        padding: 6px 4px; cursor: pointer;
        font: 500 9.5px var(--sans); letter-spacing: 0.05em; text-transform: uppercase;
      }
      .mobile-tab.active { color: var(--accent); }
      .mobile-tab-icon {
        width: 36px; height: 28px;
        border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
      }
```

To:
```css
      .mobile-tab {
        flex: 1;
        display: flex; flex-direction: column; align-items: center; gap: 3px;
        background: transparent; border: 0;
        color: var(--ink-3);
        padding: 4px 4px 2px; cursor: pointer;
        font: 500 9.5px var(--sans); letter-spacing: 0.05em; text-transform: uppercase;
        min-height: 48px; justify-content: center;
      }
      .mobile-tab.active { color: var(--accent); }
      .mobile-tab-icon {
        width: 44px; height: 36px;
        border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
      }
```

- [ ] **Step 2: Increase icon button touch area on mobile**

In the same `@media (max-width: 700px)` block, add a rule for `.btn.icon`:

```css
      .btn.icon { min-width: 44px; min-height: 44px; padding: 12px; }
```

Add this after the `.topbar-right .btn` rule.

- [ ] **Step 3: Verify visually (manual)**

Open base shell at 390px. Bottom tab bar items should feel noticeably larger. Each tab should be at least 44px tall.

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "fix(a11y): increase mobile tab and icon button touch targets to 44px"
```

---

## Task 3: Activity page — restore monitor filter on mobile

**Files:**
- Modify: `app/templates/activity.html:133-142, 161-178`

**Problem:** At ≤700px, `.mon-select-wrap { display: none }` hides the monitor name filter with no replacement. Users can't filter by monitor on mobile.

**Solution:** Add a native `<select>` for mobile that appears above the filter row only on mobile. It calls the same `filterActivity()` JS function.

- [ ] **Step 1: Add a mobile-only native select above the filter row**

In `app/templates/activity.html`, in `{% block content %}`, the filter section starts at line 160. Add a mobile-only native select **before** the `.filter-row` div:

```html
<!-- Mobile monitor filter (native select, shown only on mobile) -->
<div class="mob-mon-filter">
  <select class="input" style="font-size:12px" onchange="filterActivity(null, null)" id="mon-filter-mobile">
    <option value="">All monitors</option>
    {% for name in monitor_names %}
    <option value="{{ name }}">{{ name }}</option>
    {% endfor %}
  </select>
</div>
```

- [ ] **Step 2: Add CSS for the mobile filter and sync with desktop select**

In the `<style>` block in `{% block head %}`, add:

```css
  .mob-mon-filter { display: none; margin-bottom: 10px; }
  @media (max-width: 700px) {
    .mob-mon-filter { display: block; }
    .mon-select-wrap { display: none; }
  }
```

Remove the existing line in the `@media (max-width: 700px)` block:
```css
    .mon-select-wrap { display: none; }
```
(It's now in the new combined block above — do not duplicate it.)

- [ ] **Step 3: Update `filterActivity` to read from both selects**

In `{% block scripts %}`, find the `filterActivity` function and update it so it reads the monitor filter from whichever select is visible. The existing function reads `document.getElementById('mon-filter').value`. Update it to also check `mon-filter-mobile`:

```js
  function filterActivity(status, btn) {
    if (status && btn) {
      document.querySelectorAll('.filter-row .seg button').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
    }
    var activeStatus = document.querySelector('.filter-row .seg button.on')?.dataset.status || 'all';
    var desktopSel = document.getElementById('mon-filter');
    var mobileSel = document.getElementById('mon-filter-mobile');
    var monName = (desktopSel && desktopSel.offsetParent ? desktopSel.value : '') ||
                  (mobileSel && mobileSel.offsetParent ? mobileSel.value : '');
    document.querySelectorAll('#activity-feed .activity-row').forEach(function(row) {
      var statusMatch = activeStatus === 'all' || row.dataset.status === activeStatus;
      var monMatch = !monName || row.dataset.monitor === monName;
      row.style.display = statusMatch && monMatch ? '' : 'none';
    });
  }
```

Also add `data-status` to the seg buttons so the updated function can read the active status:

```html
  <div class="seg">
    <button class="on" data-status="all" onclick="filterActivity('all', this)">All</button>
    <button data-status="error" onclick="filterActivity('error', this)">Errors</button>
    <button data-status="changed" onclick="filterActivity('changed', this)">Changes</button>
    <button data-status="ok" onclick="filterActivity('ok', this)">OK</button>
  </div>
```

- [ ] **Step 4: Verify visually (manual)**

At 1200px: existing `.mon-select-wrap` dropdown appears in filter row; mobile select hidden. At 390px: native select shows above filter row; filtering by monitor works.

- [ ] **Step 5: Commit**

```bash
git add app/templates/activity.html
git commit -m "fix(activity): add native monitor filter select for mobile"
```

---

## Task 4: Settings — log console max-height on mobile

**Files:**
- Modify: `app/templates/settings.html:101-104`

**Problem:** `.log-console-wrap { height: 320px }` (line 85) is a fixed height. On a 667px iPhone SE, this is ~48% of the viewport — too much. The existing `@media (max-width: 700px)` block (line 101) doesn't address this.

- [ ] **Step 1: Add log console height override in mobile breakpoint**

In `app/templates/settings.html`, find the existing `@media (max-width: 700px)` block:

```css
  @media (max-width: 700px) {
    .db-stats-grid { grid-template-columns: repeat(2, 1fr); }
    .log-controls { gap: 6px; }
  }
```

Change it to:

```css
  @media (max-width: 700px) {
    .db-stats-grid { grid-template-columns: repeat(2, 1fr); }
    .log-controls { gap: 6px; }
    .log-console-wrap { height: auto; max-height: 40vh; }
  }
```

- [ ] **Step 2: Verify visually (manual)**

Open `/settings` at 390px. Log console should be at most 40% of viewport height and scrollable.

- [ ] **Step 3: Commit**

```bash
git add app/templates/settings.html
git commit -m "fix(settings): cap log console at 40vh on mobile"
```

---

## Task 5: Dashboard — whole-card tap, hide action buttons on mobile

**Files:**
- Modify: `app/templates/dashboard.html:235-301`

**Problem:** The three 32×32px icon buttons (favorite, link, run) in `.monitor-card-header` are below WCAG minimums. The monitor name is an `<a>` but only covers the text. On mobile, users want to tap the whole card to open the detail page — the three small buttons are not needed since detail page has all actions.

**Solution:** Wrap the entire card in an `<a>` pointing to the detail page (so whole card is tappable). Hide `.monitor-card-header` action buttons on mobile. On desktop: unchanged.

- [ ] **Step 1: Wrap each card in an anchor**

In `app/templates/dashboard.html`, the grid starts at line 233. Each card is:

```html
  <div class="neu-raised monitor-card" data-status="{{ m.status }}" data-monitor="{{ m.monitor_name }}">
```

Change to:

```html
  <a href="/monitors/{{ m.monitor_name }}" class="neu-raised monitor-card" data-status="{{ m.status }}" data-monitor="{{ m.monitor_name }}" style="display:flex;flex-direction:column;gap:14px;text-decoration:none;color:inherit">
```

And close the card with `</a>` instead of `</div>` at line 301.

The existing `<a href="/monitors/...">` around the monitor name (line 246) becomes redundant nesting. Change it to a `<span>` to avoid nested anchors:

```html
          <span class="monitor-name">{{ m.display_name }}</span>
```

- [ ] **Step 2: Hide action buttons on mobile via CSS**

In the `@media (max-width: 700px)` block (around line 138 in dashboard.html), add:

```css
    .monitor-card .fav-btn,
    .monitor-card .run-btn,
    .monitor-card > a.btn.icon { display: none; }
```

This hides the fav button, run button, and the external link button (which has class `btn icon`) on mobile. The card itself remains tappable via the outer `<a>`.

- [ ] **Step 3: Fix `toggleFavorite` / `runMonitor` clicks — prevent card navigation**

The fav and run buttons call `toggleFavorite(name, this)` and `runMonitor(name)` via `onclick`. Since these are now inside an `<a>`, clicking them would also trigger card navigation. Add `event.preventDefault()` and `event.stopPropagation()`:

On the fav button:
```html
        onclick="event.preventDefault();event.stopPropagation();toggleFavorite('{{ m.monitor_name }}', this)"
```

On the run button:
```html
          onclick="event.preventDefault();event.stopPropagation();runMonitor('{{ m.monitor_name }}')"
```

On the product URL link (external link button), since it's an `<a>` inside an `<a>`, convert it to a button that opens the URL:
```html
      <button class="btn icon" style="width:32px;height:32px;justify-content:center;color:var(--ink-3)"
        onclick="event.preventDefault();event.stopPropagation();window.open('{{ product_url }}', '_blank')" title="Open product page">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M7 17 17 7"/><path d="M8 7h9v9"/>
        </svg>
      </button>
```

- [ ] **Step 4: Fix SSE card update — `updateCard` finds the card via selector**

The SSE JS (line 453) does `document.querySelector('.monitor-card[data-monitor="..."]')`. Since the card is now an `<a>`, the selector still works because we kept `data-monitor` on the `<a>`. Verify by checking: does `document.querySelector('a.monitor-card[data-monitor="..."]')` work? Yes, `data-*` attributes work on any element. No change needed.

- [ ] **Step 5: Fix `filterMonitors` — it queries `.neu-raised`**

Line 317: `document.querySelectorAll('#monitor-grid .neu-raised')`. An `<a>` with class `neu-raised monitor-card` still matches `.neu-raised`. No change needed.

- [ ] **Step 6: Fix `toggleShowAll` — it `appendChild` a new `div` for non-favorite cards**

Line 386 creates `var card = document.createElement('div')`. Change to `document.createElement('a')` and set `card.href = '/monitors/' + m.monitor_name` to make non-favorite cards also tappable. Also change the `fav-btn` onclick in the innerHTML to include `event.preventDefault();event.stopPropagation();`.

In the `toggleShowAll` function, find:
```js
          var card = document.createElement('div');
          card.className = 'neu-raised monitor-card';
```

Change to:
```js
          var card = document.createElement('a');
          card.href = '/monitors/' + m.monitor_name;
          card.className = 'neu-raised monitor-card';
          card.style.display = 'flex';
          card.style.flexDirection = 'column';
          card.style.gap = '14px';
          card.style.textDecoration = 'none';
          card.style.color = 'inherit';
```

And in the innerHTML string, change the fav-btn onclick:
```js
onclick="event.preventDefault();event.stopPropagation();toggleFavorite(\'' + m.monitor_name + '\', this)"
```

- [ ] **Step 7: Verify visually (manual)**

At 390px: tapping a card navigates to detail. Action buttons not visible. At 1200px: fav star, external link, and run buttons still appear. SSE live updates still work.

- [ ] **Step 8: Commit**

```bash
git add app/templates/dashboard.html
git commit -m "feat(dashboard): whole-card tap on mobile, hide action buttons ≤700px"
```

---

## Task 6: Monitor detail — sticky action bar, 2-metric strip, runs flex

**Files:**
- Modify: `app/templates/monitor_detail.html`

This is the most involved task. Three sub-changes:
1. Metric strip: show only 2 cards on mobile (status + last value)
2. Topbar: hide action buttons on mobile
3. Sticky bottom action bar on mobile with Run now / Pause / Delete

### Sub-task 6a: Metric strip — 2 cards on mobile

- [ ] **Step 1: Add mobile class to the two key metric cards**

In `monitor_detail.html` line 220, the metric strip has 5 `.metric-card` divs. The first is "schedule", second is "status", third is "success rate", fourth is "total runs", fifth is "avg duration".

We want to show only "status" and "last value" on mobile. But there's no "last value" card — the last value is shown in run rows, not the metric strip. So show **status** (2nd card) and **total runs** (4th card) — these two are the most informative at a glance.

Add class `metric-key` to the status card (line ~226) and total-runs card (line ~248):

```html
  <div class="neu-raised-sm metric-card metric-key">
    <div class="eyebrow">status</div>
    ...
  </div>
```

```html
  <div class="neu-raised-sm metric-card metric-key">
    <div class="eyebrow">total runs</div>
    ...
  </div>
```

Leave schedule, success-rate, avg-duration cards without `metric-key`.

- [ ] **Step 2: Hide non-key metric cards on mobile**

In the `@media (max-width: 700px)` block in `monitor_detail.html` (around line 151), add:

```css
    .metric-card:not(.metric-key) { display: none; }
    .metric-strip { grid-template-columns: repeat(2, 1fr); gap: 10px; }
```

Remove the existing line `  .metric-strip { grid-template-columns: repeat(2, 1fr); gap: 10px; }` if present (it's already there at line 152 — replace it with the two lines above).

### Sub-task 6b: Hide topbar action buttons on mobile

- [ ] **Step 3: Hide topbar-right on mobile in detail page**

In `monitor_detail.html`, the topbar buttons (Open, Edit, Pause, Run now, Delete) are in `<div class="topbar-right">` lines 178-211. We want to hide the entire `topbar-right` on mobile since the sticky bar replaces them.

In the `@media (max-width: 700px)` block, add:

```css
    .detail-topbar-right { display: none; }
```

Add class `detail-topbar-right` to the topbar-right div:

```html
<div class="topbar-right detail-topbar-right">
```

### Sub-task 6c: Sticky bottom action bar

- [ ] **Step 4: Add the sticky action bar HTML**

After the `{% endblock %}` for topbar and before `{% block content %}`, add a new block. Actually in Jinja2 this needs to go inside the `{% block content %}` or as a separate element. Best approach: add it at the end of `{% block content %}`, just before the `{% endblock %}`.

At the very end of `{% block content %}` (after line 370 `</div><!-- end .detail-body -->`), add:

```html
<!-- Mobile sticky action bar -->
<div class="mob-action-bar" id="mob-action-bar">
  <button class="mob-action-btn primary" id="mob-run-btn" onclick="runNow()">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" stroke="none"><path d="M7 5l11 7-11 7V5z"/></svg>
    <span id="mob-run-label">Run now</span>
  </button>
  <button class="mob-action-btn" id="mob-pause-btn" onclick="togglePause()">
    {% if paused %}
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" stroke="none"><path d="M7 5l11 7-11 7V5z"/></svg>
    <span id="mob-pause-label">Resume</span>
    {% else %}
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" stroke="none"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
    <span id="mob-pause-label">Pause</span>
    {% endif %}
  </button>
  <button class="mob-action-btn danger" onclick="deleteMonitor()">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
    Delete
  </button>
</div>
```

- [ ] **Step 5: Add CSS for the sticky action bar**

In the `<style>` block in `{% block head %}`, add:

```css
  /* ── Mobile sticky action bar ───────────────────────────── */
  .mob-action-bar { display: none; }
  @media (max-width: 700px) {
    .mob-action-bar {
      display: flex;
      gap: 8px;
      position: fixed;
      bottom: 72px; /* above mobile tab bar (height ~72px including safe area) */
      left: 12px; right: 12px;
      z-index: 90;
      padding: 10px 12px;
      border-radius: 16px;
      background: var(--surface);
      box-shadow: -4px -4px 10px var(--raise), 4px 4px 14px var(--shadow);
    }
    .mob-action-btn {
      flex: 1;
      display: flex; align-items: center; justify-content: center; gap: 6px;
      padding: 12px 8px;
      border-radius: 10px;
      border: 0;
      cursor: pointer;
      font: 500 12px var(--sans);
      color: var(--ink);
      background: var(--surface);
      box-shadow: -2px -2px 5px var(--raise), 3px 3px 7px var(--shadow);
    }
    .mob-action-btn.primary { color: var(--accent); }
    .mob-action-btn.danger  { color: var(--err); }
    .mob-action-btn:active {
      box-shadow: inset 2px 2px 5px var(--shadow), inset -2px -2px 5px var(--raise);
    }
    /* extra bottom padding so content isn't hidden behind action bar */
    .content-card { padding-bottom: 130px; }
  }
```

- [ ] **Step 6: Sync pause/resume state between topbar and mobile bar**

The existing `togglePause()` JS function updates `#pause-label` and the SVG in `#pause-btn`. We need it to also update `#mob-pause-label` and the SVG in `#mob-pause-btn`.

Find the `togglePause` function in `{% block scripts %}` (around line 427). The section that updates the button reads:

```js
        _paused = !_paused;
        label.textContent = _paused ? 'Resume' : 'Pause';
        const svgEl = btn.querySelector('svg');
        if (svgEl) {
          if (_paused) {
            svgEl.innerHTML = '<path d="M7 5l11 7-11 7V5z"/>';
          } else {
            svgEl.innerHTML = '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>';
          }
        }
```

After those lines (still inside the `if (res.ok)` block), add:

```js
        const mobLabel = document.getElementById('mob-pause-label');
        const mobBtn = document.getElementById('mob-pause-btn');
        if (mobLabel) mobLabel.textContent = _paused ? 'Resume' : 'Pause';
        if (mobBtn) {
          const mobSvg = mobBtn.querySelector('svg');
          if (mobSvg) {
            mobSvg.innerHTML = _paused
              ? '<path d="M7 5l11 7-11 7V5z"/>'
              : '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>';
          }
        }
```

- [ ] **Step 7: Sync runNow state to mobile button label**

The existing `runNow()` function updates `#run-label` via `label.textContent = 'Queued…'`. Add the same for the mobile button. In `runNow()`, after:

```js
    const label = document.getElementById('run-label');
    btn.disabled = true;
    label.textContent = 'Queued…';
```

Add:

```js
    const mobBtn = document.getElementById('mob-run-btn');
    const mobLabel = document.getElementById('mob-run-label');
    if (mobBtn) mobBtn.disabled = true;
    if (mobLabel) mobLabel.textContent = 'Queued…';
```

And in the `location.reload()` path and catch block, re-enable the mobile button if needed (the page reloads anyway so no extra action required).

- [ ] **Step 8: Verify visually (manual)**

At 390px: topbar buttons not visible. Sticky bar appears above tab bar with Run now, Pause, Delete. Run now button queues run and reloads. Pause toggles correctly. Delete works. At 1200px: sticky bar hidden; topbar buttons appear normally.

- [ ] **Step 9: Commit**

```bash
git add app/templates/monitor_detail.html
git commit -m "feat(detail): sticky action bar, 2-metric strip, hidden topbar btns on mobile"
```

---

## Task 7: Monitor editor — plain textarea on mobile, helpers bottom sheet

**Files:**
- Modify: `app/templates/monitor_editor.html`

**Problem:**
- Rich editor in `.raw-wrap` fixed at 560px height with horizontal scroll
- Helpers drawer is `position:fixed;right:0` at 320px width — on a 320px device it covers the full screen with no backdrop
- No way to close the drawer by tapping outside it

### Sub-task 7a: Plain textarea on mobile

- [ ] **Step 1: Add a plain textarea as the mobile code editor**

In `monitor_editor.html`, find the `div id="raw-editor-container"` (line 319–326). There are two of these: one with content (custom file true) and one as fallback. The main one renders when `not custom_file`:

```html
    <div class="raw-wrap"
         id="raw-editor-container"
```

After (not instead of) this raw-wrap div, add a plain textarea that is hidden on desktop and shown on mobile:

```html
    <textarea
      class="input mob-code-editor"
      name="source"
      id="mob-code-editor"
      rows="15"
      spellcheck="false"
      autocorrect="off"
      autocapitalize="off"
    >{{ source | e }}</textarea>
```

This textarea has `name="source"` — same as the rich editor. On mobile, both will be in the DOM. We need to ensure only one submits. We handle this by disabling the hidden one on form submit.

- [ ] **Step 2: Add CSS to swap editors at ≤700px**

In the `<style>` block inside `{% block content %}`, add:

```css
  .mob-code-editor {
    display: none;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.5;
    height: auto;
    min-height: 200px;
    max-height: 60vh;
    overflow-y: auto;
    resize: vertical;
    white-space: pre;
    overflow-x: auto;
  }
  @media (max-width: 700px) {
    .raw-wrap { display: none !important; }
    .mob-code-editor { display: block; }
    .helpers-drawer {
      top: auto !important;
      bottom: 0 !important;
      right: 0 !important;
      left: 0 !important;
      width: 100% !important;
      height: 70vh;
      border-radius: 20px 20px 0 0;
      transform: translateY(100%) !important;
    }
    .helpers-drawer.open { transform: translateY(0) !important; }
    .helpers-drawer-backdrop { display: block; }
  }
```

- [ ] **Step 3: Add a backdrop for the helpers drawer on mobile**

Add a backdrop div to the DOM (at the end of `{% block content %}`, after the helpers drawer):

```html
<div class="helpers-drawer-backdrop" id="helpers-backdrop" onclick="closeHelpers()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:199"></div>
```

In CSS:
```css
  .helpers-drawer-backdrop { display: none; }
```

Update `openHelpers()` and `closeHelpers()` JS:

```js
  function openHelpers() {
    document.getElementById('helpers-drawer').classList.add('open');
    const bd = document.getElementById('helpers-backdrop');
    if (bd) bd.style.display = '';
  }
  function closeHelpers() {
    document.getElementById('helpers-drawer').classList.remove('open');
    const bd = document.getElementById('helpers-backdrop');
    if (bd) bd.style.display = 'none';
  }
```

- [ ] **Step 4: Disable the rich editor textarea on form submit when on mobile**

The rich editor syncs to a hidden textarea `.input-layer` with `name="source"`. On mobile, we want the plain textarea to submit instead. Add a submit handler:

```js
  document.querySelector('form').addEventListener('submit', function() {
    if (window.innerWidth <= 700) {
      // disable all source inputs from the rich editor so only mob-code-editor submits
      document.querySelectorAll('#raw-editor-container textarea').forEach(function(el) {
        el.disabled = true;
      });
    } else {
      // disable mob textarea so only rich editor submits
      var mob = document.getElementById('mob-code-editor');
      if (mob) mob.disabled = true;
    }
  });
```

- [ ] **Step 5: Add "Helpers ↑" button visible on mobile**

The existing "Helpers" button is in `topbar-right` which wraps on mobile but is still visible. However, on mobile the topbar is cramped. Add a second helpers trigger button below the textarea, visible only on mobile:

```html
    <button type="button" class="btn mob-helpers-btn" onclick="openHelpers()">Helpers ↑</button>
```

Add CSS:
```css
  .mob-helpers-btn { display: none; margin-top: 10px; width: 100%; justify-content: center; }
  @media (max-width: 700px) { .mob-helpers-btn { display: flex; } }
```

- [ ] **Step 6: Verify visually (manual)**

At 390px: plain textarea visible, rich editor hidden. Type code in textarea, submit — confirm monitor saves correctly. Tap "Helpers ↑": drawer slides up from bottom. Tap backdrop or X: drawer closes. At 1200px: rich editor present, plain textarea hidden. Submit works normally.

- [ ] **Step 7: Commit**

```bash
git add app/templates/monitor_editor.html
git commit -m "feat(editor): plain textarea + bottom-sheet helpers on mobile ≤700px"
```

---

## Testing Checklist

After all tasks, verify at 390px (Chrome DevTools iPhone 14 preset):

- [ ] Tags: 1-column grid, no horizontal scroll
- [ ] Base: mobile tabs feel large enough (44px+ touch area)
- [ ] Activity: native select filters activity by monitor correctly
- [ ] Activity: status seg buttons still filter correctly
- [ ] Settings: log console scrollable, not half-screen
- [ ] Dashboard: tap card → detail page navigation
- [ ] Dashboard: no horizontal scroll
- [ ] Dashboard: SSE live update still works (LED/status changes on run)
- [ ] Dashboard: on desktop (1200px): fav/run/link buttons still visible
- [ ] Detail: sticky action bar visible above tab bar
- [ ] Detail: Run now queues run and reloads on complete
- [ ] Detail: Pause/Resume toggles correctly and syncs label
- [ ] Detail: Delete works
- [ ] Detail: topbar action buttons hidden on mobile
- [ ] Detail: only 2 metric cards visible on mobile (status + total runs)
- [ ] Detail: metric strip full 5-col on desktop
- [ ] Detail: chart range selector still works
- [ ] Editor: plain textarea shown on mobile
- [ ] Editor: submit from mobile textarea saves monitor code
- [ ] Editor: Helpers ↑ button opens bottom sheet
- [ ] Editor: backdrop tap closes helpers sheet
- [ ] Editor: on desktop, rich editor still works normally
- [ ] All pages: no page-level horizontal scroll at 390px
- [ ] All pages: no page-level horizontal scroll at 320px
