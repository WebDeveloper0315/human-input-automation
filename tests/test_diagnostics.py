"""The --diagnose report: complete, honest, and guaranteed input-free."""

from __future__ import annotations

import pytest

from human_input_automation.adapters.hotkeys import HotkeySupport
from human_input_automation.adapters.platform_info import describe_host
from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.adapters.screens import NullScreens, PyMonCtlScreens
from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.core.capabilities import CapabilityName
from human_input_automation.core.keys import KeyLike, MouseButton
from human_input_automation.core.screen import CoordinateSpace, MonitorInfo, ScreenGeometry
from human_input_automation.core.target import DisplayServer, PlatformName
from human_input_automation.diagnostics import Diagnostics

from .fakes import FakeHotkey, FakeMouse, FakeWindows, make_target


class ExplodingKeyboard:
    """Any use of this keyboard fails the test - diagnostics must send nothing."""

    def type_text(self, text: str) -> None:
        raise AssertionError("diagnostics must never send input")

    def key_down(self, key: KeyLike) -> None:
        raise AssertionError("diagnostics must never send input")

    def key_up(self, key: KeyLike) -> None:
        raise AssertionError("diagnostics must never send input")


class ExplodingMouse(FakeMouse):
    def move_to(self, x: int, y: int, duration_ms: float, cancel: object = None) -> None:
        raise AssertionError("diagnostics must never move the pointer")

    def button_down(self, button: MouseButton) -> None:
        raise AssertionError("diagnostics must never click")


def adapters(
    platform: PlatformName = PlatformName.LINUX,
    display: DisplayServer = DisplayServer.X11,
    env: dict[str, str] | None = None,
    screens: object | None = None,
    accessibility: bool | None = None,
    problems: tuple[str, ...] = (),
) -> AdapterSet:
    host = describe_host(platform, display, env=env or {}, accessibility_trusted=accessibility)
    return AdapterSet(
        keyboard=ExplodingKeyboard(),
        mouse=ExplodingMouse(),
        windows=FakeWindows(windows=[make_target()]),
        discovery=FakeWindows(windows=[make_target()]),
        clock=SystemClock(),
        host=host,
        screens=screens or NullScreens(),  # type: ignore[arg-type]
        window_backend="x11",
        hotkey=FakeHotkey(),
        hotkey_support=HotkeySupport(True, "Global hotkey supported on X11."),
        problems=problems,
    )


def test_diagnostics_send_no_input() -> None:
    """The keyboard and mouse would raise if diagnostics touched them."""
    report = Diagnostics.collect(adapters()).render()
    assert "No input was generated." in report


def test_every_capability_appears_with_a_state() -> None:
    report = Diagnostics.collect(adapters()).render()
    for name in CapabilityName:
        assert name.value in report


def test_the_report_states_platform_display_server_and_backend() -> None:
    report = Diagnostics.collect(adapters()).render()
    assert "Platform: linux" in report
    assert "Display server: x11" in report
    assert "Window backend: x11" in report


def test_wayland_reasons_are_explained() -> None:
    report = Diagnostics.collect(
        adapters(PlatformName.LINUX, DisplayServer.WAYLAND)
    ).render()
    assert "window_enumeration" in report
    assert "unavailable" in report
    assert "Wayland" in report


def test_macos_permissions_name_where_to_grant_them() -> None:
    report = Diagnostics.collect(
        adapters(PlatformName.MACOS, DisplayServer.QUARTZ, accessibility=False)
    ).render()
    assert "macOS Accessibility permission" in report
    assert "System Settings > Privacy & Security > Accessibility" in report
    assert "restart the application after granting" in report


def test_macos_lists_the_key_it_cannot_send() -> None:
    report = Diagnostics.collect(
        adapters(PlatformName.MACOS, DisplayServer.QUARTZ, accessibility=True)
    ).render()
    assert "Keys unavailable on this platform: insert" in report


def test_monitor_layout_is_reported_when_known() -> None:
    geometry = ScreenGeometry(
        monitors=(
            MonitorInfo("HDMI-2", 0, 0, 1920, 1080, is_primary=True),
            MonitorInfo("DP-1", 1920, 0, 1920, 1080),
        ),
        coordinate_space=CoordinateSpace.PHYSICAL,
    )

    class FixedScreens:
        def geometry(self) -> ScreenGeometry:
            return geometry

    report = Diagnostics.collect(adapters(screens=FixedScreens())).render()
    assert "virtual desktop 3840x1080" in report
    assert "HDMI-2 (primary)" in report
    assert "scale unknown" in report


def test_unknown_geometry_is_reported_as_unknown() -> None:
    report = Diagnostics.collect(adapters()).render()
    assert "screen geometry unknown" in report


def test_adapter_problems_are_listed() -> None:
    report = Diagnostics.collect(adapters(problems=("pynput is not usable",))).render()
    assert "Adapter problems:" in report
    assert "pynput is not usable" in report


@pytest.mark.parametrize(
    ("platform", "display", "expected"),
    [
        (PlatformName.LINUX, DisplayServer.X11, 0),
        (PlatformName.LINUX, DisplayServer.WAYLAND, 1),
        (PlatformName.WINDOWS, DisplayServer.WINDOWS, 0),
        (PlatformName.UNKNOWN, DisplayServer.UNKNOWN, 1),
    ],
)
def test_exit_code_follows_whether_input_can_be_attempted(
    platform: PlatformName, display: DisplayServer, expected: int
) -> None:
    assert Diagnostics.collect(adapters(platform, display)).exit_code == expected


def test_collect_records_the_host_environment() -> None:
    diagnostics = Diagnostics.collect(adapters())
    assert diagnostics.os_name
    assert diagnostics.python_version
    assert diagnostics.window_backend == "x11"


def test_real_pymonctl_adapter_is_not_used_by_the_report_when_absent() -> None:
    screens = PyMonCtlScreens(PlatformName.LINUX, None)
    screens._module = None
    report = Diagnostics.collect(adapters(screens=screens)).render()
    assert "not installed" in report
