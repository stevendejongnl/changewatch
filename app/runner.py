import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from app.db import Database
from app.helpers import Monitor, notify

if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.events import EventBus
    from app.influx import InfluxClient


@dataclass
class RunContext:
    monitor_name: str
    logger: logging.Logger
    db: Database
    apprise: Optional["AppriseClient"] = None
    influx: Optional["InfluxClient"] = None


class _RunLogBuffer(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((record.levelname, record.getMessage()))


class Runner:
    def __init__(
        self,
        db: Database,
        browser: Any,
        apprise: Optional["AppriseClient"] = None,
        influx: Optional["InfluxClient"] = None,
        event_bus: Optional["EventBus"] = None,
    ) -> None:
        self._db = db
        self._browser = browser
        self._apprise = apprise
        self._influx = influx
        self._event_bus = event_bus

    async def run(self, monitor: Monitor, dry_run: bool = False) -> list[tuple[str, str]]:
        logger = logging.getLogger(f"changewatch.{monitor.name}.{uuid.uuid4().hex[:8]}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        ctx = RunContext(
            monitor_name=monitor.name,
            logger=logger,
            db=self._db,
            apprise=None if dry_run else self._apprise,
            influx=None if dry_run else self._influx,
        )
        log_buffer = _RunLogBuffer()
        log_buffer.setLevel(logging.DEBUG)
        logger.addHandler(log_buffer)
        start = time.monotonic()
        page = None
        try:
            context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            prev_value = await self._db.get_last_value(monitor.name)
            await monitor.fn(page, ctx)
            if dry_run:
                return list(log_buffer.lines)
            duration_ms = int((time.monotonic() - start) * 1000)
            last_value = await self._db.get_last_value(monitor.name)
            status = "changed" if prev_value is not None and last_value != prev_value else "ok"
            if status == "changed":
                await self._db.set_changed_at(monitor.name)
            run_id = await self._db.record_run(
                monitor_name=monitor.name,
                status=status,
                last_value=last_value,
                error=None,
                duration_ms=duration_ms,
            )
            await self._db.write_run_logs(run_id, log_buffer.lines)
            if self._event_bus is not None:
                await self._event_bus.publish({
                    "event": "run",
                    "monitor_name": monitor.name,
                    "status": status,
                    "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "last_value": last_value,
                    "duration_ms": duration_ms,
                    "error": None,
                })
        except Exception as exc:
            if dry_run:
                log_buffer.lines.append(("ERROR", str(exc)))
                return list(log_buffer.lines)
            duration_ms = int((time.monotonic() - start) * 1000)
            run_id = await self._db.record_run(
                monitor_name=monitor.name,
                status="error",
                last_value=None,
                error=str(exc),
                duration_ms=duration_ms,
            )
            await self._db.write_run_logs(run_id, log_buffer.lines)
            if self._event_bus is not None:
                await self._event_bus.publish({
                    "event": "run",
                    "monitor_name": monitor.name,
                    "status": "error",
                    "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "last_value": None,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                })
            if self._apprise is not None and monitor.notify_channels:
                # TODO(user): customize title/body — terse vs rich, every-failure vs transition-only
                try:
                    await notify(
                        self._apprise,
                        title=f"[changewatch] {monitor.name} failed",
                        body=str(exc),
                        tags=monitor.notify_channels,
                    )
                except Exception:
                    pass
        finally:
            logger.removeHandler(log_buffer)
            if page is not None:
                await page.close()
                await page.context.close()
        return []
