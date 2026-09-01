"""Threaded run orchestration.

The engine's ``run`` blocks, so the application layer runs it on a worker
thread. That is what keeps the GUI responsive and, crucially, what keeps the
emergency stop usable: the UI thread stays free to receive the click that calls
:meth:`AutomationRunner.emergency_stop`.

This module has no Qt dependency - it is plain ``threading`` and is tested
without a GUI.
"""

from __future__ import annotations

import logging
import threading

from ..core.control import RunControl, RunState
from ..core.engine import AutomationEngine
from ..core.events import (
    CountdownCancelled,
    CountdownStarted,
    CountdownTick,
    EventListener,
    RunEvent,
    RunFinished,
    RunReport,
    RunStatus,
)
from ..core.plan import AutomationPlan
from ..core.screen import ScreenGeometry
from ..core.target import PlatformReport

logger = logging.getLogger(__name__)


class AutomationRunner:
    """Runs one plan at a time on a background thread.

    Listener callbacks are invoked *on the worker thread*. A GUI must marshal
    them onto its own thread (for Qt: emit a signal, never touch widgets here).
    """

    def __init__(
        self,
        engine: AutomationEngine,
        listener: EventListener | None = None,
        *,
        tick_seconds: float = 1.0,
    ) -> None:
        self._engine = engine
        self._listener = listener
        self._tick_seconds = max(0.01, tick_seconds)
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
        screen: ScreenGeometry | None = None,
        countdown_seconds: float = 0.0,
    ) -> None:
        """Start ``plan`` in the background. Raises if a run is already active.

        ``countdown_seconds`` delays the run - and the target activation - so the
        user can get out of the way or abort. The countdown runs on the worker
        thread and is interrupted by :meth:`stop` and :meth:`emergency_stop`
        like any other wait.
        """
        with self._lock:
            if self.is_running:
                raise RuntimeError("an automation run is already in progress")
            self._report = None
            self._control = RunControl()
            thread = threading.Thread(
                target=self._run,
                args=(plan, listener or self._listener, host, screen, countdown_seconds),
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
        screen: ScreenGeometry | None = None,
        countdown_seconds: float = 0.0,
    ) -> None:
        emit = self._make_emitter(listener)
        if countdown_seconds > 0 and not self._countdown(countdown_seconds, emit):
            report = self._cancelled_report(plan)
            emit(CountdownCancelled(emergency=self._control.is_emergency))
            emit(RunFinished(report.status, 0, report.elapsed_ms, report.error))
            with self._lock:
                self._report = report
            return
        report = self._engine.run(plan, self._control, listener, host=host, screen=screen)
        with self._lock:
            self._report = report

    def _countdown(self, seconds: float, emit: EventListener) -> bool:
        """Wait ``seconds``, emitting ticks. Returns False if it was cancelled."""
        emit(CountdownStarted(seconds))
        remaining = seconds
        while remaining > 0:
            step = min(self._tick_seconds, remaining)
            if self._control.wait_for_stop(step):
                return False
            remaining = max(0.0, remaining - step)
            emit(CountdownTick(remaining))
        return not self._control.is_stop_requested()

    def _cancelled_report(self, plan: AutomationPlan) -> RunReport:
        return RunReport(
            status=RunStatus.STOPPED,
            executed_actions=0,
            elapsed_ms=0.0,
            plan_name=plan.name,
            dry_run=plan.options.dry_run,
            error="cancelled during the countdown; no input was sent",
        )

    def _make_emitter(self, listener: EventListener | None) -> EventListener:
        def emit(event: RunEvent) -> None:
            if listener is None:
                return
            try:
                listener(event)
            except Exception:  # a broken listener must not affect the run
                logger.exception("event listener raised for %r", event)

        return emit

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
