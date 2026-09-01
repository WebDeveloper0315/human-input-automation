"""Real-time clock adapter."""

from __future__ import annotations

import threading
import time

from ..ports.clock import CancelToken


class SystemClock:
    """Wall-clock implementation of :class:`~..ports.clock.Clock`.

    Sleeping is implemented with an event wait rather than ``time.sleep`` so a
    stop request interrupts it immediately - that is what keeps the emergency
    stop responsive during long delays.
    """

    def __init__(self) -> None:
        self._idle = threading.Event()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep_ms(self, milliseconds: float, cancel: CancelToken | None = None) -> bool:
        if milliseconds <= 0:
            return bool(cancel and cancel.is_stop_requested())
        seconds = milliseconds / 1000.0
        if cancel is None:
            # No cancellation source: wait on a never-set event so the sleep is
            # still interruptible by process-level signals.
            self._idle.wait(seconds)
            return False
        return cancel.wait_for_stop(seconds)
