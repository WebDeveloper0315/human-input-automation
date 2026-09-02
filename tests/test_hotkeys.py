"""Global emergency-stop hotkey: capability reporting and wiring."""

from __future__ import annotations

import time

import pytest

from human_input_automation.adapters.hotkeys import (
    NullHotkey,
    describe_hotkey_support,
)
from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.service import AutomationService
from human_input_automation.core.actions import TypeText, Wait
from human_input_automation.core.events import RunStatus
from human_input_automation.core.plan import AutomationPlan
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile

from .fakes import FakeHotkey, FakeKeyboard, FakeMouse, FakeWindows, make_target


def host(
    platform: PlatformName,
    display: DisplayServer = DisplayServer.UNKNOWN,
    **kwargs: object,
) -> PlatformReport:
    return PlatformReport(
        platform=platform,
        display_server=display,
        capabilities=WindowCapabilities.full(),
        **kwargs,  # type: ignore[arg-type]
    )


def test_windows_and_x11_support_a_global_hotkey() -> None:
    assert describe_hotkey_support(host(PlatformName.WINDOWS)).available is True
    assert (
        describe_hotkey_support(host(PlatformName.LINUX, DisplayServer.X11)).available is True
    )


def test_wayland_is_reported_as_unsupported_with_a_reason() -> None:
    support = describe_hotkey_support(host(PlatformName.LINUX, DisplayServer.WAYLAND))
    assert support.available is False and support.is_known_unsupported
    assert "Wayland" in support.reason


def test_macos_hotkey_support_follows_the_probed_input_monitoring_state() -> None:
    """Verified on a real Mac: CGPreflightListenEventAccess answers definitively.

    Before this, macOS always reported "may require Input Monitoring" even when
    the permission had been granted and the capability probe said available.
    """
    from human_input_automation.adapters.platform_info import describe_host

    granted = describe_hotkey_support(
        describe_host(
            PlatformName.MACOS, DisplayServer.QUARTZ, env={}, input_monitoring_trusted=True
        )
    )
    assert granted.available is True

    denied = describe_hotkey_support(
        describe_host(
            PlatformName.MACOS, DisplayServer.QUARTZ, env={}, input_monitoring_trusted=False
        )
    )
    assert denied.available is False
    assert "Input Monitoring" in denied.reason

    unknown = describe_hotkey_support(
        describe_host(
            PlatformName.MACOS, DisplayServer.QUARTZ, env={}, input_monitoring_trusted=None
        )
    )
    assert unknown.available is None, "unknown must not be reported as no"


def test_unknown_platform_reports_unknown() -> None:
    assert describe_hotkey_support(host(PlatformName.UNKNOWN)).available is None


def test_null_hotkey_never_registers() -> None:
    hotkey = NullHotkey()
    assert hotkey.start(lambda: None) is False
    assert hotkey.is_active is False
    hotkey.stop()  # safe when never started


def build_service(hotkey: FakeHotkey) -> tuple[AutomationService, FakeKeyboard]:
    keyboard = FakeKeyboard()
    windows = FakeWindows(windows=[make_target()])
    adapters = AdapterSet(
        keyboard=keyboard,
        mouse=FakeMouse(),
        windows=windows,
        discovery=windows,
        clock=SystemClock(),
        host=host(PlatformName.LINUX, DisplayServer.X11),
        hotkey=hotkey,
    )
    return AutomationService(adapters), keyboard


def test_the_hotkey_stops_a_running_plan() -> None:
    hotkey = FakeHotkey()
    service, keyboard = build_service(hotkey)
    assert service.enable_emergency_hotkey() is True

    plan = AutomationPlan(
        make_target(),
        [Wait(duration_ms=30_000), TypeText(text="never")],
        timing=TimingProfile.instant(),
    )
    service.start(plan)
    time.sleep(0.05)

    started = time.monotonic()
    hotkey.trigger()
    report = service.join(5.0)

    assert report is not None and report.status is RunStatus.EMERGENCY_STOPPED
    assert time.monotonic() - started < 2.0
    assert keyboard.typed == ""


def test_the_hotkey_can_never_start_a_run() -> None:
    hotkey = FakeHotkey()
    service, keyboard = build_service(hotkey)
    service.enable_emergency_hotkey()

    hotkey.trigger()  # nothing is running
    time.sleep(0.05)

    assert not service.is_running
    assert keyboard.calls == []


def test_the_ui_callback_runs_in_addition_to_the_stop() -> None:
    hotkey = FakeHotkey()
    service, _ = build_service(hotkey)
    notified: list[int] = []
    service.enable_emergency_hotkey(lambda: notified.append(1))
    hotkey.trigger()
    assert notified == [1]


def test_a_refused_registration_is_reported() -> None:
    hotkey = FakeHotkey(can_register=False)
    service, _ = build_service(hotkey)
    assert service.enable_emergency_hotkey() is False


def test_disabling_the_hotkey_stops_the_listener() -> None:
    hotkey = FakeHotkey()
    service, _ = build_service(hotkey)
    service.enable_emergency_hotkey()
    service.disable_emergency_hotkey()
    assert hotkey.stopped and not hotkey.is_active


@pytest.mark.parametrize("platform", list(PlatformName))
def test_support_is_described_for_every_platform(platform: PlatformName) -> None:
    support = describe_hotkey_support(host(platform))
    assert support.reason
    assert support.available in (True, False, None)


# -- combination shapes that pynput does not match ------------------------
def test_the_default_combination_avoids_the_shapes_that_never_fire() -> None:
    """Regression: the previous default, Ctrl+Alt+., could never fire.

    Measured against a real X server in Phase 6: combinations holding Ctrl and
    Alt together never fire, and character keys do not match once a modifier is
    held. The old default did both.
    """
    from human_input_automation.adapters.hotkeys import (
        DEFAULT_EMERGENCY_HOTKEY,
        problematic_combination,
    )

    assert problematic_combination(DEFAULT_EMERGENCY_HOTKEY) is None


@pytest.mark.parametrize(
    "combination", ["<ctrl>+<alt>+.", "<ctrl>+<alt>+q", "<ctrl>+<alt>+<f9>", "<alt>+<ctrl>+<f10>"]
)
def test_ctrl_alt_combinations_are_flagged(combination: str) -> None:
    from human_input_automation.adapters.hotkeys import problematic_combination

    problem = problematic_combination(combination)
    assert problem is not None and "Ctrl and Alt" in problem


@pytest.mark.parametrize("combination", ["<ctrl>+.", "<shift>+q", "<ctrl>+<shift>+p"])
def test_character_key_combinations_are_flagged(combination: str) -> None:
    from human_input_automation.adapters.hotkeys import problematic_combination

    problem = problematic_combination(combination)
    assert problem is not None and "character keys" in problem


@pytest.mark.parametrize(
    "combination",
    ["<ctrl>+<shift>+<f9>", "<ctrl>+<f9>", "<alt>+<f9>", "<shift>+<f10>", "<f9>"],
)
def test_verified_working_shapes_are_not_flagged(combination: str) -> None:
    """These fired reliably against a real X server."""
    from human_input_automation.adapters.hotkeys import problematic_combination

    assert problematic_combination(combination) is None
