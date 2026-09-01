"""Platform detection and capability reporting, simulated for every platform."""

from __future__ import annotations

import pytest

from human_input_automation.adapters.platform_info import (
    MACOS_ACCESSIBILITY,
    MACOS_INPUT_MONITORING,
    describe_host,
    detect_display_server,
    detect_platform,
    has_xwayland,
)
from human_input_automation.core.capabilities import CapabilityName, CapabilityState
from human_input_automation.core.target import DisplayServer, PlatformName


@pytest.mark.parametrize(
    ("platform_id", "expected"),
    [
        ("win32", PlatformName.WINDOWS),
        ("darwin", PlatformName.MACOS),
        ("linux", PlatformName.LINUX),
        ("freebsd13", PlatformName.UNKNOWN),
    ],
)
def test_platform_detection(platform_id: str, expected: PlatformName) -> None:
    assert detect_platform(platform_id) is expected


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"XDG_SESSION_TYPE": "wayland"}, DisplayServer.WAYLAND),
        ({"WAYLAND_DISPLAY": "wayland-0"}, DisplayServer.WAYLAND),
        ({"XDG_SESSION_TYPE": "x11"}, DisplayServer.X11),
        ({"DISPLAY": ":0"}, DisplayServer.X11),
        ({}, DisplayServer.UNKNOWN),
    ],
)
def test_linux_display_server_detection(env: dict[str, str], expected: DisplayServer) -> None:
    assert detect_display_server(PlatformName.LINUX, env) is expected


def test_windows_and_macos_display_servers_are_implied() -> None:
    assert detect_display_server(PlatformName.WINDOWS, {}) is DisplayServer.WINDOWS
    assert detect_display_server(PlatformName.MACOS, {}) is DisplayServer.QUARTZ


def test_windows_reports_full_capabilities() -> None:
    report = describe_host(PlatformName.WINDOWS, DisplayServer.WINDOWS, env={})
    assert report.capabilities.can_enumerate
    assert report.capabilities.can_activate
    assert report.capabilities.can_verify_focus
    assert report.can_automate


def test_macos_reports_the_accessibility_permission_when_it_is_missing() -> None:
    report = describe_host(
        PlatformName.MACOS, DisplayServer.QUARTZ, env={}, accessibility_trusted=False
    )
    assert report.missing_permissions
    assert not report.capabilities.can_send_synthetic_input
    assert report.capabilities.requires_permission


def test_macos_with_permission_granted_can_automate() -> None:
    report = describe_host(
        PlatformName.MACOS, DisplayServer.QUARTZ, env={}, accessibility_trusted=True
    )
    assert report.can_automate
    assert not report.missing_permissions


def test_linux_x11_can_automate() -> None:
    report = describe_host(PlatformName.LINUX, DisplayServer.X11, env={"DISPLAY": ":0"})
    assert report.can_automate
    assert report.capabilities.can_enumerate


def test_wayland_reports_restricted_capabilities() -> None:
    report = describe_host(PlatformName.LINUX, DisplayServer.WAYLAND, env={})
    assert not report.capabilities.can_enumerate
    assert not report.capabilities.can_activate
    assert not report.can_automate
    assert report.warnings


def test_wayland_with_xwayland_may_reach_x11_clients_only() -> None:
    report = describe_host(
        PlatformName.LINUX, DisplayServer.WAYLAND, env={"DISPLAY": ":0"}
    )
    assert report.capabilities.can_send_synthetic_input
    assert not report.capabilities.can_activate
    assert any("XWayland" in warning for warning in report.warnings)


def test_unknown_platform_is_reported_honestly() -> None:
    report = describe_host(PlatformName.UNKNOWN, DisplayServer.UNKNOWN, env={})
    assert not report.can_automate
    assert report.warnings


# -- capability matrix ----------------------------------------------------
def test_windows_matrix_is_fully_available() -> None:
    matrix = describe_host(PlatformName.WINDOWS, DisplayServer.WINDOWS, env={}).matrix
    assert all(capability.state is CapabilityState.AVAILABLE for capability in matrix)
    assert matrix.missing_permissions() == ()


