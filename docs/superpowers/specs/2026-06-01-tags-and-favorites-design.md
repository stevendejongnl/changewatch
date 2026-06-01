# Tags & Favorites Design

**Date:** 2026-06-01  
**Status:** Approved

## Summary

Add tag-based grouping and per-monitor favorites to changewatch. Tags are managed server-side in SQLite (decoupled from `.py` source files). Favorites replace the homepage monitor grid when any favorites exist, falling back to all monitors when none are set.

---

## 1. Data Model

### New `tags` table

```sql
CREATE TABLE tags (
    monitor_name TEXT NOT NULL,
    tag          TEXT NOT NULL,
    PRIMARY KEY (monitor_name, tag)
);
```

Tags are stored in the DB independently of monitor source files. They survive monitor edits and reloads.

### `monitor_config` extension

```sql
ALTER TABLE monitor_config ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0;
```

### New `Database` methods

| Method | Purpose |
|--------|---------|
| `set_tags(monitor_name, tags: list[str])` | Replace all tags for a monitor |
| `get_tags(monitor_name) -> list[str]` | Get tags for one monitor |
| `get_all_tags() -> list[dict]` | All distinct tags with monitor counts |
| `rename_tag(old, new)` | Rename tag across all monitors |
| `delete_tag(tag)` | Remove tag from all monitors |
| `set_favorite(monitor_name, favorite: bool)` | Toggle favorite |

`get_all_monitor_states` updated to JOIN tags and favorite from `monitor_config`.

---

## 2. Backend Routes

### Tag management API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/tags` | All distinct tags with monitor counts |
| `POST` | `/api/tags` | Create tag in vocabulary `{"tag": "electronics"}` |
| `DELETE` | `/api/tags/{tag}` | Delete tag and remove from all monitors |
| `PUT` | `/api/tags/{tag}` | Rename tag `{"new_tag": "gadgets"}` |
| `GET` | `/api/monitors/{name}/tags` | Get tags for a monitor |
| `POST` | `/api/monitors/{name}/tags` | Set tags for a monitor `{"tags": [...]}` |
| `POST` | `/monitors/{name}/favorite` | Toggle favorite (204) |

### Page routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/tags` | Tag overview: all tags with monitor counts |
| `GET` | `/tags/{tag}` | Tag detail: monitor grid filtered to that tag |

---

## 3. Dashboard (Homepage) Behavior

- **Has favorites:** show only favorited monitors. Topbar subtitle: "N favorites · live". Status filter buttons still work within the favorites set.
- **No favorites:** fall back to all monitors (same as today — no regression for fresh installs).
- **Star icon** on each monitor card: filled = favorited, empty = not. Toggles via `POST /monitors/{name}/favorite`, updates in-place without page reload.
- Star icon also present on tag detail pages (`/tags/{tag}`).

---

## 4. Monitor Editor — Tags Field

- New "Tags" multi-select field in `monitor_editor.html`, above the code editor.
- Available tags loaded from `GET /api/tags` and shown as checkboxable chips.
- Free-text entry allowed — typing a new tag and confirming creates it on the fly.
- On save, frontend calls `POST /api/monitors/{name}/tags` with selected tags (separate request from source save).
- Works on both new monitor creation and edit flows.

---

## 5. Settings Page — Tag Management

New "Tags" section in `/settings`:

- List of all tags showing name and monitor count.
- "New tag" input + Add button to pre-create tags.
- Inline rename: click tag name → editable field → confirm → calls `PUT /api/tags/{tag}`.
- Delete button per tag with confirmation dialog: "This will remove the tag from N monitors."

---

## 6. Navigation

- New "Tags" nav item in `base.html` sidebar/topbar linking to `/tags`.
- `/tags` overview: tag cards showing name + monitor count, clicking through to `/tags/{tag}`.
- `/tags/{tag}` detail: same monitor card design as dashboard (run/pause/favorite actions all present). Header shows tag name with back link to `/tags`.

---

## Out of Scope

- Tags in `.py` source files (tags live in DB only).
- Tag-based notifications or scheduling.
- Bulk-favorite actions.
