# Mobile-First Redesign — changewatch

**Date:** 2026-06-16  
**Status:** Approved for implementation  
**Approach:** Mobile-first redesign of key pages. Desktop inherits from mobile-first CSS. No separate mobile view — one codebase, CSS-driven.

---

## Context

The app is used primarily on mobile to check monitor status, trigger runs, and edit monitors. The current UI is desktop-first with a 700px breakpoint bolted on. 37 mobile issues found in audit; 10 high-severity.

---

## Design Decisions

| Question | Decision |
|---|---|
| Overall approach | Mobile-first redesign of key pages (not polish, not separate view) |
| Code editor on mobile | Plain `<textarea>` — no rich editor, native keyboard |
| Dashboard card actions | Whole card tappable → detail page; icon buttons hidden on mobile |
| Git history per monitor | Out of scope — separate spec |

---

## Area 1: Dashboard Cards

**Problem:** Icon buttons (favorite, link, run) are 32×32px — below 48px WCAG minimum. Card not fully tappable.

**Solution:**
- Wrap entire card in `<a href="/monitors/{name}">` — whole card navigates to detail
- On mobile (≤700px): hide the three icon buttons (`.monitor-actions`) entirely
- On desktop: buttons remain visible as today
- Card body shows: LED status dot, monitor name, schedule, last value (if metric), last run time
- No swipe/long-press — keep it simple

**Files:** `app/templates/dashboard.html`

---

## Area 2: Monitor Detail Page

**Problem:** 5 topbar buttons overflow on mobile. Metric strip (5 cols) too dense. Chart column stacks below long runs list.

**Solution:**

### Topbar
- Keep: breadcrumb, monitor name, status LED
- On mobile (≤700px): remove Open, Edit, Pause, Run now, Delete buttons from topbar entirely
- Replace with a **sticky bottom action bar** (above the mobile tab bar): `[▶ Run now] [Pause] [⋯ More]`
- "More" expands to show Edit and Delete (less frequently used)

### Metric strip
- On mobile (≤700px): show only 2 metrics in a row — **Status** and **Last value**
- Remaining metrics (success rate, total runs, avg duration) hidden on mobile — not shown
- Schedule shown in topbar subtitle (already is)

### Chart
- Full-width above the runs list on mobile (already stacks at 1100px)
- Range selector buttons (48h/30d/90d/1y) stay — they're small enough

### Runs list
- Run row grid on mobile: `LED | time + value (stacked) | chip | chevron` — 2-line layout instead of 4-column grid
- Remove fixed column widths, use flex with `flex-wrap`
- Tap target: entire row remains tappable (add `role="button"` + `tabindex="0"` for a11y)

**Files:** `app/templates/monitor_detail.html`

---

## Area 3: Monitor Editor

**Problem:** Rich editor fixed at 560px height + horizontal scroll forced. Helpers drawer 320px fixed width = full screen on 320px device.

**Solution:**

### Form layout
- Already collapses to 1-col at 900px — keep
- Ensure all inputs have 48px minimum height

### Code editor
- On desktop (>700px): existing rich editor (CodeMirror or styled textarea with mono font) unchanged
- On mobile (≤700px): hide rich editor, show plain `<textarea>` with same `name` attribute
  - `height: auto; min-height: 200px; max-height: 60vh; overflow-y: auto`
  - `font-family: monospace; font-size: 13px; line-height: 1.5`
  - Both elements exist in DOM; CSS `display:none` toggles between them at breakpoint
  - Form submits same field name regardless

### Helpers drawer
- On desktop: existing side-panel behavior unchanged
- On mobile (≤700px): drawer becomes `position: fixed; bottom: 0; left: 0; right: 0; height: 70vh` — slides up from bottom (CSS transform)
- Backdrop overlay covers rest of screen
- "Helpers ↑" button at bottom of editor form triggers it
- Drawer has a drag handle / close button at top

### Save button
- Sticky at bottom of page on mobile (above keyboard, within form flow)

**Files:** `app/templates/monitor_editor.html`

---

## Area 4: Tags Page

**Problem:** `grid-template-columns: repeat(3, 1fr)` hardcoded with no mobile breakpoint.

**Solution:**
- Add `@media (max-width: 700px)` → `grid-template-columns: 1fr`
- Tag row: name left, monitor count right, full-width tappable
- One-line fix

**Files:** `app/templates/tags.html`

---

## Area 5: Tap Targets (Global)

**Problem:** Mobile tab icons 36×28px. All icon `.btn.icon` buttons 32×32px. Below 48×48px WCAG minimum.

**Solution:**
- Mobile tabs: increase `.mobile-tab` padding so touch area ≥ 48px. `.mobile-tab-icon` min-height: 32px, outer area padded to 48px total.
- Icon buttons in general: add `min-width: 48px; min-height: 48px` to `.btn.icon` on mobile via breakpoint, or add `padding: 12px` so total ≥ 48px
- Run row: add `role="button" tabindex="0"` to `.run-row-main` divs for keyboard nav / a11y

**Files:** `app/templates/base.html`, `app/templates/monitor_detail.html`

---

## Area 6: Activity Filter on Mobile

**Problem:** Monitor name filter dropdown (`.mon-select-wrap`) hidden at ≤700px with no alternative.

**Solution:**
- Replace the styled custom dropdown with a native `<select>` element on mobile
- Show it inline above the activity list at ≤700px (same position as the topbar filter on desktop)
- Native `<select>` is already mobile-friendly (OS picker)
- Same filter logic — just a different trigger element

**Files:** `app/templates/activity.html`

---

## Area 7: Settings Page (Minor)

**Problem:** Log console fixed at 320px height takes half the screen.

**Solution:**
- On mobile: `max-height: 40vh` with scroll — no fixed height
- Tags list `.tag-row` delete button: ensure 48px tap target

**Files:** `app/templates/settings.html`

---

## What Does NOT Change

- Desktop layout, sidebar, all desktop breakpoints
- Dashboard stat strip (already responsive)
- Monitor detail chart (already full-width on mobile)
- Tag detail page (already responsive)
- Chart range selector on detail page
- All Python backend, API routes, data model

---

## Out of Scope (Separate Spec)

- Git history browser per monitor (revert/checkout to commit)

---

## Implementation Order

1. **Tags page breakpoint** — 1 CSS line, zero risk (Area 4)
2. **Tap targets** — CSS only, base.html + detail (Area 5)
3. **Activity filter** — swap dropdown for native select on mobile (Area 6)
4. **Settings log console** — max-height tweak (Area 7)
5. **Dashboard cards** — whole-card link, hide action buttons on mobile (Area 1)
6. **Monitor detail** — sticky action bar, metric strip, run row flex layout (Area 2)
7. **Monitor editor** — textarea swap, helpers bottom sheet (Area 3)

Start with lowest-risk changes; editor last as most complex.

---

## Testing Checklist

- [ ] All pages at 390px (iPhone 14) — no horizontal scroll
- [ ] All pages at 320px (smallest common) — no overflow
- [ ] All tap targets ≥ 48px verified by inspection
- [ ] Dashboard card tap navigates to detail
- [ ] Detail page sticky action bar: Run now, Pause, Delete all work
- [ ] Editor: plain textarea submits correctly, saves monitor
- [ ] Helpers bottom sheet opens/closes on mobile
- [ ] Tags page 1-col on mobile
- [ ] Activity filter native select filters correctly
- [ ] Desktop (1200px+): zero regressions — all existing layout unchanged
