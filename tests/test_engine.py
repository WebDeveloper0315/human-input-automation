"""Engine behaviour: sequencing, targeting, safety and cancellation.

Everything here runs against fakes and a virtual clock, so the suite needs no
desktop session and finishes in milliseconds.
"""

from __future__ import annotations

from typing import Any

import pytest

from human_input_automation.core.actions import (
    Action,
    KeyDown,
    KeyPress,
    KeyUp,
    MouseClick,
    MouseDown,
    MouseMove,
    MouseUp,
    Shortcut,
    TypeText,
    Wait,
)
from human_input_automation.core.control import RunControl
from human_input_automation.core.engine import AutomationEngine, ExecutionContext
from human_input_automation.core.events import (
    ActionCompleted,
    ActionStarted,
    RunFinished,
    RunStarted,
    RunStatus,
    TargetActivated,
)
from human_input_automation.core.keys import MouseButton
from human_input_automation.core.plan import AutomationPlan, ExecutionLimits, RunOptions
from human_input_automation.core.target import TargetWindow, WindowCapabilities
from human_input_automation.core.timing import TimingProfile

from .fakes import FakeClock, FakeKeyboard, FakeMouse, FakeWindows, make_target


def build_engine(
    keyboard: FakeKeyboard | None = None,
    mouse: FakeMouse | None = None,
    windows: FakeWindows | None = None,
    clock: FakeClock | None = None,
) -> tuple[AutomationEngine, FakeKeyboard, FakeMouse, FakeWindows, FakeClock]:
    keyboard = keyboard or FakeKeyboard()
    mouse = mouse or FakeMouse()
    windows = windows or FakeWindows()
    clock = clock or FakeClock()
    engine = AutomationEngine(keyboard=keyboard, mouse=mouse, windows=windows, clock=clock)
    return engine, keyboard, mouse, windows, clock


def plan_of(*actions: Action, **kwargs: Any) -> AutomationPlan:
    kwargs.setdefault("timing", TimingProfile.instant())
    return AutomationPlan(make_target(), list(actions), **kwargs)


# -- sequencing -----------------------------------------------------------
def test_actions_run_in_order_after_the_target_is_activated() -> None:
    engine, keyboard, mouse, windows, _ = build_engine()
    report = engine.run(
        plan_of(
            TypeText(text="hi"),
            KeyPress(key="enter"),
            MouseClick(button=MouseButton.LEFT, x=10, y=20),
        )
    )
    assert report.status is RunStatus.COMPLETED
    assert report.executed_actions == 3
    assert windows.calls[0] == "activate:win-1"
    assert keyboard.typed == "hi"
    assert keyboard.names == ["type_text", "key_down", "key_up"]
    assert mouse.names == ["move_to", "button_down", "button_up"]


def test_typing_is_per_character_when_a_delay_is_configured() -> None:
    engine, keyboard, _, _, clock = build_engine()
    plan = AutomationPlan(
        make_target(),
        [TypeText(text="abc")],
        timing=TimingProfile(char_delay_ms=50, char_jitter_ms=0, min_delay_ms=0, max_delay_ms=100),
    )
    engine.run(plan)
    assert [value for name, value in keyboard.calls if name == "type_text"] == ["a", "b", "c"]
    assert clock.sleeps_ms == [50, 50, 50]


def test_typing_is_sent_in_one_call_when_timing_is_instant() -> None:
    engine, keyboard, _, _, clock = build_engine()
    engine.run(plan_of(TypeText(text="abc")))
    assert keyboard.calls == [("type_text", "abc")]
    assert clock.sleeps_ms == []


def test_key_press_repeats_and_holds_are_expanded_correctly() -> None:
    engine, keyboard, _, _, _ = build_engine()
    engine.run(plan_of(KeyPress(key="a", count=3)))
    assert keyboard.names == ["key_down", "key_up"] * 3


def test_shortcut_presses_and_releases_in_reverse_order() -> None:
    engine, keyboard, _, _, _ = build_engine()
    engine.run(plan_of(Shortcut.parse("ctrl+shift+p")))
    assert keyboard.calls == [
        ("key_down", "ctrl"),
        ("key_down", "shift"),
        ("key_down", "p"),
        ("key_up", "p"),
        ("key_up", "shift"),
        ("key_up", "ctrl"),
    ]


