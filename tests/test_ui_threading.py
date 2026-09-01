"""Qt thread-safety: worker events must reach widgets only via queued signals."""

from __future__ import annotations

import threading
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI extra not installed")

from PySide6.QtCore import QThread

from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.runner import AutomationRunner
from human_input_automation.core.actions import TypeText, Wait
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.events import RunEvent, RunFinished, RunStatus
from human_input_automation.core.plan import AutomationPlan
from human_input_automation.core.timing import TimingProfile
from human_input_automation.ui.run_bridge import RunEventBridge
from human_input_automation.ui.run_log import RunLog

from .fakes import FakeKeyboard, FakeMouse, FakeWindows, make_target

pytestmark = pytest.mark.usefixtures("qt_app")


def test_bridge_delivers_worker_events_on_the_main_thread(pump: Any) -> None:
    bridge = RunEventBridge()
    main_thread = QThread.currentThread()
    seen: list[tuple[RunFinished, object, int]] = []

    def slot(event: RunEvent) -> None:
        assert isinstance(event, RunFinished)
        seen.append((event, QThread.currentThread(), threading.get_ident()))

    bridge.run_event.connect(slot)
    main_ident = threading.get_ident()

    worker_ident: list[int] = []

    def worker() -> None:
        worker_ident.append(threading.get_ident())
        for index in range(3):
            bridge(RunFinished(RunStatus.COMPLETED, index, 0.0))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(5.0)

    assert pump(lambda: len(seen) == 3)
    assert worker_ident and worker_ident[0] != main_ident
    assert all(qt_thread == main_thread for _event, qt_thread, _ident in seen)
    assert all(ident == main_ident for _event, _qt_thread, ident in seen)
    assert [event.executed_actions for event, _, _ in seen] == [0, 1, 2]


def test_a_whole_run_reaches_widgets_only_from_the_main_thread(pump: Any) -> None:
    """The worker never touches a widget: it emits, the main thread renders."""
    keyboard = FakeKeyboard()
    engine = AutomationEngine(
        keyboard=keyboard, mouse=FakeMouse(), windows=FakeWindows(), clock=SystemClock()
    )
    runner = AutomationRunner(engine)
    bridge = RunEventBridge()
    log = RunLog()
    idents: set[int] = set()

    def slot(event: RunEvent) -> None:
        idents.add(threading.get_ident())
        from human_input_automation.ui.models import format_event

        line = format_event(event)
        if line is not None:
            log.append_line(line)

    bridge.run_event.connect(slot)

    plan = AutomationPlan(
        make_target(),
        [TypeText(text="hi"), Wait(duration_ms=1)],
        timing=TimingProfile.instant(),
        name="threading",
    )
    runner.start(plan, bridge)
    report = runner.join(5.0)

    assert report is not None and report.status is RunStatus.COMPLETED
    assert pump(lambda: any("Run completed" in line for line in log.lines))
    assert idents == {threading.get_ident()}, "widgets were touched from a worker thread"
    assert keyboard.typed == "hi"


def test_a_failing_ui_slot_cannot_break_the_automation_run(pump: Any) -> None:
    """A buggy UI slot must not stop the worker: the worker only calls emit."""
    keyboard = FakeKeyboard()
    engine = AutomationEngine(
        keyboard=keyboard, mouse=FakeMouse(), windows=FakeWindows(), clock=SystemClock()
    )
    runner = AutomationRunner(engine)
    bridge = RunEventBridge()
    received: list[RunEvent] = []

    def good_slot(event: RunEvent) -> None:
        received.append(event)

    def bad_slot(event: RunEvent) -> None:
        raise RuntimeError("slot bug")

    bridge.run_event.connect(bad_slot)
    bridge.run_event.connect(good_slot)

    plan = AutomationPlan(
        make_target(), [TypeText(text="ok")], timing=TimingProfile.instant(), name="slot bug"
    )
    runner.start(plan, bridge)
    report = runner.join(5.0)

    assert report is not None and report.status is RunStatus.COMPLETED
    assert keyboard.typed == "ok"

    # Qt logs the slot's exception and keeps going: the other slot still gets
    # every event, including the final one.
    assert pump(lambda: any(isinstance(event, RunFinished) for event in received))


def test_direct_signal_emission_is_synchronous_on_the_main_thread() -> None:
    """Emitting from the main thread still works (no event loop needed)."""
    bridge = RunEventBridge()
    seen: list[RunEvent] = []
    bridge.run_event.connect(seen.append)
    bridge(RunFinished(RunStatus.STOPPED, 0, 0.0))
    assert len(seen) == 1
