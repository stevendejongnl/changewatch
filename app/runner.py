import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from app.db import Database
from app.helpers import Monitor

if TYPE_CHECKING:  # pragma: no cover
    from app.apprise_client import AppriseClient
    from app.influx import InfluxClient


@dataclass
class RunContext:
    monitor_name: str
    logger: logging.Logger
    db: Database
    apprise: Optional["AppriseClient"] = None
    influx: Optional["InfluxClient"] = None


class Runner:
    def __init__(
        self,
        db: Database,
        browser: Any,
        apprise: Optional["AppriseClient"] = None,
        influx: Optional["InfluxClient"] = None,
    ) -> None:
        self._db = db
        self._browser = browser
        self._apprise = apprise
        self._influx = influx

    async def run(self, monitor: Monitor) -> None:
        logger = logging.getLogger(f"changewatch.{monitor.name}")
        ctx = RunContext(
            monitor_name=monitor.name,
            logger=logger,
            db=self._db,
            apprise=self._apprise,
            influx=self._influx,
        )
        start = time.monotonic()
        page = None
        try:
            context = await self._browser.new_context()
            page = await context.new_page()
            await monitor.fn(page, ctx)
            duration_ms = int((time.monotonic() - start) * 1000)
            last_value = await self._db.get_last_value(monitor.name)
            await self._db.record_run(
                monitor_name=monitor.name,
                status="ok",
                last_value=last_value,
                error=None,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._db.record_run(
                monitor_name=monitor.name,
                status="error",
                last_value=None,
                error=str(exc),
                duration_ms=duration_ms,
            )
        finally:
            if page is not None:
                await page.close()
                await page.context.close()