def test_mouse_move_supports_absolute_and_relative_movement() -> None:
    engine, _, mouse, _, _ = build_engine()
    engine.run(plan_of(MouseMove(x=100, y=50), MouseMove(x=5, y=-5, relative=True)))
    assert mouse.calls == [("move_to", "100,50"), ("move_by", "5,-5")]


def test_mouse_button_hold_and_release_are_supported() -> None:
    engine, _, mouse, _, _ = build_engine()
    engine.run(plan_of(MouseDown(button=MouseButton.RIGHT), MouseUp(button=MouseButton.RIGHT)))
    assert mouse.calls == [("button_down", "right"), ("button_up", "right")]


def test_wait_uses_the_interruptible_clock() -> None:
    engine, _, _, _, clock = build_engine()
    engine.run(plan_of(Wait(duration_ms=500)))
    assert clock.sleeps_ms == [500]


def test_action_level_delay_overrides_the_profile() -> None:
    engine, _, _, _, clock = build_engine()
    plan = AutomationPlan(
        make_target(),
        [KeyPress(key="a", delay_after_ms=333), KeyPress(key="b")],
        timing=TimingProfile.instant(),
    )
    engine.run(plan)
    assert 333 in clock.sleeps_ms


# -- extensibility --------------------------------------------------------
def test_a_new_action_type_only_needs_a_handler() -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Beep(Action):
        times: int = 1

        def describe(self) -> str:
            return f"beep x{self.times}"

    seen: list[int] = []

    def handle_beep(action: Beep, ctx: ExecutionContext) -> None:
        seen.append(action.times)

    engine, _, _, _, _ = build_engine()
    engine.registry.register(Beep, handle_beep)
    report = engine.run(plan_of(Beep(times=3)))
    assert report.status is RunStatus.COMPLETED
    assert seen == [3]


def test_an_unregistered_action_fails_the_run_instead_of_crashing() -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Unknown(Action):
        pass

    engine, _, _, _, _ = build_engine()
    report = engine.run(plan_of(Unknown()))
    assert report.status is RunStatus.FAILED
    assert "no handler registered" in (report.error or "")


# -- target handling ------------------------------------------------------
def test_a_failed_activation_aborts_before_any_input_is_sent() -> None:
    windows = FakeWindows(activate_result=False)
    engine, keyboard, _, _, _ = build_engine(windows=windows)
    report = engine.run(plan_of(TypeText(text="secret")))
    assert report.status is RunStatus.FAILED
    assert keyboard.calls == []


def test_a_target_that_does_not_take_focus_aborts_the_run() -> None:
    windows = FakeWindows(activate_result=True, active_result=False)
    engine, keyboard, _, _, _ = build_engine(windows=windows)
    report = engine.run(plan_of(TypeText(text="secret")))
    assert report.status is RunStatus.FAILED
    assert "did not take focus" in (report.error or "")
    assert keyboard.calls == []


def test_unverifiable_focus_runs_by_default_and_aborts_when_verification_is_required() -> None:
    windows = FakeWindows(active_result=None)
    engine, keyboard, _, _, _ = build_engine(windows=windows)
    assert engine.run(plan_of(TypeText(text="hi"))).status is RunStatus.COMPLETED

    windows = FakeWindows(active_result=None)
    engine, keyboard, _, _, _ = build_engine(windows=windows)
    report = engine.run(
        plan_of(TypeText(text="hi"), options=RunOptions(require_focus_verification=True))
    )
    assert report.status is RunStatus.FAILED
    assert keyboard.calls == []


def test_the_focused_window_target_skips_activation() -> None:
    engine, keyboard, _, windows, _ = build_engine()
    plan = AutomationPlan(
        TargetWindow.focused_window(capabilities=WindowCapabilities(can_send_synthetic_input=True)),
        [TypeText(text="hi")],
        timing=TimingProfile.instant(),
    )
    report = engine.run(plan)
    assert report.status is RunStatus.COMPLETED
    assert windows.calls == []
    assert keyboard.typed == "hi"


