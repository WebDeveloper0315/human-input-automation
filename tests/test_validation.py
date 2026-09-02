"""Plan, target and action validation."""

from __future__ import annotations

from human_input_automation.core.actions import KeyDown, MouseDown, TypeText, Wait
from human_input_automation.core.plan import AutomationPlan, ExecutionLimits, RunOptions
from human_input_automation.core.screen import CoordinateSpace, MonitorInfo, ScreenGeometry
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile
from human_input_automation.core.validation import shortest_run_seconds, validate_plan

from .fakes import make_target


def codes(plan: AutomationPlan, **kwargs: object) -> set[str]:
    result = validate_plan(plan, **kwargs)  # type: ignore[arg-type]
    return {issue.code for issue in result.issues}


def test_valid_plan_has_no_errors() -> None:
    plan = AutomationPlan(make_target(), [TypeText(text="hello")])
    result = validate_plan(plan)
    assert result.ok
    assert result.errors == ()


def test_empty_plan_is_invalid() -> None:
    result = validate_plan(AutomationPlan(make_target(), []))
    assert not result.ok
    assert "plan.no_actions" in {issue.code for issue in result.errors}


def test_action_count_limit_is_enforced() -> None:
    plan = AutomationPlan(
        make_target(),
        [Wait(duration_ms=1) for _ in range(5)],
        limits=ExecutionLimits(max_actions=3),
    )
    assert "plan.too_many_actions" in codes(plan)


def test_text_length_limits_are_enforced_per_action_and_in_total() -> None:
    single = AutomationPlan(
        make_target(), [TypeText(text="x" * 50)], limits=ExecutionLimits(max_text_length=10)
    )
    assert "action.text_too_long" in codes(single)

    total = AutomationPlan(
        make_target(),
        [TypeText(text="x" * 30), TypeText(text="y" * 30)],
        limits=ExecutionLimits(max_text_length=100, max_total_characters=50),
    )
    assert "plan.too_much_text" in codes(total)


def test_a_source_file_sized_action_fits_the_default_limits() -> None:
    """20 000 characters is the point of the per-action limit, not its edge case."""
    limits = ExecutionLimits()
    assert limits.max_text_length == 20_000

    fits = AutomationPlan(make_target(), [TypeText(text="x" * limits.max_text_length)])
    assert validate_plan(fits).ok

    over = AutomationPlan(make_target(), [TypeText(text="x" * (limits.max_text_length + 1))])
    assert "action.text_too_long" in codes(over)


def test_the_default_limits_leave_room_for_several_full_actions() -> None:
    """A plan total equal to one action's cap would refuse the second one."""
    limits = ExecutionLimits()
    assert limits.max_total_characters >= limits.max_text_length * 2

    plan = AutomationPlan(
        make_target(), [TypeText(text="x" * limits.max_text_length) for _ in range(2)]
    )
    assert "plan.too_much_text" not in codes(plan)


def test_a_full_action_can_be_typed_inside_the_default_run_limit() -> None:
    """Raising the text limit without the duration limit only moves the failure.

    The duration limit is checked between actions, so it never cuts one short -
    it drops everything after it. A plan that types a full action at the default
    pace has to fit, or the limits contradict each other.
    """
    limits = ExecutionLimits()
    assert limits.max_run_duration_s is not None
    plan = AutomationPlan(make_target(), [TypeText(text="x" * limits.max_text_length)])
    assert shortest_run_seconds(plan) < limits.max_run_duration_s
    assert "plan.exceeds_run_limit" not in codes(plan)


def test_a_plan_that_cannot_finish_in_time_says_so_before_it_starts() -> None:
    plan = AutomationPlan(
        make_target(),
        [TypeText(text="x" * 5_000)],
        timing=TimingProfile(char_delay_ms=200, char_jitter_ms=0, max_delay_ms=400),
        limits=ExecutionLimits(max_run_duration_s=60),
    )
    result = validate_plan(plan)
    assert "plan.exceeds_run_limit" in codes(plan)
    # A warning, not an error: the run may still be worth starting.
    assert result.ok
    assert "1000 s" in "".join(issue.message for issue in result.warnings)


def test_the_shortest_run_counts_waits_and_the_fastest_possible_keystroke() -> None:
    timing = TimingProfile(
        char_delay_ms=100, char_jitter_ms=40, min_delay_ms=20, max_delay_ms=200
    )
    plan = AutomationPlan(
        make_target(),
        [TypeText(text="x" * 10), Wait(duration_ms=5_000)],
        timing=timing,
    )
    # 10 characters at 60 ms - the fastest the jitter allows - plus the wait.
    assert shortest_run_seconds(plan) == (10 * 60 + 5_000) / 1000


def test_the_shortest_run_of_an_instant_plan_is_nothing() -> None:
    plan = AutomationPlan(
        make_target(), [TypeText(text="x" * 100)], timing=TimingProfile.instant()
    )
    assert shortest_run_seconds(plan) == 0


