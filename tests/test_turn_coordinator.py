import threading
import time

from core.turn_coordinator import ChatTurnCoordinator


def test_shutdown_discards_delayed_work_without_superseded_callback() -> None:
    coordinator = ChatTurnCoordinator(default_delay_seconds=0.05)
    called = threading.Event()
    superseded = threading.Event()

    coordinator.submit(
        chat_id="chat-1",
        callback=lambda handle: called.set(),
        on_superseded=superseded.set,
    )
    coordinator.shutdown()
    time.sleep(0.1)

    assert not called.is_set()
    assert not superseded.is_set()


def test_new_lifecycle_accepts_new_work_after_shutdown() -> None:
    coordinator = ChatTurnCoordinator(default_delay_seconds=0)
    coordinator.shutdown()
    called = threading.Event()

    coordinator.submit(chat_id="chat-1", callback=lambda handle: called.set())

    assert called.wait(timeout=1)
