"""Threaded run orchestration.

The engine's ``run`` blocks, so the application layer runs it on a worker
thread. That is what keeps the GUI responsive and, crucially, what keeps the
emergency stop usable: the UI thread stays free to receive the click that calls
:meth:`AutomationRunner.emergency_stop`.

This module has no Qt dependency - it is plain ``threading`` and is tested
without a GUI.
"""

from __future__ import annotations

import threading

from ..core.control import RunControl, RunState
from ..core.engine import AutomationEngine
from ..core.events import EventListener, RunEvent, RunReport
from ..core.plan import AutomationPlan
from ..core.target import PlatformReport


class AutomationRunner:
    """Runs one plan at a time on a background thread.

    Listener callbacks are invoked *on the worker thread*. A GUI must marshal
    them onto its own thread (for Qt: emit a signal, never touch widgets here).
    """

    def __init__(self, engine: AutomationEngine, listener: EventListener | None = None) -> None:
        self._engine = engine
        self._listener = listener
        self._control = RunControl()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._report: RunReport | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(
        self,
        plan: AutomationPlan,
        listener: EventListener | None = None,
        *,
        host: PlatformReport | None = None,
    ) -> None:
        """Start ``plan`` in the background. Raises if a run is already active."""
        with self._lock:
            if self.is_running:
                raise RuntimeError("an automation run is already in progress")
            self._report = None
            self._control = RunControl()
            thread = threading.Thread(
                target=self._run,
                args=(plan, listener or self._listener, host),
                name="automation-runner",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def _run(
        self,
        plan: AutomationPlan,
        listener: EventListener | None,
        host: PlatformReport | None,
    ) -> None:
        report = self._engine.run(plan, self._control, listener, host=host)
        with self._lock:
            self._report = report

    # -- controls ----------------------------------------------------------
    def pause(self) -> None:
        self._control.pause()

    def resume(self) -> None:
        self._control.resume()

    def stop(self) -> None:
        self._control.stop()

    def emergency_stop(self) -> None:
        """Stop immediately. Safe to call at any time, including when idle."""
        self._control.emergency_stop()

    # -- queries -----------------------------------------------------------
    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def state(self) -> RunState:
        return self._control.state

    @property
    def last_report(self) -> RunReport | None:
        with self._lock:
            return self._report

    def join(self, timeout: float | None = None) -> RunReport | None:
        """Wait for the current run to finish and return its report."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self.last_report


class EventCollector:
    """Thread-safe listener that accumulates events.

    Handy for tests, for the run log, and as a template for a UI adapter.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[RunEvent] = []

    def __call__(self, event: RunEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> list[RunEvent]:
        with self._lock:
            return list(self._events)

    def of_type(self, event_type: type[RunEvent]) -> list[RunEvent]:
        return [event for event in self.events if isinstance(event, event_type)]
