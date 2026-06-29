import asyncio
import importlib.util
import logging
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
    from app.influx import InfluxClient


_discover_logger = logging.getLogger("changewatch.discover")


def discover_monitors(monitors_dir: Path) -> tuple[list[Monitor], dict[str, str]]:
    """Return (monitors, broken) where broken maps filename → error string."""
    if not monitors_dir.is_dir():
        return [], {}
    monitors = []
    broken: dict[str, str] = {}
    for path in sorted(monitors_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            _discover_logger.warning("skipping %s: failed to import: %s", path.name, exc)
            broken[path.name] = str(exc)
            continue
        monitor = getattr(module, "monitor", None)
        if isinstance(monitor, Monitor):
            product_name = getattr(module, "_PRODUCT_NAME", None)
            if product_name:
                monitor.display_name = product_name
            url_override = getattr(module, "_URL", None)
            if not monitor.display_url:
                monitor.display_url = url_override if url_override else (monitor.url or "")
            monitors.append(monitor)
    if len(monitors) > 1:
        monitors = [m for m in monitors if m.name != "example_price"]
    return monitors, broken


class Scheduler:
    def __init__(
        self,
        monitors_dir: Path,
        db: Database,
        apprise: Optional["AppriseClient"] = None,
        influx: Optional["InfluxClient"] = None,
        timezone: str = "UTC",
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._monitors_dir = monitors_dir
        self._db = db
        self._apprise = apprise
        self._influx = influx
        self._timezone = timezone
        self._event_bus = event_bus
        self._browser: Any = None
        self._scheduler = AsyncIOScheduler()
        self._monitors: list[Monitor] = []
        self._broken: dict[str, str] = {}

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
        self._monitors, self._broken = discover_monitors(self._monitors_dir)
        active_names = {m.name for m in self._monitors}
        existing_files = {p.stem for p in self._monitors_dir.glob("*.py")} if self._monitors_dir.is_dir() else set()
        for row in await self._db.get_all_monitor_states():
            name = row["monitor_name"]
            if name not in active_names and name not in existing_files:
                await self._db.delete_monitor(name)
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise, influx=self._influx, event_bus=self._event_bus)
        for monitor in self._monitors:
            if monitor.schedule is None:
                continue
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
        new_monitors, new_broken = discover_monitors(self._monitors_dir)
        new_ids = {m.name for m in new_monitors}
        old_ids = {job.id for job in self._scheduler.get_jobs() if not job.id.startswith("__")}
        existing_files = {p.stem for p in self._monitors_dir.glob("*.py")} if self._monitors_dir.is_dir() else set()
        runner = Runner(db=self._db, browser=self._browser, apprise=self._apprise, influx=self._influx, event_bus=self._event_bus)
        for job_id in old_ids - new_ids:
            self._scheduler.remove_job(job_id)
            if job_id not in existing_files:
                await self._db.delete_monitor(job_id)
        for monitor in new_monitors:
            if monitor.schedule is None:
                continue
            self._scheduler.add_job(
                self._make_job_fn(runner, monitor),
                CronTrigger.from_crontab(monitor.schedule, timezone=self._timezone),
                id=monitor.name,
                name=monitor.name,
                misfire_grace_time=60,
                replace_existing=True,
            )
        self._monitors = new_monitors
        self._broken = new_broken

    async def trigger(self, monitor_name: str, browser: Any) -> None:
        all_monitors = discover_monitors(self._monitors_dir)
        monitor = next((m for m in all_monitors if m.name == monitor_name), None)
        if monitor is None:
            raise KeyError(f"No monitor named {monitor_name!r}")
        runner = Runner(db=self._db, browser=browser, apprise=self._apprise, influx=self._influx, event_bus=self._event_bus)
        await runner.run(monitor)
