"""Run control: pause, resume, stop and emergency stop semantics."""

from __future__ import annotations

import threading
import time

import pytest

from human_input_automation.core.control import RunControl, RunState
from human_input_automation.core.errors import Cancelled


def test_lifecycle_states() -> None:
    control = RunControl()
    state: RunState = control.state
    assert state is RunState.IDLE
    control.begin()
    state = control.state
    assert state is RunState.RUNNING
    control.pause()
    state = control.state
    paused = control.is_paused
    assert state is RunState.PAUSED and paused
    control.resume()
    state = control.state
    paused = control.is_paused
    assert state is RunState.RUNNING and not paused
    control.stop()
    state = control.state
    assert state is RunState.STOPPING
    control.finish()
    state = control.state
    assert state is RunState.FINISHED


def test_raise_if_stopped_reports_emergency_separately() -> None:
    control = RunControl()
    control.begin()
    control.raise_if_stopped()
    control.stop()
    with pytest.raises(Cancelled) as excinfo:
        control.raise_if_stopped()
    assert excinfo.value.emergency is False

    emergency = RunControl()
    emergency.begin()
    emergency.emergency_stop()
    with pytest.raises(Cancelled) as excinfo:
        emergency.raise_if_stopped()
    assert excinfo.value.emergency is True


def test_stop_releases_a_paused_run() -> None:
    control = RunControl()
    control.begin()
    control.pause()
    released = threading.Event()

    def waiter() -> None:
        control.wait_while_paused()
        released.set()

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    assert not released.wait(0.05)
    control.stop()
    assert released.wait(1.0)
    thread.join(1.0)


def test_wait_for_stop_returns_immediately_when_stopped() -> None:
    control = RunControl()
    control.begin()
    started = time.monotonic()
    threading.Timer(0.02, control.emergency_stop).start()
    assert control.wait_for_stop(5.0) is True
    assert time.monotonic() - started < 1.0


def test_reset_allows_a_control_to_be_reused() -> None:
    control = RunControl()
    control.begin()
    control.emergency_stop()
    control.finish()
    control.reset()
    control.begin()
    assert not control.is_stop_requested()
    assert not control.is_emergency
    control.raise_if_stopped()


def test_a_stop_requested_before_begin_is_still_honoured() -> None:
    """The window between "start clicked" and "engine running" must not swallow a stop."""
    control = RunControl()
    control.stop()
    control.begin()
    assert control.state is RunState.STOPPING
    with pytest.raises(Cancelled):
        control.raise_if_stopped()


def test_a_pause_requested_before_begin_is_still_honoured() -> None:
    control = RunControl()
    control.pause()
    control.begin()
    assert control.is_paused
    assert control.state is RunState.PAUSED
