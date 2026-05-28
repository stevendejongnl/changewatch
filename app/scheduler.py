import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import Database
from app.events import EventBus
from app.helpers import Monitor
from app.runner import Runner

if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient


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
    if len(monitors) > 1:
        monitors = [m for m in monitors if m.name != "example_price"]
    return monitors


class Scheduler:
    def __init__(
        self,
        monitors_dir: Path,
        db: Database,
        apprise: Optional["AppriseClient"] = None,
        timezone: str = "UTC",
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._monitors_dir = monitors_dir
        self._db = db
        self._apprise = apprise
        self._timezone = timezone
        self._event_bus = event_bus
        self._browser: Any = None
        self._scheduler = AsyncIOScheduler()
        self._monitors: list[Monitor] = []

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def _make_job_fn(self, runner: Runner, monitor: Monitor):
        async def _run() -> None:
            config = await self._db.get_config(monitor.name)
            if config.get("paused"):
                return
            await runner.run(monitor)
        return _run

    async def start(self, browser: Any = None) -> None:
        self._browser = browser
        self._monitors = discover_monitors(self._monitors_dir)
        active_names = {m.name for m in self._monitors}
        for row in await self._db.get_all_monitor_states():
            if row["monitor_name"] not in active_names:
                await self._db.delete_monitor(row["monitor_name"])
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise, event_bus=self._event_bus)
        for monitor in self._monitors:
            self._scheduler.add_job(
                self._make_job_fn(runner, monitor),
                CronTrigger.from_crontab(monitor.schedule, timezone=self._timezone),
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

    async def reload(self) -> None:
        new_monitors = discover_monitors(self._monitors_dir)
        new_ids = {m.name for m in new_monitors}
        old_ids = {job.id for job in self._scheduler.get_jobs() if not job.id.startswith("__")}
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise, event_bus=self._event_bus)
        for job_id in old_ids - new_ids:
            self._scheduler.remove_job(job_id)
            await self._db.delete_monitor(job_id)
        for monitor in new_monitors:
            self._scheduler.add_job(
                self._make_job_fn(runner, monitor),
                CronTrigger.from_crontab(monitor.schedule, timezone=self._timezone),
                id=monitor.name,
                name=monitor.name,
                misfire_grace_time=60,
                replace_existing=True,
            )
        self._monitors = new_monitors

    async def trigger(self, monitor_name: str, browser: Any) -> None:
        all_monitors = discover_monitors(self._monitors_dir)
        monitor = next((m for m in all_monitors if m.name == monitor_name), None)
        if monitor is None:
            raise KeyError(f"No monitor named {monitor_name!r}")
        runner = Runner(db=self._db, browser=browser, apprise=self._apprise, event_bus=self._event_bus)
        await runner.run(monitor)
