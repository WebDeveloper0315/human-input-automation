"""Presentation models: state machine, forms, banner and formatting (no Qt)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from human_input_automation.adapters.hotkeys import HotkeySupport
from human_input_automation.core.actions import (
    IndentMode,
    KeyPress,
    MouseClick,
    MouseMove,
    Shortcut,
    TypeText,
    Wait,
)
from human_input_automation.core.errors import Severity, ValidationError, ValidationIssue
from human_input_automation.core.events import (
    ActionStarted,
    CountdownCancelled,
    CountdownStarted,
    CountdownTick,
    RunFinished,
    RunPaused,
    RunReport,
    RunResumed,
    RunStarted,
    RunStatus,
    TargetActivated,
)
from human_input_automation.core.keys import Key, MouseButton
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile
from human_input_automation.core.typing_style import TypingStyle
from human_input_automation.ui.models import (
    ACTION_SPECS,
    DEFAULT_TYPO_PERCENT,
    INDENT_LABELS,
    CapabilityLevel,
    TargetRow,
    UiState,
    action_row_text,
    action_to_values,
    active_target_text,
    build_action,
    build_timing_profile,
    capability_banner,
    controls_for,
    dry_run_view,
    format_event,
    format_preview,
    friendly_error,
    host_status_text,
    next_state,
    preview_delays,
    spec_for_action,
    timing_to_values,
    typing_style_to_values,
    typing_style_with_rate,
)

from .fakes import make_target


def host(
    platform: PlatformName = PlatformName.LINUX,
    display: DisplayServer = DisplayServer.X11,
    capabilities: WindowCapabilities | None = None,
    **kwargs: object,
) -> PlatformReport:
    return PlatformReport(
        platform=platform,
        display_server=display,
        capabilities=capabilities or WindowCapabilities.full(),
        **kwargs,  # type: ignore[arg-type]
    )


# -- run state machine ----------------------------------------------------
def test_countdown_and_run_events_drive_the_state_machine() -> None:
    state = UiState.IDLE
    state = next_state(state, CountdownStarted(3))
    assert state is UiState.COUNTDOWN
    state = next_state(state, CountdownTick(2))
    assert state is UiState.COUNTDOWN
    state = next_state(state, RunStarted("plan", 2, False))
    assert state is UiState.RUNNING
    state = next_state(state, RunPaused(0))
    assert state is UiState.PAUSED
    state = next_state(state, RunResumed(0))
    assert state is UiState.RUNNING
    state = next_state(state, RunFinished(RunStatus.COMPLETED, 2, 10.0))
    assert state is UiState.COMPLETED


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RunStatus.COMPLETED, UiState.COMPLETED),
        (RunStatus.STOPPED, UiState.STOPPED),
        (RunStatus.EMERGENCY_STOPPED, UiState.STOPPED),
        (RunStatus.FAILED, UiState.FAILED),
        (RunStatus.INVALID, UiState.FAILED),
    ],
)
def test_terminal_states(status: RunStatus, expected: UiState) -> None:
    assert next_state(UiState.RUNNING, RunFinished(status, 0, 0.0)) is expected


def test_unrelated_events_do_not_change_the_state() -> None:
    assert next_state(UiState.RUNNING, ActionStarted(0, Wait(duration_ms=1), "wait")) is (
        UiState.RUNNING
    )
    assert next_state(UiState.COUNTDOWN, CountdownCancelled()) is UiState.COUNTDOWN


def test_controls_while_idle_require_a_target_and_actions() -> None:
    ready = controls_for(UiState.IDLE)
    assert ready.start_enabled and ready.editing_enabled and ready.dry_run_enabled
    assert not controls_for(UiState.IDLE, has_target=False).start_enabled
    assert not controls_for(UiState.IDLE, has_actions=False).start_enabled


def test_controls_lock_editing_while_running() -> None:
    state = controls_for(UiState.RUNNING)
    assert not state.start_enabled
    assert state.pause_enabled and state.stop_enabled
    assert not state.resume_enabled
    assert not state.editing_enabled and not state.dry_run_enabled


def test_paused_offers_resume_not_pause() -> None:
    state = controls_for(UiState.PAUSED)
    assert state.resume_enabled and not state.pause_enabled and state.stop_enabled


def test_countdown_locks_editing_but_allows_stop() -> None:
    state = controls_for(UiState.COUNTDOWN)
    assert state.stop_enabled and not state.pause_enabled and not state.editing_enabled


@pytest.mark.parametrize("state", list(UiState))
def test_emergency_stop_is_enabled_in_every_state(state: UiState) -> None:
    assert controls_for(state).emergency_enabled is True


def test_terminal_states_behave_like_idle() -> None:
    for state in (UiState.COMPLETED, UiState.STOPPED, UiState.FAILED):
        controls = controls_for(state)
        assert controls.start_enabled and controls.editing_enabled
        assert controls.status_text != "Idle"


# -- capability banner ----------------------------------------------------
def test_banner_reports_available_host() -> None:
    model = capability_banner(host())
    assert model.level is CapabilityLevel.AVAILABLE
    assert model.marker == "OK"


def test_banner_reports_denied_permission() -> None:
    report = host(
        PlatformName.MACOS,
        DisplayServer.QUARTZ,
        WindowCapabilities(requires_permission="Accessibility"),
        missing_permissions=("Accessibility",),
    )
    model = capability_banner(report)
    assert model.level is CapabilityLevel.DENIED
    assert any("Accessibility" in detail for detail in model.details)


def test_banner_reports_restricted_wayland() -> None:
    report = host(
        PlatformName.LINUX,
        DisplayServer.WAYLAND,
        WindowCapabilities(can_send_synthetic_input=True),
        warnings=("Wayland restricts window control",),
    )
    model = capability_banner(report)
    assert model.level is CapabilityLevel.RESTRICTED
    assert "restricts window control" in model.headline


def test_banner_reports_unknown_focus_verification_without_saying_no() -> None:
    report = host(
        capabilities=WindowCapabilities(
            can_enumerate=True, can_activate=True, can_send_synthetic_input=True
        )
    )
    model = capability_banner(report)
    assert model.level is CapabilityLevel.UNKNOWN
    assert model.marker == "UNKNOWN"


def test_banner_reports_unavailable_backend() -> None:
    model = capability_banner(host(), problems=("pynput is not usable on this host: no module",))
    assert model.level is CapabilityLevel.UNAVAILABLE
    assert model.symbol == "✗"


def test_banner_includes_hotkey_reason() -> None:
    model = capability_banner(host(), hotkey=HotkeySupport(False, "Wayland blocks it"))
    assert any("Wayland blocks it" in detail for detail in model.details)


def test_status_text_is_qt_free_and_lists_capabilities() -> None:
    """The summary prints each capability's own state word, never yes/no.

    Regression: a macOS run showed "Verify focus: no" for a capability whose
    state was *unknown* - exactly the confusion the five-state model exists to
    prevent.
    """
    from human_input_automation.adapters.platform_info import describe_host

    text = host_status_text(
        describe_host(PlatformName.LINUX, DisplayServer.WAYLAND, env={}),
        problems=("adapter missing",),
        hotkey=HotkeySupport(None, "unknown"),
    )
    assert "Platform: linux (wayland)" in text
    assert "Enumerate windows: unavailable" in text
    assert "Adapter: adapter missing" in text
    assert "Emergency hotkey: unknown" in text
    assert ": no" not in text, "a state must never be rendered as a bare no"


def test_an_unverified_permission_is_never_shown_as_no() -> None:
    """macOS with nothing confirmed yet: every gated line must say 'unknown'."""
    from human_input_automation.adapters.platform_info import describe_host

    text = host_status_text(
        describe_host(
            PlatformName.MACOS,
            DisplayServer.QUARTZ,
            env={},
            accessibility_trusted=True,
            input_monitoring_trusted=None,
            automation_trusted=None,
        )
    )
    assert "Send input: available" in text
    assert "Verify focus: unknown" in text
    assert "Activate windows: unknown" in text
    assert ": no" not in text


# -- target presentation --------------------------------------------------
def test_target_row_uses_placeholders_for_missing_metadata() -> None:
    row = TargetRow.from_target(TargetWindow(handle="h1"))
    assert row.title == "(untitled)" and row.process == "-" and row.pid == "-"


def test_active_target_text_states_when_nothing_is_selected() -> None:
    assert "none selected" in active_target_text(None)
    assert "Test Window" in active_target_text(make_target())
    assert "UNAVAILABLE" in active_target_text(make_target(), available=False)


# -- action forms ---------------------------------------------------------
def test_every_action_spec_round_trips_through_the_form() -> None:
    samples: dict[str, dict[str, Any]] = {
        "type_text": {"text": "hello"},
        "type_code": {
            "text": "def f():\n    pass",
            "indent": INDENT_LABELS[IndentMode.EDITOR],
            "drop_auto_pairs": False,
            "dismiss_suggestions": True,
            "line_start_chord": "meta+shift+left",
        },
        "key_press": {"key": "enter", "count": 2},
        "key_down": {"key": "shift"},
        "key_up": {"key": "shift"},
        "shortcut": {"keys": "ctrl+shift+p"},
        "mouse_move": {"x": 10, "y": 20, "relative": False, "duration_ms": 100.0},
        "mouse_click": {"button": "right", "use_position": True, "x": 5, "y": 6, "count": 2},
        "mouse_down": {"button": "middle"},
        "mouse_up": {"button": "middle"},
        "wait": {"duration_ms": 250.0},
    }
    assert set(samples) == {spec.kind for spec in ACTION_SPECS}
    for kind, values in samples.items():
        action = build_action(kind, values, 50.0)
        assert action.delay_after_ms == 50.0
        spec = spec_for_action(action)
        assert spec is not None and spec.kind == kind
        rebuilt = build_action(kind, action_to_values(action), action.delay_after_ms)
        assert rebuilt == action


def test_build_action_produces_domain_objects() -> None:
    assert build_action("type_text", {"text": "hi"}) == TypeText(text="hi")
    assert build_action("key_press", {"key": "ENTER", "count": 1}) == KeyPress(key=Key.ENTER)
    assert build_action("shortcut", {"keys": "ctrl+s"}) == Shortcut.parse("ctrl+s")
    assert build_action("mouse_click", {"button": "middle"}) == MouseClick(
        button=MouseButton.MIDDLE
    )


def test_build_action_rejects_invalid_input_with_readable_errors() -> None:
    with pytest.raises(ValidationError):
        build_action("type_text", {"text": ""})
    with pytest.raises(ValidationError):
        build_action("key_press", {"key": "nonexistent-key"})
    with pytest.raises(ValidationError):
        build_action("mouse_move", {"x": -5, "y": 5, "relative": False})
    with pytest.raises(ValidationError):
        build_action("wait", {"duration_ms": -1})


def test_unknown_action_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_action("teleport", {})


def test_mouse_click_without_position_drops_coordinates() -> None:
    action = build_action("mouse_click", {"button": "left", "use_position": False, "x": 9, "y": 9})
    assert isinstance(action, MouseClick) and action.position is None


def test_mouse_move_optional_duration_stays_none() -> None:
    action = build_action("mouse_move", {"x": 1, "y": 2, "duration_ms": None})
    assert isinstance(action, MouseMove) and action.duration_ms is None


def test_action_row_text_numbers_rows_and_shows_delay_overrides() -> None:
    assert action_row_text(0, TypeText(text="hi")).startswith("1. type 'hi'")
    assert "+80 ms" in action_row_text(1, Wait(duration_ms=5, delay_after_ms=80))


# -- timing form ----------------------------------------------------------
def test_timing_values_round_trip() -> None:
    profile = TimingProfile(char_delay_ms=55, word_pause_ms=120)
    assert build_timing_profile(timing_to_values(profile)) == profile


def test_timing_form_rejects_min_greater_than_max() -> None:
    values = timing_to_values(TimingProfile())
    values["min_delay_ms"] = 400.0
    values["max_delay_ms"] = 100.0
    with pytest.raises(ValidationError) as excinfo:
        build_timing_profile(values)
    assert "min_delay_ms" in str(excinfo.value)


def test_timing_form_rejects_negative_values() -> None:
    values = timing_to_values(TimingProfile())
    values["char_delay_ms"] = -5.0
    with pytest.raises(ValidationError):
        build_timing_profile(values)


def test_preview_uses_the_timing_service_and_is_seed_stable() -> None:
    profile = TimingProfile(char_delay_ms=80, char_jitter_ms=30, min_delay_ms=20, max_delay_ms=200)
    first = preview_delays(profile, seed=7, count=5)
    second = preview_delays(profile, seed=7, count=5)
    assert first == second
    assert len(first) == 5


def test_preview_stays_within_configured_bounds() -> None:
    profile = TimingProfile(char_delay_ms=50, char_jitter_ms=500, min_delay_ms=10, max_delay_ms=60)
    delays = preview_delays(profile, seed=3, count=40, sample="abcdefgh")
    assert all(10 <= delay <= 60 for delay in delays)


def test_preview_varies_when_jitter_is_configured() -> None:
    profile = TimingProfile(char_delay_ms=80, char_jitter_ms=40, min_delay_ms=0, max_delay_ms=500)
    assert len(set(preview_delays(profile, seed=1, count=8, sample="abcdefgh"))) > 1


def test_preview_formatting() -> None:
    assert format_preview([63.2, 91.7]) == "63 ms  92 ms"
    assert format_preview([]) == "no delays configured"


# -- log formatting -------------------------------------------------------
def test_events_render_as_log_lines() -> None:
    stamp = datetime(2026, 9, 1, 21, 55, 2)
    line = format_event(RunStarted("demo", 3, False), timestamp=stamp)
    assert line is not None and line.startswith("21:55:02  Run started: demo, 3 action(s)")

    assert "DRY RUN" in str(format_event(RunStarted("demo", 1, True)))
    assert "Countdown started" in str(format_event(CountdownStarted(3)))
    assert "Starting in 2" in str(format_event(CountdownTick(2)))
    assert "cancelled" in str(format_event(CountdownCancelled()))
    started = ActionStarted(0, TypeText(text="hi"), "type 'hi'")
    assert "Action 1: type 'hi'" in str(format_event(started))
    assert "Paused before action 2" in str(format_event(RunPaused(1)))
    assert "Resumed at action 2" in str(format_event(RunResumed(1)))
    assert "focus confirmed" in str(format_event(TargetActivated(make_target(), True)))
    assert "focus not confirmed" in str(format_event(TargetActivated(make_target(), False)))
    assert "Run completed" in str(format_event(RunFinished(RunStatus.COMPLETED, 2, 15.0)))


def test_noisy_events_are_not_logged() -> None:
    from human_input_automation.core.events import ActionCompleted

    assert format_event(ActionCompleted(0, TypeText(text="hi"), 1.0)) is None


# -- error presentation ---------------------------------------------------
def report(status: RunStatus, error: str | None = None, **kwargs: object) -> RunReport:
    return RunReport(
        status=status, executed_actions=0, elapsed_ms=0.0, error=error, **kwargs  # type: ignore[arg-type]
    )


def test_friendly_errors_never_show_tracebacks() -> None:
    assert "Unable to activate" in friendly_error(
        report(RunStatus.FAILED, "could not activate target window Foo")
    )
    assert "did not take focus" in friendly_error(
        report(RunStatus.FAILED, "target window Foo did not take focus; aborting")
    )
    assert "permission" in friendly_error(
        report(RunStatus.FAILED, "pynput is not usable on this host")
    ).lower()
    assert friendly_error(report(RunStatus.STOPPED)) == "Automation stopped by user."
    assert "safety limit" in friendly_error(report(RunStatus.FAILED, "action limit of 5 reached"))


def test_friendly_error_for_unexpected_failure_mentions_the_log() -> None:
    assert "run log" in friendly_error(report(RunStatus.FAILED))


def test_friendly_error_lists_validation_problems() -> None:
    invalid = RunReport(
        status=RunStatus.INVALID,
        executed_actions=0,
        elapsed_ms=0.0,
        issues=(ValidationIssue("plan.no_actions", "the plan contains no actions"),),
    )
    assert "the plan contains no actions" in friendly_error(invalid)


def test_friendly_error_for_completed_dry_run() -> None:
    finished = RunReport(
        status=RunStatus.COMPLETED, executed_actions=3, elapsed_ms=1200.0, dry_run=True
    )
    message = friendly_error(finished)
    assert "3 action(s)" in message and "dry run" in message


# -- dry run view ---------------------------------------------------------
def test_dry_run_view_lists_actions_duration_and_warnings() -> None:
    finished = RunReport(
        status=RunStatus.COMPLETED,
        executed_actions=2,
        elapsed_ms=2500.0,
        dry_run=True,
        performed=("type 'hi' (2 chars)", "press enter"),
        issues=(
            ValidationIssue(
                "target.focused_window", "no explicit target", severity=Severity.WARNING
            ),
        ),
    )
    view = dry_run_view(finished, make_target(), delays=[70.0, 80.0])
    assert view.header == "DRY RUN - NO INPUT WILL BE SENT"
    assert "Test Window" in view.target_text
    assert "2.5 s" in view.estimated_duration
    assert view.lines[0].startswith("1. type 'hi'")
    assert any("Sample character delays" in line for line in view.lines)
    assert view.warnings == ("no explicit target",)


# -- typing style form ----------------------------------------------------
def test_switching_mistakes_off_and_on_keeps_the_pauses_from_the_file() -> None:
    """The panel edits two values; a hand-edited profile may carry more."""
    saved = TypingStyle(typo_rate=0.1, notice_pause_ms=999.0, correction_pause_ms=5.0)

    off = typing_style_with_rate(saved, enabled=False, percent=10.0)
    assert off.is_exact
    assert off.notice_pause_ms == 999.0

    back_on = typing_style_with_rate(off, enabled=True, percent=10.0)
    assert back_on.typo_rate == pytest.approx(0.1)
    assert back_on.notice_pause_ms == 999.0
    assert back_on.hesitation_rate > 0


def test_typing_style_values_offer_a_starting_rate_when_there_is_none() -> None:
    assert typing_style_to_values(TypingStyle()) == {
        "enabled": False,
        "percent": DEFAULT_TYPO_PERCENT,
    }
    assert typing_style_to_values(TypingStyle.natural(typo_rate=0.05)) == {
        "enabled": True,
        "percent": 5.0,
    }


def test_a_rate_outside_the_panel_range_is_clamped_not_rejected() -> None:
    assert typing_style_with_rate(TypingStyle(), enabled=True, percent=500.0).typo_rate == 1.0
    assert typing_style_with_rate(TypingStyle(), enabled=True, percent=-5.0).typo_rate == 0.0
