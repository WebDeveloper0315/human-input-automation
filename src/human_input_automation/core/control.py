"""Run control: start, pause, resume, stop and emergency stop.

The whole design goal here is that a stop request is honoured *immediately*,
even in the middle of a long delay. Every wait in the engine is implemented as
``Event.wait(timeout)`` on the stop event, so setting the event returns from the
wait at once instead of sleeping out the remaining time.

:class:`RunControl` is deliberately free of any UI or platform dependency: it is
plain ``threading`` and can be driven from a Qt slot, a global hotkey handler,
or a test.
"""

from __future__ import annotations

import threading
from enum import StrEnum

from .errors import Cancelled


class RunState(StrEnum):
    """Lifecycle state of a run, as observed from outside."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FINISHED = "finished"


class RunControl:
    """Thread-safe start/pause/resume/stop signalling for one run.

    Instances are reusable: :meth:`begin` resets the flags for a new run.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._emergency = threading.Event()
        #: Set while the run may proceed; cleared to pause.
        self._proceed = threading.Event()
        self._proceed.set()
        self._state = RunState.IDLE

    # -- lifecycle ---------------------------------------------------------
    def begin(self) -> None:
        """Mark the run as started.

        Deliberately does *not* clear the flags: a stop or pause requested in
        the window between "user clicked start" and "worker thread reached the
        engine" must still be honoured. Use :meth:`reset` to reuse a control.
        """
        with self._lock:
            if self._stop.is_set():
                self._state = RunState.STOPPING
            elif self.is_paused:
                self._state = RunState.PAUSED
            else:
                self._state = RunState.RUNNING

    def reset(self) -> None:
        """Clear every flag so this control can drive another run."""
        with self._lock:
            self._stop.clear()
            self._emergency.clear()
            self._proceed.set()
            self._state = RunState.IDLE

    def finish(self) -> None:
        """Mark the run as finished (called by the engine in its ``finally``)."""
        with self._lock:
            self._state = RunState.FINISHED
            self._proceed.set()

    # -- controls ----------------------------------------------------------
    def pause(self) -> None:
        """Pause before the next action. A pause never delays a stop request.

        Pausing before the run starts is allowed: the engine then stops at its
        first checkpoint instead of racing ahead.
        """
        with self._lock:
            if self._stop.is_set():
                return
            self._proceed.clear()
            if self._state in (RunState.IDLE, RunState.RUNNING):
                self._state = RunState.PAUSED

    def resume(self) -> None:
        """Resume a paused run."""
        with self._lock:
            if self._state is RunState.PAUSED:
                self._state = RunState.RUNNING
            self._proceed.set()


    def stop(self) -> None:
        """Request an orderly stop; also wakes a paused run."""
        with self._lock:
            if self._state in (RunState.IDLE, RunState.RUNNING, RunState.PAUSED):
                self._state = RunState.STOPPING
            self._stop.set()
            self._proceed.set()

    def emergency_stop(self) -> None:
        """Stop as fast as possible.

        Identical to :meth:`stop` from the engine's point of view, but flagged so
        the report and the UI can show that the emergency control was used. Held
        keys and mouse buttons are still released during cleanup.
        """
        with self._lock:
            self._emergency.set()
        self.stop()

    # -- queries -----------------------------------------------------------
    @property
    def state(self) -> RunState:
        with self._lock:
            return self._state

    @property
    def is_paused(self) -> bool:
        return not self._proceed.is_set()

    @property
    def is_emergency(self) -> bool:
        return self._emergency.is_set()

    def is_stop_requested(self) -> bool:
        return self._stop.is_set()

    def wait_for_stop(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds; return ``True`` if a stop arrived."""
        if timeout <= 0:
            return self._stop.is_set()
        return self._stop.wait(timeout)

    # -- engine-facing helpers --------------------------------------------
    def raise_if_stopped(self) -> None:
        if self._stop.is_set():
            raise Cancelled(emergency=self._emergency.is_set())

    def wait_while_paused(self, timeout: float | None = None) -> bool:
        """Block while paused. Returns ``True`` if the run may proceed.

        Returns ``False`` only when ``timeout`` elapses while still paused.
        """
        if self._proceed.is_set():
            return True
        return self._proceed.wait(timeout)
