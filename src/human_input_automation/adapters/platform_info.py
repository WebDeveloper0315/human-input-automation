"""Host platform and capability detection.

The detection functions take their inputs as arguments so they can be unit
tested for every platform from any machine - no real Windows, macOS or Wayland
session required in CI.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from ..core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)

MACOS_PERMISSION = "macOS Accessibility permission (System Settings > Privacy & Security)"

WAYLAND_NOTE = (
    "Wayland compositors restrict global synthetic input and window control by design; "
    "window enumeration, activation and focus verification are usually unavailable"
)


def detect_platform(platform_id: str | None = None) -> PlatformName:
    """Map ``sys.platform`` onto :class:`PlatformName`."""
    value = (platform_id if platform_id is not None else sys.platform).lower()
    if value.startswith("win"):
        return PlatformName.WINDOWS
    if value == "darwin":
        return PlatformName.MACOS
    if value.startswith("linux"):
        return PlatformName.LINUX
    return PlatformName.UNKNOWN


def detect_display_server(
    platform: PlatformName, env: Mapping[str, str] | None = None
) -> DisplayServer:
    """Determine the windowing system, which decides what is possible on Linux."""
    if platform is PlatformName.WINDOWS:
        return DisplayServer.WINDOWS
    if platform is PlatformName.MACOS:
        return DisplayServer.QUARTZ
    if platform is not PlatformName.LINUX:
        return DisplayServer.UNKNOWN

    environ = env if env is not None else os.environ
    session = environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" or environ.get("WAYLAND_DISPLAY"):
        return DisplayServer.WAYLAND
    if session == "x11" or environ.get("DISPLAY"):
        return DisplayServer.X11
    return DisplayServer.UNKNOWN


def macos_accessibility_trusted() -> bool | None:
    """Whether this process holds macOS Accessibility permission.

    Returns ``None`` when it cannot be determined (no PyObjC available, or not
    running on macOS). ``None`` means unknown, never "denied".
    """
    if detect_platform() is not PlatformName.MACOS:
        return None
    try:  # PyObjC ships with several macOS Python distributions; it is optional here.
        from ApplicationServices import AXIsProcessTrusted
    except Exception:
        return None
    try:
        return bool(AXIsProcessTrusted())
    except Exception:  # pragma: no cover - macOS only
        return None


def describe_host(
    platform: PlatformName | None = None,
    display_server: DisplayServer | None = None,
    env: Mapping[str, str] | None = None,
    accessibility_trusted: bool | None = None,
) -> PlatformReport:
    """Build a :class:`PlatformReport` for the host (or for a simulated one).

    Capabilities are stated per platform rather than assumed uniform, because
    the three platforms genuinely differ.
    """
    platform = platform or detect_platform()
    display_server = display_server or detect_display_server(platform, env)
    warnings: list[str] = []
    missing: list[str] = []

    if platform is PlatformName.WINDOWS:
        capabilities = WindowCapabilities(
            can_enumerate=True,
            can_activate=True,
            can_verify_focus=True,
            can_send_synthetic_input=True,
            notes=("native window handles are available",),
        )
    elif platform is PlatformName.MACOS:
        trusted = accessibility_trusted
        if trusted is None:
            trusted = macos_accessibility_trusted()
        granted = trusted is True
        if trusted is None:
            warnings.append(
                "Accessibility permission could not be verified; "
                "input and window control may silently do nothing"
            )
        elif not granted:
            missing.append(MACOS_PERMISSION)
        capabilities = WindowCapabilities(
            can_enumerate=True,
            can_activate=granted or trusted is None,
            can_verify_focus=granted or trusted is None,
            can_send_synthetic_input=granted or trusted is None,
            requires_permission=MACOS_PERMISSION,
            notes=("macOS gates synthetic input behind Accessibility permission",),
        )
    elif platform is PlatformName.LINUX and display_server is DisplayServer.X11:
        capabilities = WindowCapabilities(
            can_enumerate=True,
            can_activate=True,
            can_verify_focus=True,
            can_send_synthetic_input=True,
            notes=("X11 allows window control and global synthetic input",),
        )
    elif platform is PlatformName.LINUX and display_server is DisplayServer.WAYLAND:
        environ = env if env is not None else os.environ
        xwayland = bool(environ.get("DISPLAY"))
        warnings.append(WAYLAND_NOTE)
        if xwayland:
            warnings.append(
                "XWayland is present: input may reach X11 applications only, "
                "and native Wayland windows may ignore it"
            )
        capabilities = WindowCapabilities(
            can_enumerate=False,
            can_activate=False,
            can_verify_focus=False,
            can_send_synthetic_input=xwayland,
            notes=(WAYLAND_NOTE,),
        )
    else:
        capabilities = WindowCapabilities.unknown()
        warnings.append("unrecognised platform or display server; capabilities are unknown")

    return PlatformReport(
        platform=platform,
        display_server=display_server,
        capabilities=capabilities,
        missing_permissions=tuple(missing),
        warnings=tuple(warnings),
    )


class HostCapabilityProbe:
    """:class:`~..ports.capabilities.CapabilityProbe` for the current machine."""

    def probe(self) -> PlatformReport:
        return describe_host()
