"""Pre-run countdown, driven entirely through the existing control architecture."""

from __future__ import annotations

import threading
import time
from typing import Any

from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.runner import AutomationRunner, EventCollector
from human_input_automation.core.actions import TypeText
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.events import (
    CountdownCancelled,
    CountdownStarted,
    CountdownTick,
    RunFinished,
    RunStarted,
    RunStatus,
)
from human_input_automation.core.plan import AutomationPlan
from human_input_automation.core.timing import TimingProfile

from .fakes import FakeKeyboard, FakeMouse, FakeWindows, make_target


def build(tick: float = 0.02) -> tuple[AutomationRunner, FakeKeyboard, FakeWindows]:
    keyboard = FakeKeyboard()
    windows = FakeWindows()
    engine = AutomationEngine(
        keyboard=keyboard, mouse=FakeMouse(), windows=windows, clock=SystemClock()
    )
    return AutomationRunner(engine, tick_seconds=tick), keyboard, windows


def plan() -> AutomationPlan:
    return AutomationPlan(
        make_target(), [TypeText(text="hi")], timing=TimingProfile.instant(), name="countdown"
    )


def test_countdown_emits_ticks_then_runs() -> None:
    runner, keyboard, _ = build()
    events = EventCollector()
    runner.start(plan(), events, countdown_seconds=0.1)
    report = runner.join(5.0)

    assert report is not None and report.status is RunStatus.COMPLETED
    assert keyboard.typed == "hi"
    assert events.of_type(CountdownStarted)
    assert events.of_type(CountdownTick)
    assert events.of_type(RunStarted)
    kinds = [type(event) for event in events.events]
    assert kinds.index(CountdownStarted) < kinds.index(RunStarted)


def test_no_countdown_events_when_it_is_zero() -> None:
    runner, _, _ = build()
    events = EventCollector()
    runner.start(plan(), events, countdown_seconds=0)
    runner.join(5.0)
    assert not events.of_type(CountdownStarted)


def test_the_target_is_not_touched_during_the_countdown() -> None:
    runner, keyboard, windows = build()
    runner.start(plan(), countdown_seconds=0.4)
    time.sleep(0.1)
    assert windows.calls == [], "activation must wait until the countdown ends"
    assert keyboard.calls == []
    runner.join(5.0)
    assert windows.calls


def test_stop_during_the_countdown_cancels_before_any_input() -> None:
    runner, keyboard, windows = build()
    events = EventCollector()
    runner.start(plan(), events, countdown_seconds=5.0)
    time.sleep(0.05)
    runner.stop()
    report = runner.join(5.0)

    assert report is not None and report.status is RunStatus.STOPPED
    assert report.executed_actions == 0
    assert keyboard.calls == [] and windows.calls == []
    assert events.of_type(CountdownCancelled)
    assert events.of_type(RunFinished)
    assert not events.of_type(RunStarted)


def test_emergency_stop_during_the_countdown_is_flagged() -> None:
    runner, _, _ = build()
    events = EventCollector()
    runner.start(plan(), events, countdown_seconds=5.0)
    time.sleep(0.05)

    started = time.monotonic()
    runner.emergency_stop()
    report = runner.join(5.0)
    elapsed = time.monotonic() - started

    assert report is not None and report.status is RunStatus.STOPPED
    assert elapsed < 2.0, "the countdown must not run to completion after a stop"
    cancelled = events.of_type(CountdownCancelled)
    assert cancelled
    event = cancelled[0]
    assert isinstance(event, CountdownCancelled) and event.emergency is True


def test_a_broken_listener_during_the_countdown_does_not_break_the_run() -> None:
    runner, keyboard, _ = build()

    def bad_listener(event: Any) -> None:
        raise RuntimeError("listener bug")

    runner.start(plan(), bad_listener, countdown_seconds=0.05)
    report = runner.join(5.0)
    assert report is not None and report.status is RunStatus.COMPLETED
    assert keyboard.typed == "hi"


def test_countdown_runs_off_the_calling_thread() -> None:
    runner, _, _ = build()
    caller = threading.get_ident()
    idents: list[int] = []
    runner.start(plan(), lambda event: idents.append(threading.get_ident()), countdown_seconds=0.05)
    runner.join(5.0)
    assert idents and all(ident != caller for ident in idents)