def test_a_selected_target_without_a_window_adapter_is_refused() -> None:
    engine = AutomationEngine(
        keyboard=FakeKeyboard(), mouse=FakeMouse(), clock=FakeClock(), windows=None
    )
    report = engine.run(plan_of(TypeText(text="hi")))
    assert report.status is RunStatus.FAILED
    assert "no window control adapter" in (report.error or "")


# -- safety ---------------------------------------------------------------
def test_dry_run_sends_nothing_but_reports_every_action() -> None:
    engine, keyboard, mouse, windows, _ = build_engine()
    report = engine.run(
        plan_of(
            TypeText(text="hello"),
            MouseClick(x=1, y=2),
            options=RunOptions(dry_run=True),
        )
    )
    assert report.status is RunStatus.COMPLETED
    assert report.dry_run
    assert keyboard.calls == [] and mouse.calls == [] and windows.calls == []
    assert report.performed == ("type 'hello' (5 chars)", "left click at (1, 2)")


def test_dry_run_estimates_the_duration_without_waiting() -> None:
    engine, _, _, _, clock = build_engine()
    plan = AutomationPlan(
        make_target(),
        [Wait(duration_ms=5_000), Wait(duration_ms=5_000)],
        timing=TimingProfile.instant(),
        options=RunOptions(dry_run=True),
    )
    report = engine.run(plan)
    assert report.status is RunStatus.COMPLETED
    assert report.elapsed_ms == pytest.approx(10_000)
    assert clock.sleeps_ms == [], "a dry run must not consume real time"


def test_an_invalid_plan_is_reported_and_never_executed() -> None:
    engine, keyboard, _, windows, _ = build_engine()
    report = engine.run(AutomationPlan(make_target(), []))
    assert report.status is RunStatus.INVALID
    assert keyboard.calls == [] and windows.calls == []
    assert any(issue.code == "plan.no_actions" for issue in report.issues)


def test_the_run_duration_limit_stops_a_long_plan() -> None:
    engine, _, _, _, _ = build_engine()
    plan = AutomationPlan(
        make_target(),
        [Wait(duration_ms=20_000) for _ in range(10)],
        timing=TimingProfile.instant(),
        limits=ExecutionLimits(max_run_duration_s=30),
    )
    report = engine.run(plan)
    assert report.status is RunStatus.FAILED
    assert "duration limit" in (report.error or "")
    assert report.executed_actions < 10


def test_held_keys_and_buttons_are_released_when_a_run_ends() -> None:
    engine, keyboard, mouse, _, _ = build_engine()
    engine.run(plan_of(KeyDown(key="shift"), MouseDown(button=MouseButton.LEFT)))
    assert keyboard.calls[-1] == ("key_up", "shift")
    assert mouse.calls[-1] == ("button_up", "left")


def test_held_keys_are_released_even_when_an_adapter_fails() -> None:
    keyboard = FakeKeyboard()
    engine, _, _, _, _ = build_engine(keyboard=keyboard)

    def explode(action: Action, ctx: ExecutionContext) -> None:
        raise RuntimeError("adapter exploded")

    engine.registry.register(Wait, explode)
    report = engine.run(plan_of(KeyDown(key="ctrl"), Wait(duration_ms=1)))
    assert report.status is RunStatus.FAILED
    assert keyboard.calls == [("key_down", "ctrl"), ("key_up", "ctrl")]


def test_explicit_key_up_is_not_repeated_during_cleanup() -> None:
    engine, keyboard, _, _, _ = build_engine()
    engine.run(plan_of(KeyDown(key="alt"), KeyUp(key="alt")))
    assert keyboard.names == ["key_down", "key_up"]


# -- cancellation ---------------------------------------------------------
def test_a_stop_request_ends_the_run_at_the_next_checkpoint() -> None:
    control = RunControl()
    clock = FakeClock(on_sleep=lambda c: control.stop() if len(c.sleeps_ms) == 2 else None)
    engine, keyboard, _, _, _ = build_engine(clock=clock)
    plan = AutomationPlan(
        make_target(),
        [TypeText(text="abcdefgh")],
        timing=TimingProfile(char_delay_ms=10, char_jitter_ms=0, min_delay_ms=0, max_delay_ms=20),
    )
    report = engine.run(plan, control)
    assert report.status is RunStatus.STOPPED
    assert keyboard.typed == "ab"


