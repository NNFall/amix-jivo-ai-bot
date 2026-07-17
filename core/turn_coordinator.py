from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TurnHandle:
    chat_id: str
    generation: int
    _coordinator: ChatTurnCoordinator

    def is_current(self) -> bool:
        return self._coordinator.is_current(self.chat_id, self.generation)


class ChatTurnCoordinator:
    """In-process per-chat debounce/supersede coordinator.

    This does not cancel an already running provider HTTP request. It marks that
    turn as stale so its result is not stored/sent, then lets the newest turn
    answer using all currently un-answered user messages in history.
    """

    def __init__(self, *, default_delay_seconds: float = 1.2) -> None:
        self.default_delay_seconds = default_delay_seconds
        self._lock = threading.Lock()
        self._generations: dict[str, int] = {}

    def submit(
        self,
        *,
        chat_id: str,
        callback: Callable[[TurnHandle], None],
        on_superseded: Callable[[], None] | None = None,
        delay_seconds: float | None = None,
    ) -> TurnHandle:
        with self._lock:
            generation = self._generations.get(chat_id, 0) + 1
            self._generations[chat_id] = generation

        handle = TurnHandle(chat_id=chat_id, generation=generation, _coordinator=self)
        actual_delay = self.default_delay_seconds if delay_seconds is None else delay_seconds
        thread = threading.Thread(
            target=self._run,
            args=(handle, callback, on_superseded, actual_delay),
            daemon=True,
            name=f"chat-turn-{chat_id}-{generation}",
        )
        thread.start()
        return handle

    def is_current(self, chat_id: str, generation: int) -> bool:
        with self._lock:
            return self._generations.get(chat_id) == generation

    def cancel(self, chat_id: str) -> None:
        """Invalidate every queued or running turn for a terminal chat."""
        with self._lock:
            self._generations[chat_id] = self._generations.get(chat_id, 0) + 1

    def _run(
        self,
        handle: TurnHandle,
        callback: Callable[[TurnHandle], None],
        on_superseded: Callable[[], None] | None,
        delay_seconds: float,
    ) -> None:
        if delay_seconds > 0:
            time.sleep(delay_seconds)

        if not handle.is_current():
            logger.info(
                "Skipping superseded chat turn before processing chat_id=%s generation=%s",
                handle.chat_id,
                handle.generation,
            )
            if on_superseded is not None:
                try:
                    on_superseded()
                except Exception:
                    logger.exception(
                        "Failed to finalize superseded chat turn chat_id=%s generation=%s",
                        handle.chat_id,
                        handle.generation,
                    )
            return

        try:
            callback(handle)
        except Exception:
            logger.exception(
                "Chat turn callback failed chat_id=%s generation=%s",
                handle.chat_id,
                handle.generation,
            )


GLOBAL_TURN_COORDINATOR = ChatTurnCoordinator()
