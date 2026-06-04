import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress


logger = logging.getLogger(__name__)


class ProductsXmlAutoImportRunner:
    def __init__(
        self,
        *,
        import_once: Callable[[], object],
        interval_seconds: int,
        run_on_startup: bool,
    ) -> None:
        self.import_once = import_once
        self.interval_seconds = max(60, interval_seconds)
        self.run_on_startup = run_on_startup
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="products-xml-auto-import")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        if self.run_on_startup:
            await self._import_safely()

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                await self._import_safely()

    async def _import_safely(self) -> None:
        try:
            result = await asyncio.to_thread(self.import_once)
        except Exception:
            logger.exception("Remote products XML auto-import failed")
            return

        status = getattr(result, "status", "unknown")
        error_text = getattr(result, "error_text", None)
        if status == "completed":
            logger.info("Remote products XML auto-import completed")
        else:
            logger.error("Remote products XML auto-import finished with status=%s error=%s", status, error_text)
