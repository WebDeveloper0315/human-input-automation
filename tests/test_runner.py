"""Application layer: threaded runs, and an emergency stop that stays responsive."""

from __future__ import annotations

import time

import pytest

from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.runner import AutomationRunner, EventCollector
from human_input_automation.core.actions import KeyDown, TypeText, Wait
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.events import RunFinished, RunStarted, RunStatus
from human_input_automation.core.plan import AutomationPlan
from human_input_automation.core.timing import TimingProfile
from human_input_automation.ports.clock import Clock

from .fakes import FakeKeyboard, FakeMouse, FakeWindows, make_target


def build_runner(clock: Clock | None = None) -> tuple[AutomationRunner, FakeKeyboard]:
    keyboard = FakeKeyboard()
    engine = AutomationEngine(
        keyboard=keyboard,
        mouse=FakeMouse(),
        windows=FakeWindows(),
        clock=clock or SystemClock(),
    )
    return AutomationRunner(engine), keyboard


def test_a_run_completes_on_a_background_thread() -> None:
    runner, keyboard = build_runner()
    collector = EventCollector()
    plan = AutomationPlan(
        make_target(), [TypeText(text="hello")], timing=TimingProfile.instant()
    )
    runner.start(plan, collector)
    report = runner.join(5.0)
    assert report is not None and report.status is RunStatus.COMPLETED
    assert keyboard.typed == "hello"
    assert collector.of_type(RunStarted) and collector.of_type(RunFinished)


def test_starting_twice_is_refused() -> None:
    runner, _ = build_runner()
    plan = AutomationPlan(make_target(), [Wait(duration_ms=2_000)], timing=TimingProfile.instant())
    runner.start(plan)
    try:
        with pytest.raises(RuntimeError):
            runner.start(plan)
    finally:
        runner.emergency_stop()
        runner.join(5.0)


def test_emergency_stop_interrupts_a_long_wait_immediately() -> None:
    """The point of the emergency stop: it must not wait for the delay to end."""
    runner, keyboard = build_runner()
    plan = AutomationPlan(
        make_target(),
        [KeyDown(key="shift"), Wait(duration_ms=60_000), TypeText(text="never typed")],
        timing=TimingProfile.instant(),
    )
    runner.start(plan)
    time.sleep(0.05)

    started = time.monotonic()
    runner.emergency_stop()
    report = runner.join(5.0)
    elapsed = time.monotonic() - started

    assert report is not None and report.status is RunStatus.EMERGENCY_STOPPED
    assert elapsed < 2.0, "emergency stop must not wait for the pending delay"
    assert keyboard.calls == [("key_down", "shift"), ("key_up", "shift")]


def test_pause_and_resume_from_another_thread() -> None:
    runner, keyboard = build_runner()
    plan = AutomationPlan(
        make_target(),
        [TypeText(text="a"), Wait(duration_ms=50), TypeText(text="b")],
        timing=TimingProfile.instant(),
    )
    runner.pause()
    runner.start(plan)
    time.sleep(0.05)
    runner.resume()
    report = runner.join(5.0)
    assert report is not None and report.status is RunStatus.COMPLETED
    assert keyboard.typed == "ab"


def test_stop_before_completion_reports_a_stopped_run() -> None:
    runner, _ = build_runner()
    plan = AutomationPlan(
        make_target(),
        [Wait(duration_ms=30_000), TypeText(text="unreachable")],
        timing=TimingProfile.instant(),
    )
    runner.start(plan)
    time.sleep(0.05)
    runner.stop()
    report = runner.join(5.0)
    assert report is not None and report.status is RunStatus.STOPPED