def test_an_emergency_stop_is_reported_separately_and_releases_held_keys() -> None:
    control = RunControl()
    clock = FakeClock(on_sleep=lambda c: control.emergency_stop())
    engine, keyboard, _, _, _ = build_engine(clock=clock)
    plan = AutomationPlan(
        make_target(),
        [KeyDown(key="shift"), Wait(duration_ms=5_000), TypeText(text="never typed")],
        timing=TimingProfile.instant(),
    )
    report = engine.run(plan, control)
    assert report.status is RunStatus.EMERGENCY_STOPPED
    assert keyboard.calls == [("key_down", "shift"), ("key_up", "shift")]


def test_a_stop_during_a_wait_does_not_sleep_out_the_remaining_time() -> None:
    control = RunControl()
    clock = FakeClock(on_sleep=lambda c: control.stop())
    engine, _, _, _, _ = build_engine(clock=clock)
    report = engine.run(plan_of(Wait(duration_ms=60_000), Wait(duration_ms=60_000)), control)
    assert report.status is RunStatus.STOPPED
    assert clock.sleeps_ms == [60_000]


def test_pause_blocks_the_run_until_resume() -> None:
    import threading

    control = RunControl()
    engine, keyboard, _, _, _ = build_engine()
    plan = AutomationPlan(
        make_target(),
        [TypeText(text="a"), TypeText(text="b")],
        timing=TimingProfile.instant(),
    )
    control.begin()
    control.pause()
    done = threading.Event()
    result: dict[str, Any] = {}

    def worker() -> None:
        result["report"] = engine.run(plan, control)
        done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert not done.wait(0.1)
    control.resume()
    assert done.wait(2.0)
    thread.join(1.0)
    assert result["report"].status is RunStatus.COMPLETED
    assert keyboard.typed == "ab"


# -- events ---------------------------------------------------------------
def test_events_describe_the_whole_run() -> None:
    engine, _, _, _, _ = build_engine()
    events: list[Any] = []
    report = engine.run(plan_of(TypeText(text="hi"), KeyPress(key="enter")), listener=events.append)
    kinds = [type(event) for event in events]
    assert kinds[0] is RunStarted
    assert kinds[1] is TargetActivated
    assert kinds.count(ActionStarted) == 2
    assert kinds.count(ActionCompleted) == 2
    assert kinds[-1] is RunFinished
    assert events[-1].status is report.status


def test_a_broken_listener_cannot_break_a_run() -> None:
    engine, keyboard, _, _, _ = build_engine()

    def bad_listener(event: Any) -> None:
        raise RuntimeError("listener bug")

    report = engine.run(plan_of(TypeText(text="hi")), listener=bad_listener)
    assert report.status is RunStatus.COMPLETED
    assert keyboard.typed == "hi"


def test_deterministic_seed_reproduces_identical_delays() -> None:
    def run_once() -> list[float]:
        engine, _, _, _, clock = build_engine()
        plan = AutomationPlan(
            make_target(),
            [TypeText(text="hello world."), KeyPress(key="enter")],
            timing=TimingProfile(word_pause_ms=100, punctuation_pause_ms=200),
            options=RunOptions(seed=1234),
        )
        engine.run(plan)
        return clock.sleeps_ms

    assert run_once() == run_once()


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_delays_respect_profile_bounds_during_a_real_run(seed: int) -> None:
    engine, _, _, _, clock = build_engine()
    plan = AutomationPlan(
        make_target(),
        [TypeText(text="hello world")],
        timing=TimingProfile(
            char_delay_ms=40, char_jitter_ms=100, min_delay_ms=10, max_delay_ms=60
        ),
        options=RunOptions(seed=seed),
    )
    engine.run(plan)
    assert all(10 <= value <= 60 for value in clock.sleeps_ms)
