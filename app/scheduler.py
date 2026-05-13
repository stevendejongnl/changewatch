import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import Database
from app.helpers import Monitor
from app.runner import Runner


def discover_monitors(monitors_dir: Path) -> list[Monitor]:
    if not monitors_dir.is_dir():
        return []
    monitors = []
    for path in sorted(monitors_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue
        monitor = getattr(module, "monitor", None)
        if isinstance(monitor, Monitor):
            monitors.append(monitor)
    return monitors


class Scheduler:
    def __init__(self, monitors_dir: Path, db: Database) -> None:
        self._monitors_dir = monitors_dir
        self._db = db
        self._scheduler = AsyncIOScheduler()
        self._monitors: list[Monitor] = []

    @property
    def running(self) -> bool:
        return self._scheduler.running

    async def start(self) -> None:
        self._monitors = discover_monitors(self._monitors_dir)
        runner = Runner(db=self._db, browser=None)
        for monitor in self._monitors:
            self._scheduler.add_job(
                runner.run,
                CronTrigger.from_crontab(monitor.schedule),
                args=[monitor],
                id=monitor.name,
                name=monitor.name,
                misfire_grace_time=60,
                replace_existing=True,
            )
        self._scheduler.start()

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        await asyncio.sleep(0)  # let event loop execute the deferred @run_in_event_loop _shutdown

    def list_jobs(self) -> list[dict[str, Any]]:
        return [{"name": job.name, "id": job.id} for job in self._scheduler.get_jobs()]

    async def trigger(self, monitor_name: str, browser: Any) -> None:
        monitor = next((m for m in self._monitors if m.name == monitor_name), None)
        if monitor is None:
            raise KeyError(f"No monitor named {monitor_name!r}")
        runner = Runner(db=self._db, browser=browser)
        await runner.run(monitor)
