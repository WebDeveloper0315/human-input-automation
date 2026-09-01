"""Platform detection and capability reporting, simulated for every platform."""

from __future__ import annotations

import pytest

from human_input_automation.adapters.platform_info import (
    describe_host,
    detect_display_server,
    detect_platform,
)
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
