"""Adapter selection: capability-driven, degrading safely."""

from __future__ import annotations

import pytest

from human_input_automation.adapters.null import NullKeyboard, NullMouse, NullWindowBackend
from human_input_automation.adapters.platform_info import describe_host
from human_input_automation.adapters.registry import (
    build_adapters,
    build_window_adapter,
    select_window_backend,
)
from human_input_automation.core.errors import AdapterUnavailableError
from human_input_automation.core.target import DisplayServer, PlatformName, PlatformReport


def host(
    platform: PlatformName, display: DisplayServer, env: dict[str, str] | None = None
) -> PlatformReport:
    return describe_host(platform, display, env=env or {})


@pytest.mark.parametrize(
    ("platform", "display", "expected"),
    [
        (PlatformName.WINDOWS, DisplayServer.WINDOWS, "pywinctl"),
        (PlatformName.MACOS, DisplayServer.QUARTZ, "pywinctl"),
        (PlatformName.LINUX, DisplayServer.X11, "x11"),
        (PlatformName.UNKNOWN, DisplayServer.UNKNOWN, "none"),
    ],
)
def test_backend_selection_per_platform(
    platform: PlatformName, display: DisplayServer, expected: str
) -> None:
    assert select_window_backend(host(platform, display)) == expected


def test_linux_x11_and_wayland_do_not_get_the_same_treatment() -> None:
    """The whole point of selecting on capability rather than OS name."""
    x11 = host(PlatformName.LINUX, DisplayServer.X11)
    wayland = host(PlatformName.LINUX, DisplayServer.WAYLAND)
    assert select_window_backend(x11) == "x11"
    assert select_window_backend(wayland) == "none"
    assert x11.capabilities.can_activate
    assert not wayland.capabilities.can_activate


def test_wayland_with_xwayland_uses_the_x11_backend_for_x11_clients() -> None:
    """Measured on GNOME/Wayland: XWayland windows can be listed and focused."""
    xwayland = host(PlatformName.LINUX, DisplayServer.WAYLAND, {"DISPLAY": ":0"})
    assert select_window_backend(xwayland) == "x11"
    assert xwayland.capabilities.can_enumerate
    assert xwayland.capabilities.can_activate
    assert xwayland.capabilities.can_verify_focus


def test_wayland_without_xwayland_has_no_window_backend() -> None:
    bare = host(PlatformName.LINUX, DisplayServer.WAYLAND, {})
    assert select_window_backend(bare) == "none"
    assert not bare.capabilities.can_activate


def test_macos_without_automation_permission_gets_no_window_backend() -> None:
    """Window listing on macOS is gated by Automation, not Accessibility.

    pywinctl drives window enumeration and activation through AppleScript to
    System Events, so Accessibility being granted says nothing about whether
    windows can be listed.
    """
    denied = describe_host(
        PlatformName.MACOS,
        DisplayServer.QUARTZ,
        env={},
        accessibility_trusted=True,
        automation_trusted=False,
    )
    assert select_window_backend(denied) == "none"


def test_macos_without_accessibility_can_still_list_windows() -> None:
    """Input is blocked, but the window list is a different permission."""
    host = describe_host(
        PlatformName.MACOS,
        DisplayServer.QUARTZ,
        env={},
        accessibility_trusted=False,
        automation_trusted=True,
    )
    assert select_window_backend(host) == "pywinctl"
    assert not host.capabilities.can_send_synthetic_input


def test_building_an_unavailable_backend_raises_with_the_reason() -> None:
    wayland = host(PlatformName.LINUX, DisplayServer.WAYLAND)
    with pytest.raises(AdapterUnavailableError) as excinfo:
        build_window_adapter(wayland)
    assert "Wayland" in str(excinfo.value)


def test_build_adapters_without_desktop_libraries_degrades_to_null_adapters() -> None:
    adapters = build_adapters(allow_desktop=False)
    assert isinstance(adapters.keyboard, NullKeyboard)
    assert isinstance(adapters.mouse, NullMouse)
    assert not adapters.is_functional
    assert adapters.window_backend == "none"
    assert adapters.host is not None


def test_build_adapters_reports_problems_instead_of_raising() -> None:
    """Never raises, whatever is installed: problems are data, not exceptions."""
    adapters = build_adapters(allow_desktop=False)
    assert adapters.host is not None
    assert adapters.clock is not None
    assert isinstance(adapters.windows, (type(None), NullWindowBackend))
    assert isinstance(adapters.problems, tuple)
    adapters.close()


@pytest.mark.manual
@pytest.mark.linux
def test_real_adapters_on_this_host() -> None:
    """Builds the real adapters for whatever machine this runs on.

    Marked ``manual``: it touches the installed desktop libraries, so it is not
    part of the CI suite. Run it with ``pytest -m manual``.
    """
    adapters = build_adapters()
    try:
        assert adapters.host.platform is not None
        assert adapters.window_backend in {"none", "x11", "pywinctl"}
    finally:
        adapters.close()


def test_geometry_is_always_answerable() -> None:
    adapters = build_adapters(allow_desktop=False)
    geometry = adapters.geometry()
    assert geometry is not None
    assert not geometry.is_known or geometry.monitors
    adapters.close()
