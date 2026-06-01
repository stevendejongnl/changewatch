import os
import aiosqlite
from typing import Optional


class Database:
    def __init__(self, path: str = "/data/state.db"):
        self._path = path
        self.conn: aiosqlite.Connection

    async def init(self) -> None:
        self.conn = await aiosqlite.connect(self._path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS state (
                monitor_name TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_name TEXT NOT NULL,
                status TEXT NOT NULL,
                last_value TEXT,
                error TEXT,
                duration_ms INTEGER NOT NULL,
                ran_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS run_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                logged_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_run_logs_run_id ON run_logs(run_id);
            CREATE TABLE IF NOT EXISTS monitor_config (
                monitor_name TEXT PRIMARY KEY,
                paused       INTEGER NOT NULL DEFAULT 0,
                changed_at   TEXT
            );
        """)
        await self.conn.commit()

    async def close(self) -> None:
        await self.conn.close()

    async def get_stats(self) -> dict:
        result: dict = {}
        for table in ("runs", "run_logs", "state", "monitor_config"):
            async with self.conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:  # noqa: S608
                row = await cur.fetchone()
            result[table] = row[0]
        async with self.conn.execute("SELECT MIN(ran_at), MAX(ran_at) FROM runs") as cur:
            row = await cur.fetchone()
        result["oldest_run"] = row[0]
        result["newest_run"] = row[1]
        try:
            result["db_size_bytes"] = os.path.getsize(self._path)
        except OSError:
            result["db_size_bytes"] = 0
        return result

    async def get_last_value(self, monitor_name: str) -> Optional[str]:
        async with self.conn.execute(
            "SELECT value FROM state WHERE monitor_name = ?", (monitor_name,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_value(self, monitor_name: str, value: str) -> None:
        await self.conn.execute(
            """INSERT INTO state (monitor_name, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(monitor_name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (monitor_name, value),
        )
        await self.conn.commit()

    async def record_run(
        self,
        monitor_name: str,
        status: str,
        last_value: Optional[str],
        error: Optional[str],
        duration_ms: int,
    ) -> int:
        async with self.conn.execute(
            """INSERT INTO runs (monitor_name, status, last_value, error, duration_ms)
               VALUES (?, ?, ?, ?, ?)""",
            (monitor_name, status, last_value, error, duration_ms),
        ) as cur:
            row_id = cur.lastrowid
        await self.conn.commit()
        return row_id

    async def write_run_logs(self, run_id: int, lines: list[tuple[str, str]]) -> None:
        if not lines:
            return
        await self.conn.executemany(
            "INSERT INTO run_logs (run_id, level, message) VALUES (?, ?, ?)",
            [(run_id, level, msg) for level, msg in lines],
        )
        await self.conn.commit()

    async def get_run_logs(self, run_id: int) -> list[dict]:
        async with self.conn.execute(
            "SELECT level, message, logged_at FROM run_logs WHERE run_id = ? ORDER BY id",
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_avg_duration(self, monitor_name: str) -> Optional[int]:
        async with self.conn.execute(
            "SELECT ROUND(AVG(duration_ms)) AS avg FROM runs WHERE monitor_name = ?",
            (monitor_name,),
        ) as cur:
            row = await cur.fetchone()
        return int(row["avg"]) if row and row["avg"] is not None else None

    async def get_runs_with_logs(self, monitor_name: str, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM runs WHERE monitor_name = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (monitor_name, limit, offset),
        ) as cur:
            run_rows = await cur.fetchall()
        runs = []
        for row in run_rows:
            run = dict(row)
            run["logs"] = await self.get_run_logs(run["id"])
            runs.append(run)
        return runs

    async def get_all_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_recent_runs(self, monitor_name: str, limit: int = 10) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM runs WHERE monitor_name = ? ORDER BY id DESC LIMIT ?",
            (monitor_name, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete_monitor(self, monitor_name: str) -> None:
        async with self.conn.execute(
            "SELECT id FROM runs WHERE monitor_name = ?", (monitor_name,)
        ) as cur:
            run_ids = [row[0] for row in await cur.fetchall()]
        if run_ids:
            placeholders = ",".join("?" * len(run_ids))
            await self.conn.execute(f"DELETE FROM run_logs WHERE run_id IN ({placeholders})", run_ids)
        await self.conn.execute("DELETE FROM runs WHERE monitor_name = ?", (monitor_name,))
        await self.conn.execute("DELETE FROM state WHERE monitor_name = ?", (monitor_name,))
        await self.conn.execute("DELETE FROM monitor_config WHERE monitor_name = ?", (monitor_name,))
        await self.conn.commit()

    async def set_paused(self, monitor_name: str, paused: bool) -> None:
        await self.conn.execute(
            """INSERT INTO monitor_config (monitor_name, paused)
               VALUES (?, ?)
               ON CONFLICT(monitor_name) DO UPDATE SET paused=excluded.paused""",
            (monitor_name, 1 if paused else 0),
        )
        await self.conn.commit()

    async def set_changed_at(self, monitor_name: str) -> None:
        await self.conn.execute(
            """INSERT INTO monitor_config (monitor_name, changed_at)
               VALUES (?, datetime('now'))
               ON CONFLICT(monitor_name) DO UPDATE SET changed_at=datetime('now')""",
            (monitor_name,),
        )
        await self.conn.commit()

    async def get_config(self, monitor_name: str) -> dict:
        async with self.conn.execute(
            "SELECT monitor_name, paused, changed_at FROM monitor_config WHERE monitor_name = ?",
            (monitor_name,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return {"monitor_name": monitor_name, "paused": 0, "changed_at": None}
        return dict(row)

    async def get_all_configs(self) -> dict[str, dict]:
        async with self.conn.execute(
            "SELECT monitor_name, paused, changed_at FROM monitor_config"
        ) as cur:
            rows = await cur.fetchall()
        return {row["monitor_name"]: dict(row) for row in rows}

    async def get_all_monitor_states(self) -> list[dict]:
        async with self.conn.execute(
            """SELECT r.monitor_name, r.status, r.last_value, r.error, r.duration_ms, r.ran_at,
                      COALESCE(c.paused, 0) AS paused, c.changed_at
               FROM runs r
               INNER JOIN (
                   SELECT monitor_name, MAX(ran_at) AS latest
                   FROM runs GROUP BY monitor_name
               ) latest ON r.monitor_name = latest.monitor_name AND r.ran_at = latest.latest
               LEFT JOIN monitor_config c ON r.monitor_name = c.monitor_name"""
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
