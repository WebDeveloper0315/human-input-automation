"""Time and cancellation ports.

Time is injected rather than called directly so that tests can run a whole plan
in microseconds while still asserting on the delays that *would* have been
applied.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CancelToken(Protocol):
    """Anything that can report and wait for a stop request."""

    def is_stop_requested(self) -> bool:
        """True once a stop (or emergency stop) has been requested."""
        ...

    def wait_for_stop(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds; return True if a stop arrived."""
        ...


@runtime_checkable
class Clock(Protocol):
    """Monotonic time plus an interruptible sleep."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin; only differences are meaningful."""
        ...

    def sleep_ms(self, milliseconds: float, cancel: CancelToken | None = None) -> bool:
        """Sleep for ``milliseconds``.

        Implementations must return as soon as ``cancel`` reports a stop.
        Returns ``True`` if the sleep was cut short by a stop request.
        """
        ...