def test_wait_longer_than_the_run_limit_is_rejected() -> None:
    plan = AutomationPlan(
        make_target(),
        [Wait(duration_ms=600_000)],
        limits=ExecutionLimits(max_run_duration_s=60),
    )
    assert "action.wait_exceeds_run_limit" in codes(plan)


def test_missing_target_handle_is_an_error() -> None:
    target = TargetWindow(handle="", capabilities=WindowCapabilities.full())
    result = validate_plan(AutomationPlan(target, [TypeText(text="hi")]))
    assert "target.missing_handle" in {issue.code for issue in result.errors}


def test_target_without_input_capability_blocks_a_real_run_but_allows_a_dry_run() -> None:
    target = TargetWindow(handle="w1", capabilities=WindowCapabilities(can_activate=True))
    real = validate_plan(AutomationPlan(target, [TypeText(text="hi")]))
    assert "target.no_input_capability" in {issue.code for issue in real.errors}

    dry = validate_plan(
        AutomationPlan(target, [TypeText(text="hi")], options=RunOptions(dry_run=True))
    )
    assert "target.no_input_capability" in {issue.code for issue in dry.warnings}
    assert dry.ok


def test_permission_and_focus_limitations_are_warnings_not_errors() -> None:
    target = TargetWindow(
        handle="w1",
        capabilities=WindowCapabilities(
            can_send_synthetic_input=True,
            can_activate=False,
            can_verify_focus=False,
            requires_permission="macOS Accessibility permission",
        ),
    )
    result = validate_plan(AutomationPlan(target, [TypeText(text="hi")]))
    assert result.ok
    warning_codes = {issue.code for issue in result.warnings}
    assert {
        "target.permission_required",
        "target.cannot_activate",
        "target.cannot_verify_focus",
    } <= warning_codes


def test_focused_window_target_is_allowed_with_a_warning() -> None:
    plan = AutomationPlan(TargetWindow.focused_window(), [TypeText(text="hi")])
    result = validate_plan(plan)
    assert result.ok
    assert "target.focused_window" in {issue.code for issue in result.warnings}


def test_target_from_another_platform_is_rejected() -> None:
    target = make_target()
    host = PlatformReport(
        platform=PlatformName.WINDOWS,
        display_server=DisplayServer.WINDOWS,
        capabilities=WindowCapabilities.full(),
    )
    result = validate_plan(AutomationPlan(target, [TypeText(text="hi")]), host=host)
    assert "target.platform_mismatch" in {issue.code for issue in result.errors}


def test_unbalanced_key_and_button_holds_are_warnings() -> None:
    plan = AutomationPlan(make_target(), [KeyDown(key="shift"), MouseDown()])
    result = validate_plan(plan)
    assert result.ok
    codes_found = {issue.code for issue in result.warnings}
    assert {"plan.unbalanced_keys", "plan.unbalanced_buttons"} <= codes_found


# -- platform key gaps ----------------------------------------------------
def macos_host(**kwargs: object) -> PlatformReport:
    from human_input_automation.adapters.platform_info import describe_host

    return describe_host(
        PlatformName.MACOS, DisplayServer.QUARTZ, env={}, accessibility_trusted=True, **kwargs  # type: ignore[arg-type]
    )


def test_a_key_the_platform_cannot_send_is_rejected_before_the_run() -> None:
    """pynput's macOS backend has no `insert` key: fail up front, not mid-plan."""
    from human_input_automation.core.actions import KeyPress

    plan = AutomationPlan(make_target(), [KeyPress(key="insert")])
    result = validate_plan(plan, host=macos_host())
    assert not result.ok
    issue = next(i for i in result.errors if i.code == "action.key_unsupported")
    assert "insert" in issue.message and "macos" in issue.message


def test_the_same_key_is_fine_on_platforms_that_have_it() -> None:
    from human_input_automation.adapters.platform_info import describe_host
    from human_input_automation.core.actions import KeyPress

    windows = describe_host(PlatformName.WINDOWS, DisplayServer.WINDOWS, env={})
    plan = AutomationPlan(
        TargetWindow(
            handle="w1", platform=PlatformName.WINDOWS, capabilities=WindowCapabilities.full()
        ),
        [KeyPress(key="insert")],
    )
    assert validate_plan(plan, host=windows).ok


def test_unsupported_keys_are_caught_inside_shortcuts_and_holds() -> None:
    from human_input_automation.core.actions import KeyDown, Shortcut

    host = macos_host()
    for action in (Shortcut(keys=("ctrl", "insert")), KeyDown(key="insert")):
        result = validate_plan(AutomationPlan(make_target(), [action]), host=host)
        assert any(i.code == "action.key_unsupported" for i in result.errors)