def test_x11_matrix_is_available_except_for_scaling() -> None:
    matrix = describe_host(PlatformName.LINUX, DisplayServer.X11, env={"DISPLAY": ":0"}).matrix
    assert matrix.state(CapabilityName.WINDOW_ENUMERATION) is CapabilityState.AVAILABLE
    assert matrix.state(CapabilityName.GLOBAL_HOTKEY) is CapabilityState.AVAILABLE
    assert matrix.state(CapabilityName.MULTI_MONITOR) is CapabilityState.RESTRICTED


def test_wayland_matrix_marks_window_control_unavailable() -> None:
    matrix = describe_host(PlatformName.LINUX, DisplayServer.WAYLAND, env={}).matrix
    for name in (
        CapabilityName.WINDOW_ENUMERATION,
        CapabilityName.WINDOW_ACTIVATION,
        CapabilityName.FOCUS_VERIFICATION,
        CapabilityName.KEYBOARD_INPUT,
        CapabilityName.GLOBAL_HOTKEY,
    ):
        assert matrix.state(name) is CapabilityState.UNAVAILABLE, name


def test_xwayland_upgrades_input_and_enumeration_to_restricted_only() -> None:
    """Verified on Ubuntu 26.04 GNOME/Wayland: X11 clients are visible, others are not."""
    matrix = describe_host(
        PlatformName.LINUX, DisplayServer.WAYLAND, env={"DISPLAY": ":0"}
    ).matrix
    assert matrix.state(CapabilityName.WINDOW_ENUMERATION) is CapabilityState.RESTRICTED
    assert matrix.state(CapabilityName.KEYBOARD_INPUT) is CapabilityState.RESTRICTED
    assert matrix.state(CapabilityName.WINDOW_ACTIVATION) is CapabilityState.UNAVAILABLE
    assert matrix.state(CapabilityName.GLOBAL_HOTKEY) is CapabilityState.UNAVAILABLE


def test_macos_separates_accessibility_from_input_monitoring() -> None:
    """Two different permissions: holding one does not imply the other."""
    report = describe_host(
        PlatformName.MACOS,
        DisplayServer.QUARTZ,
        env={},
        accessibility_trusted=True,
        input_monitoring_trusted=False,
    )
    matrix = report.matrix
    assert matrix.state(CapabilityName.KEYBOARD_INPUT) is CapabilityState.AVAILABLE
    assert matrix.state(CapabilityName.GLOBAL_HOTKEY) is CapabilityState.DENIED
    assert matrix.get(CapabilityName.GLOBAL_HOTKEY).permission == MACOS_INPUT_MONITORING
    assert report.missing_permissions == (MACOS_INPUT_MONITORING,)


def test_macos_accessibility_denial_names_the_setting_and_the_restart() -> None:
    report = describe_host(
        PlatformName.MACOS, DisplayServer.QUARTZ, env={}, accessibility_trusted=False
    )
    capability = report.matrix.get(CapabilityName.KEYBOARD_INPUT)
    assert capability.state is CapabilityState.DENIED
    assert capability.permission == MACOS_ACCESSIBILITY
    assert "Accessibility" in (capability.permission_category or "")
    assert capability.requires_restart


def test_macos_permission_that_cannot_be_probed_is_unknown_not_denied() -> None:
    report = describe_host(
        PlatformName.MACOS,
        DisplayServer.QUARTZ,
        env={},
        accessibility_trusted=None,
        input_monitoring_trusted=None,
    )
    assert report.matrix.state(CapabilityName.KEYBOARD_INPUT) is CapabilityState.UNKNOWN
    assert report.missing_permissions == ()
    assert report.can_automate, "unknown must let the user try"


def test_unknown_platform_has_no_adapter_and_says_so() -> None:
    matrix = describe_host(PlatformName.UNKNOWN, DisplayServer.UNKNOWN, env={}).matrix
    assert matrix.state(CapabilityName.KEYBOARD_INPUT) is CapabilityState.UNAVAILABLE
    assert "no platform adapter" in matrix.reason(CapabilityName.KEYBOARD_INPUT)


def test_platform_key_gaps_are_carried_on_the_report() -> None:
    macos = describe_host(PlatformName.MACOS, DisplayServer.QUARTZ, env={})
    windows = describe_host(PlatformName.WINDOWS, DisplayServer.WINDOWS, env={})
    assert [key.value for key in macos.unsupported_keys] == ["insert"]
    assert windows.unsupported_keys == ()


def test_xwayland_detection() -> None:
    assert has_xwayland({"DISPLAY": ":0"})
    assert not has_xwayland({})
