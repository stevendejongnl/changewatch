import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.helpers import Monitor
    from app.scheduler import Scheduler

logger = logging.getLogger(__name__)

IMAP_ENV: dict[str, str] | None = None


class ImapWatcher:
    def __init__(
        self,
        monitors: list["Monitor"],
        scheduler: "Scheduler",
        browser: Any,
    ) -> None:
        self._monitors = monitors
        self._scheduler = scheduler
        self._browser = browser

    async def run(self) -> None:
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for m in self._monitors:
            if m.imap_idle:
                groups[(m.imap_idle.account, m.imap_idle.folder)].append(m)

        tasks = [
            asyncio.create_task(
                self._watch_folder(account, folder, mons),
                name=f"imap-idle-{account}-{folder}",
            )
            for (account, folder), mons in groups.items()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _watch_folder(
        self,
        account: str,
        folder: str,
        monitors: list,
    ) -> None:
        backoff = 1
        while True:
            try:
                await self._idle_loop(account, folder, monitors)
                backoff = 1  # pragma: no cover
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "IMAP watcher error for %s/%s: %s — retry in %ds",
                    account, folder, exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _idle_loop(
        self,
        account: str,
        folder: str,
        monitors: list,
    ) -> None:
        from app.helpers import ImapIdleConfig, imap_connect

        config = ImapIdleConfig(account=account, folder=folder, search=[])
        async with imap_connect(config, IMAP_ENV) as imap:
            has_idle = imap.has_capability("IDLE")
            logger.info("IMAP watcher connected to %s/%s (IDLE=%s)", account, folder, has_idle)

            if has_idle:
                await self._idle_wait(imap, monitors)
            else:
                await self._poll_wait(imap, monitors)

    async def _idle_wait(self, imap: Any, monitors: list) -> None:
        while True:
            await imap.idle_start(timeout=300)
            push = await imap.wait_server_push()
            await imap.idle_done()
            if any(b"EXISTS" in (line if isinstance(line, bytes) else str(line).encode()) for line in push):
                for m in monitors:
                    await self._scheduler.trigger(m.name, self._browser)

    async def _poll_wait(self, imap: Any, monitors: list) -> None:
        while True:
            await asyncio.sleep(60)
            await imap.noop()
            for m in monitors:
                await self._scheduler.trigger(m.name, self._browser)