# -- coordinate validation ------------------------------------------------
def two_monitor_desktop() -> ScreenGeometry:
    return ScreenGeometry(
        monitors=(
            MonitorInfo("primary", 0, 0, 1920, 1080, is_primary=True),
            MonitorInfo("second", 1920, 0, 1920, 1080),
        ),
        coordinate_space=CoordinateSpace.PHYSICAL,
    )


def test_coordinates_on_a_second_monitor_are_accepted() -> None:
    from human_input_automation.core.actions import MouseMove

    plan = AutomationPlan(make_target(), [MouseMove(x=2500, y=500)])
    assert validate_plan(plan, screen=two_monitor_desktop()).ok


def test_coordinates_beyond_every_monitor_are_rejected_with_the_bounds() -> None:
    from human_input_automation.core.actions import MouseMove

    plan = AutomationPlan(make_target(), [MouseMove(x=5000, y=500)])
    result = validate_plan(plan, screen=two_monitor_desktop())
    issue = next(i for i in result.errors if i.code == "action.coordinates_off_screen")
    assert "(0, 0) to (3840, 1080)" in issue.message
    assert "physical" in issue.message


def test_click_coordinates_are_validated_too() -> None:
    from human_input_automation.core.actions import MouseClick

    plan = AutomationPlan(make_target(), [MouseClick(x=4000, y=10)])
    assert not validate_plan(plan, screen=two_monitor_desktop()).ok


def test_relative_movement_is_never_bounds_checked() -> None:
    from human_input_automation.core.actions import MouseMove

    plan = AutomationPlan(make_target(), [MouseMove(x=-9999, y=-9999, relative=True)])
    assert validate_plan(plan, screen=two_monitor_desktop()).ok


def test_clicks_without_coordinates_are_never_bounds_checked() -> None:
    from human_input_automation.core.actions import MouseClick

    plan = AutomationPlan(make_target(), [MouseClick()])
    assert validate_plan(plan, screen=two_monitor_desktop()).ok


def test_unknown_geometry_disables_coordinate_validation() -> None:
    from human_input_automation.core.actions import MouseMove

    plan = AutomationPlan(make_target(), [MouseMove(x=99_999, y=99_999)])
    assert validate_plan(plan, screen=ScreenGeometry.unknown("no backend")).ok
    assert validate_plan(plan).ok


def test_a_gap_between_monitors_is_rejected() -> None:
    from human_input_automation.core.actions import MouseMove

    detached = ScreenGeometry(
        monitors=(
            MonitorInfo("primary", 0, 0, 1920, 1080, is_primary=True),
            MonitorInfo("far", 3000, 0, 1920, 1080),
        ),
        coordinate_space=CoordinateSpace.PHYSICAL,
    )
    plan = AutomationPlan(make_target(), [MouseMove(x=2500, y=500)])
    assert not validate_plan(plan, screen=detached).ok


# -- host capability gating ----------------------------------------------
def wayland_host() -> PlatformReport:
    """GNOME/Wayland with XWayland: keyboard works, the pointer cannot be moved."""
    from human_input_automation.adapters.platform_info import describe_host

    return describe_host(
        PlatformName.LINUX, DisplayServer.WAYLAND, env={"DISPLAY": ":0"}
    )


def test_mouse_actions_are_rejected_where_the_pointer_cannot_be_moved() -> None:
    """Regression: measured on GNOME/Wayland, XTEST pointer warping is ignored.

    A click would land wherever the pointer already happens to be - which may be
    any window at all - so the plan must be refused rather than aimed blindly.
    """
    from human_input_automation.core.actions import MouseClick, MouseDown, MouseMove, MouseUp

    host = wayland_host()
    for action in (MouseMove(x=10, y=10), MouseClick(), MouseDown(), MouseUp()):
        plan = AutomationPlan(make_target(), [action])
        result = validate_plan(plan, host=host)
        issue = next(
            (i for i in result.errors if i.code == "action.capability_unavailable"), None
        )
        assert issue is not None, f"{action.describe()} should be refused"
        assert "pointer" in issue.message


def test_keyboard_actions_are_still_allowed_on_wayland() -> None:
    """Keyboard follows focus, which the compositor does let us set."""
    from human_input_automation.core.actions import KeyPress, TypeText

    host = wayland_host()
    target = make_target(capabilities=host.capabilities)
    plan = AutomationPlan(target, [TypeText(text="hello"), KeyPress(key="enter")])
    assert validate_plan(plan, host=host).ok


def test_mouse_actions_are_allowed_where_the_pointer_works() -> None:
    from human_input_automation.adapters.platform_info import describe_host
    from human_input_automation.core.actions import MouseClick

    host = describe_host(PlatformName.LINUX, DisplayServer.X11, env={"DISPLAY": ":0"})
    plan = AutomationPlan(make_target(), [MouseClick(x=10, y=10)])
    assert validate_plan(plan, host=host).ok
