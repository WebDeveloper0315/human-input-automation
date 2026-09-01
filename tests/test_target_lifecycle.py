"""What happens when the target window changes underneath a run.

Every case here must end in a failed run with an explanation - never in input
being sent to a different application.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.service import AutomationService
from human_input_automation.core.actions import TypeText, Wait
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.events import RunStatus
from human_input_automation.core.plan import AutomationPlan, RunOptions
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile

from .fakes import FakeClock, FakeKeyboard, FakeMouse, FakeWindows, make_target


def build(windows: FakeWindows) -> tuple[AutomationEngine, FakeKeyboard]:
    keyboard = FakeKeyboard()
    engine = AutomationEngine(
        keyboard=keyboard, mouse=FakeMouse(), windows=windows, clock=FakeClock()
    )
    return engine, keyboard


def plan_of(*actions: object, **kwargs: object) -> AutomationPlan:
    return AutomationPlan(
        make_target(), list(actions), timing=TimingProfile.instant(), **kwargs  # type: ignore[arg-type]
    )


def test_a_closed_target_fails_the_run_before_any_input() -> None:
    engine, keyboard = build(FakeWindows(windows=[], activate_result=False))
    report = engine.run(plan_of(TypeText(text="secret")))
    assert report.status is RunStatus.FAILED
    assert keyboard.calls == []


def test_a_target_that_is_no_longer_frontmost_fails_the_run() -> None:
    engine, keyboard = build(FakeWindows(activate_result=True, active_result=False))
    report = engine.run(plan_of(TypeText(text="secret")))
    assert report.status is RunStatus.FAILED
    assert keyboard.calls == []


def test_losing_focus_mid_run_stops_the_remaining_actions() -> None:
    """The window closed or the user switched away after the run began."""

    class LosesFocus(FakeWindows):
        def is_active(self, target: TargetWindow) -> bool | None:
            self.calls.append("is_active")
            # focused for activation and the first action, gone afterwards
            return self.calls.count("is_active") <= 2

    windows = LosesFocus()
    engine, keyboard = build(windows)
    report = engine.run(plan_of(TypeText(text="one"), TypeText(text="two")))
    assert report.status is RunStatus.FAILED
    assert "no longer focused" in (report.error or "")
    assert keyboard.typed == "one", "the second action must not be sent elsewhere"


def test_focus_rechecking_can_be_turned_off() -> None:
    class LosesFocus(FakeWindows):
        def is_active(self, target: TargetWindow) -> bool | None:
            self.calls.append("is_active")
            return self.calls.count("is_active") <= 1

    engine, keyboard = build(LosesFocus())
    report = engine.run(
        plan_of(
            TypeText(text="one"),
            TypeText(text="two"),
            options=RunOptions(reverify_focus=False),
        )
    )
    assert report.status is RunStatus.COMPLETED
    assert keyboard.typed == "onetwo"


def test_platforms_that_cannot_verify_focus_skip_the_recheck() -> None:
    """Unknown focus must not abort a run on its own."""
    capabilities = WindowCapabilities(
        can_enumerate=True, can_activate=True, can_send_synthetic_input=True
    )
    target = make_target(capabilities=capabilities)
    engine, keyboard = build(FakeWindows(active_result=None))
    plan = AutomationPlan(
        target, [TypeText(text="hi"), Wait(duration_ms=1)], timing=TimingProfile.instant()
    )
    assert engine.run(plan).status is RunStatus.COMPLETED
    assert keyboard.typed == "hi"


def test_the_focused_window_target_is_never_rechecked() -> None:
    engine, _keyboard = build(FakeWindows(active_result=False))
    plan = AutomationPlan(
        TargetWindow.focused_window(
            capabilities=WindowCapabilities(can_send_synthetic_input=True)
        ),
        [TypeText(text="hi")],
        timing=TimingProfile.instant(),
    )
    assert engine.run(plan).status is RunStatus.COMPLETED


# -- application-level target re-resolution --------------------------------
def service_with(windows: FakeWindows) -> AutomationService:
    return AutomationService(
        AdapterSet(
            keyboard=FakeKeyboard(),
            mouse=FakeMouse(),
            windows=windows,
            discovery=windows,
            clock=SystemClock(),
            host=PlatformReport(
                platform=PlatformName.LINUX,
                display_server=DisplayServer.X11,
                capabilities=WindowCapabilities.full(),
            ),
        )
    )


def test_a_renamed_window_is_still_the_same_target() -> None:
    """Titles change constantly; the handle is the identity."""
    original = make_target("h1", "Document - Editor")
    windows = FakeWindows(windows=[original])
    service = service_with(windows)

    windows.windows = [replace(original, title="Document (modified) - Editor")]
    resolved = service.refresh_target(original)
    assert resolved is not None
    assert resolved.handle == "h1"
    assert resolved.title == "Document (modified) - Editor"


def test_a_closed_window_no_longer_resolves() -> None:
    target = make_target("h1")
    windows = FakeWindows(windows=[target])
    service = service_with(windows)
    windows.windows = []
    assert service.refresh_target(target) is None


def test_a_restarted_application_gets_a_new_handle() -> None:
    """A restart means a new window id: the old target is gone, not renamed."""
    target = make_target("h1", "Editor")
    windows = FakeWindows(windows=[target])
    service = service_with(windows)
    windows.windows = [make_target("h2", "Editor")]
    assert service.refresh_target(target) is None


def test_discovery_failure_is_reported_not_raised() -> None:
    class Broken(FakeWindows):
        def list_windows(self) -> Sequence[TargetWindow]:
            raise RuntimeError("X connection lost")

    service = service_with(Broken())
    listing = service.discover_targets()
    assert listing.is_empty
    assert "X connection lost" in (listing.reason or "")
