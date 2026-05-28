# Design: Example Monitor Hiding + Git-Backed Monitor Source

## Context

Two independent improvements to changewatch:

1. `example_price.py` currently appears on the dashboard alongside real monitors, and will also attempt to run (scraping `https://example.com/product`) even when real monitors are configured. It should only be visible when no other monitors exist.

2. Users want to store their private monitors in a separate Gitea repository (`git.madebysteven.nl`) rather than in the app repo. The service should clone that repo on startup, sync it periodically, and expose a manual sync button on the dashboard.

---

## Feature 1: Hide example_price.py

### Behaviour

After `discover_monitors` collects all monitors from `MONITORS_DIR`:

- If more than one monitor is found, remove the one named `example_price` from the returned list.
- If `example_price` is the only monitor, include it (so new installs aren't empty).

The filtered list is used by both the Scheduler (determines which jobs are scheduled) and the dashboard (determines what is displayed). The example monitor will not run and will not appear once any real monitor exists.

### Convention

`example_price` is hardcoded as the name to suppress. No filename convention or `Monitor` flag is introduced.

### Change surface

- `app/scheduler.py` — filter applied inside or directly after `discover_monitors`
- No changes to `app/main.py`, `app/db.py`, or templates

---

## Feature 2: Git-Backed Monitor Source

### New file: `app/git_sync.py`

```python
class GitSync:
    def __init__(self, repo_url: str, clone_path: Path, token: str) -> None: ...
    async def sync(self) -> None: ...
```

`sync()` behaviour:
- Injects the token into the URL at call time: `https://<token>@<host>/path.git`. The token is never written to the clone's git config.
- If `clone_path` does not exist: runs `git clone <authenticated_url> <clone_path>`.
- If `clone_path` exists: runs `git pull` inside it.
- Runs git as a subprocess (`asyncio.create_subprocess_exec`).
- Raises on non-zero exit (caller decides how to surface the error).

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MONITORS_REPO_URL` | No | — | Gitea repo URL, e.g. `https://git.madebysteven.nl/steven/monitors.git` |
| `MONITORS_REPO_TOKEN` | If URL set | — | HTTP token for authentication |
| `MONITORS_REPO_SYNC_INTERVAL` | No | `0 * * * *` | Cron string for periodic sync (default: hourly) |

When `MONITORS_REPO_URL` is not set, git sync is disabled and the service behaves as before.

### MONITORS_DIR when git sync is enabled

The clone path defaults to `Path(DB_PATH).parent / "monitors-repo"` (i.e. `/data/monitors-repo` on the default setup). When `MONITORS_REPO_URL` is set, this clone path takes precedence over `MONITORS_DIR` — the git repo is authoritative. `MONITORS_DIR` is only used when git sync is not configured. The clone sits on the same persistent volume as the SQLite database — no additional volume required.

### Scheduler changes

`Scheduler` gains a `reload()` method:
- Re-runs `discover_monitors`.
- For each discovered monitor: `add_job(..., replace_existing=True)`.
- Removes jobs whose IDs are no longer in the discovered set.

### Lifespan wiring (`app/main.py`)

On startup, if `MONITORS_REPO_URL` is set:
1. Instantiate `GitSync`.
2. `await git_sync.sync()` — clone or pull.
3. `MONITORS_DIR` is already pointing at the clone path.
4. `await scheduler.reload()` — picks up the synced monitors.
5. Add an APScheduler cron job: `git_sync.sync()` then `scheduler.reload()` on `MONITORS_REPO_SYNC_INTERVAL`.

`GitSync` instance is held as a module-level singleton alongside `_db`, `_scheduler`, `_browser`.

### New API endpoint

```
POST /sync
```

- If git sync is not configured: returns 503 `{"error": "git sync not configured"}`.
- If configured: calls `await git_sync.sync()` then `await scheduler.reload()`, returns 202 `{"synced": true}`.
- Errors from `git_sync.sync()` (e.g. auth failure, network error) propagate as 500.

### Dashboard button

A "Sync monitors" button in `dashboard.html` (header area, near any global controls). On click:

1. POSTs to `/sync`.
2. Shows a brief "Syncing…" disabled state.
3. On success (202): reloads the page.
4. On error: shows an inline error message without reloading.

Button is only rendered when `MONITORS_REPO_URL` is configured (template receives a boolean `git_sync_enabled` from the dashboard endpoint).

---

## Testing

- `app/git_sync_test.py` — unit tests using a real temp git repo (no network): init a bare repo, clone it locally, verify `sync()` performs clone on first call and pull on subsequent calls.
- `app/scheduler_test.py` — extend with tests for `reload()`: add a monitor, reload, verify job added; remove a monitor file, reload, verify job removed.
- `app/main_test.py` — test `POST /sync` returns 503 when not configured; mock `GitSync.sync` to test the 202 path.
- Example-hiding: extend existing scheduler tests to verify `example_price` is excluded when other monitors are present.
- `--cov-fail-under=100` continues to apply; `# pragma: no cover` for the lifespan git-sync wiring that touches real subprocesses.
