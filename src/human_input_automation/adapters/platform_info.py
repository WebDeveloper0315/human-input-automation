"""Host platform, display-server and capability detection.

The detection functions take their inputs as arguments so every platform can be
simulated in CI from any machine - no real Windows, macOS or Wayland session
required.

Capability states here are per platform *and* per display server, because
"Linux" is not one platform: an X11 session and a Wayland session differ more
than Windows and macOS do.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from ..core.capabilities import (
    Capability,
    CapabilityMatrix,
    CapabilityName,
    CapabilityState,
)
from ..core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)
from .keymap import unsupported_keys

MACOS_ACCESSIBILITY = "macOS Accessibility permission"
MACOS_INPUT_MONITORING = "macOS Input Monitoring permission"
#: Window control on macOS goes through AppleScript to "System Events", which
#: is a *third*, separate grant. Source-verified: pywinctl's macOS backend runs
#: ``osascript`` for getAllWindows, getActiveWindow and activate.
MACOS_AUTOMATION = "macOS Automation permission (System Events)"

#: Where the user grants each permission. Shown verbatim in the UI.
PERMISSION_LOCATIONS = {
    MACOS_ACCESSIBILITY: "System Settings > Privacy & Security > Accessibility",
    MACOS_INPUT_MONITORING: "System Settings > Privacy & Security > Input Monitoring",
    MACOS_AUTOMATION: "System Settings > Privacy & Security > Automation",
}

WAYLAND_NOTE = (
    "Wayland compositors restrict global synthetic input and window control by design; "
    "window enumeration, activation and focus verification are usually unavailable"
)

XWAYLAND_NOTE = (
    "XWayland is present: X11 clients can be listed, focused and driven, "
    "but native Wayland windows are invisible to it"
)

WAYLAND_POINTER_NOTE = (
    "Wayland ignores requests to move the pointer, so a click cannot be aimed; "
    "it would land wherever the pointer already is. Keyboard automation still "
    "works, because it follows the focused window"
)

XWAYLAND_FOCUS_NOTE = (
    "focus is readable and settable for X11 (XWayland) clients through EWMH; "
    "verified on GNOME/Wayland, where the compositor honours activation requests "
    "for X11 windows"
)

_UNPROBED = "capabilities were not probed"


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


def has_xwayland(env: Mapping[str, str] | None = None) -> bool:
    """Whether an X server (XWayland) is reachable from a Wayland session."""
    environ = env if env is not None else os.environ
    return bool(environ.get("DISPLAY"))


def macos_accessibility_trusted() -> bool | None:
    """Whether this process holds macOS Accessibility permission.

    ``None`` means undetermined (no PyObjC, or not macOS). Never "denied".
    """
    if detect_platform() is not PlatformName.MACOS:
        return None
    try:  # PyObjC is optional; absence means we cannot tell, not that it is denied.
        from ApplicationServices import AXIsProcessTrusted
    except Exception:
        return None
    try:
        return bool(AXIsProcessTrusted())
    except Exception:  # pragma: no cover - macOS only
        return None


def macos_automation_trusted() -> bool | None:
    """Whether this process may drive "System Events" via Apple Events.

    A third permission, separate from Accessibility and Input Monitoring, and
    the one that actually gates window enumeration, activation and focus
    verification on macOS. ``None`` when it cannot be determined - which is the
    usual answer, because asking would prompt the user.
    """
    if detect_platform() is not PlatformName.MACOS:
        return None
    try:
        from Foundation import NSAppleEventDescriptor
        from ScriptingBridge import AEDeterminePermissionToAutomateTarget
    except Exception:
        return None
    try:  # 0 == noErr, i.e. permission already granted
        target = NSAppleEventDescriptor.descriptorWithBundleIdentifier_(
            "com.apple.systemevents"
        )
        status = AEDeterminePermissionToAutomateTarget(
            target.aeDesc(), b"****", b"****", False
        )
        return int(status) == 0
    except Exception:  # pragma: no cover - macOS only
        return None


def macos_input_monitoring_trusted() -> bool | None:
    """Whether this process may observe global key events on macOS.

    Input Monitoring is a *separate* permission from Accessibility: an app can
    hold one without the other, which is why the global hotkey and keyboard
    automation are reported independently.
    """
    if detect_platform() is not PlatformName.MACOS:
        return None
    try:
        from Quartz import IOHIDCheckAccess, kIOHIDRequestTypeListenEvent
    except Exception:
        return None
    try:  # 0 == kIOHIDAccessTypeGranted
        return int(IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)) == 0
    except Exception:  # pragma: no cover - macOS only
        return None


def _capability(
    name: CapabilityName,
    state: CapabilityState,
    reason: str = "",
    permission: str | None = None,
    requires_restart: bool = False,
) -> Capability:
    return Capability(
        name=name,
        state=state,
        reason=reason,
        permission=permission,
        permission_category=PERMISSION_LOCATIONS.get(permission or "") or None,
        requires_restart=requires_restart,
    )


def _windows_matrix() -> CapabilityMatrix:
    available = "Win32 exposes native window handles and synthetic input without permissions"
    return CapabilityMatrix.from_capabilities(
        [
            _capability(name, CapabilityState.AVAILABLE, available)
            for name in (
                CapabilityName.WINDOW_ENUMERATION,
                CapabilityName.WINDOW_ACTIVATION,
                CapabilityName.FOCUS_VERIFICATION,
                CapabilityName.KEYBOARD_INPUT,
                CapabilityName.KEY_HOLD,
                CapabilityName.MOUSE_MOVE,
                CapabilityName.MOUSE_CLICK,
                CapabilityName.GLOBAL_HOTKEY,
                CapabilityName.PROCESS_INFO,
                CapabilityName.MULTI_MONITOR,
            )
        ]
    )


def _macos_matrix(
    accessibility: bool | None,
    input_monitoring: bool | None,
    automation: bool | None = None,
) -> CapabilityMatrix:
    """macOS gates this application behind **three** separate permissions.

    Attributed from the libraries' own source, not assumed:

    * **Accessibility** - synthetic keyboard and mouse input (pynput's Quartz
      event posting).
    * **Automation (System Events)** - window enumeration, activation and focus
      verification, because pywinctl's macOS backend drives them through
      AppleScript.
    * **Input Monitoring** - observing global key presses for the emergency
      hotkey.

    Holding one grants nothing about the others, so a user told merely to
    "grant permissions" cannot tell which pane to open.
    """

    def gated(name: CapabilityName, granted: bool | None, permission: str, what: str) -> Capability:
        if granted is True:
            return _capability(name, CapabilityState.AVAILABLE, f"{permission} granted")
        if granted is False:
            return _capability(
                name,
                CapabilityState.DENIED,
                f"{what} requires {permission} ({PERMISSION_LOCATIONS[permission]})",
                permission=permission,
                requires_restart=True,
            )
        return _capability(
            name,
            CapabilityState.UNKNOWN,
            f"{permission} could not be verified (install PyObjC for a definite answer); "
            f"{what} may silently do nothing until it is granted",
            permission=permission,
            requires_restart=True,
        )

    accessibility_gated = [
        (CapabilityName.KEYBOARD_INPUT, "keyboard automation"),
        (CapabilityName.KEY_HOLD, "holding keys down"),
        (CapabilityName.MOUSE_MOVE, "mouse movement"),
        (CapabilityName.MOUSE_CLICK, "mouse clicks"),
    ]
    automation_gated = [
        (CapabilityName.WINDOW_ENUMERATION, "listing other applications' windows"),
        (CapabilityName.WINDOW_ACTIVATION, "activating another application's window"),
        (CapabilityName.FOCUS_VERIFICATION, "reading which window is frontmost"),
    ]
    capabilities = [
        gated(name, accessibility, MACOS_ACCESSIBILITY, what) for name, what in accessibility_gated
    ]
    capabilities += [
        gated(name, automation, MACOS_AUTOMATION, what) for name, what in automation_gated
    ]
    capabilities.append(
        gated(
            CapabilityName.GLOBAL_HOTKEY,
            input_monitoring,
            MACOS_INPUT_MONITORING,
            "the global emergency-stop hotkey",
        )
    )
    capabilities.append(
        _capability(
            CapabilityName.PROCESS_INFO,
            CapabilityState.AVAILABLE,
            "process identifiers are available from the window server",
        )
    )
    capabilities.append(
        _capability(
            CapabilityName.MULTI_MONITOR,
            CapabilityState.RESTRICTED,
            "macOS reports logical points, not device pixels; Retina displays scale by 2",
        )
    )
    return CapabilityMatrix.from_capabilities(capabilities)


def _x11_matrix() -> CapabilityMatrix:
    reason = "X11 allows window control and global synthetic input via XTEST"
    capabilities = [
        _capability(name, CapabilityState.AVAILABLE, reason)
        for name in (
            CapabilityName.WINDOW_ENUMERATION,
            CapabilityName.WINDOW_ACTIVATION,
            CapabilityName.FOCUS_VERIFICATION,
            CapabilityName.KEYBOARD_INPUT,
            CapabilityName.KEY_HOLD,
            CapabilityName.MOUSE_MOVE,
            CapabilityName.MOUSE_CLICK,
            CapabilityName.GLOBAL_HOTKEY,
            CapabilityName.PROCESS_INFO,
        )
    ]
    capabilities.append(
        _capability(
            CapabilityName.MULTI_MONITOR,
            CapabilityState.RESTRICTED,
            "X11 uses one virtual screen in physical pixels; per-monitor scaling is not reported",
        )
    )
    return CapabilityMatrix.from_capabilities(capabilities)


def _wayland_matrix(xwayland: bool) -> CapabilityMatrix:
    """Wayland restricts window control and global input by design.

    With XWayland present, X11 clients remain visible and reachable; native
    Wayland windows are not. That is reported as *restricted*, not available.
    """
    blocked = CapabilityState.UNAVAILABLE
    capabilities = [
        _capability(
            CapabilityName.WINDOW_ENUMERATION,
            CapabilityState.RESTRICTED if xwayland else blocked,
            XWAYLAND_NOTE if xwayland else WAYLAND_NOTE,
        ),
        # Measured on GNOME/Wayland: the compositor honours an EWMH
        # _NET_ACTIVE_WINDOW request for an XWayland client, focus moves, and
        # input follows. Restricted rather than unavailable - it works for X11
        # clients and cannot work for native Wayland windows.
        _capability(
            CapabilityName.WINDOW_ACTIVATION,
            CapabilityState.RESTRICTED if xwayland else blocked,
            XWAYLAND_FOCUS_NOTE if xwayland else WAYLAND_NOTE,
        ),
        # Available - for the windows that can be targeted at all. Only X11
        # clients are enumerable here, and _NET_ACTIVE_WINDOW reports their
        # focus accurately, so activation can be positively confirmed rather
        # than assumed.
        _capability(
            CapabilityName.FOCUS_VERIFICATION,
            CapabilityState.AVAILABLE if xwayland else blocked,
            XWAYLAND_FOCUS_NOTE if xwayland else WAYLAND_NOTE,
        ),
        _capability(
            CapabilityName.KEYBOARD_INPUT,
            CapabilityState.RESTRICTED if xwayland else blocked,
            XWAYLAND_NOTE if xwayland else WAYLAND_NOTE,
        ),
        _capability(
            CapabilityName.KEY_HOLD,
            CapabilityState.RESTRICTED if xwayland else blocked,
            XWAYLAND_NOTE if xwayland else WAYLAND_NOTE,
        ),
        # Measured on GNOME/Wayland: XTEST pointer warping is ignored - the
        # cursor does not move, whatever is requested. A click would therefore
        # land wherever the pointer already happens to be, which may be any
        # window at all, so clicking is unavailable rather than restricted.
        # Keyboard input is unaffected: it follows focus, which we can set.
        _capability(CapabilityName.MOUSE_MOVE, blocked, WAYLAND_POINTER_NOTE),
        _capability(CapabilityName.MOUSE_CLICK, blocked, WAYLAND_POINTER_NOTE),
        _capability(
            CapabilityName.GLOBAL_HOTKEY,
            blocked,
            "Wayland does not let applications observe global key presses",
        ),
        _capability(
            CapabilityName.PROCESS_INFO,
            CapabilityState.RESTRICTED if xwayland else blocked,
            "process ids are readable for X11 clients only" if xwayland else WAYLAND_NOTE,
        ),
        _capability(
            CapabilityName.MULTI_MONITOR,
            CapabilityState.RESTRICTED,
            "monitor layout is readable, but per-monitor scaling is not reported",
        ),
    ]
    return CapabilityMatrix.from_capabilities(capabilities)


def build_matrix(
    platform: PlatformName,
    display_server: DisplayServer,
    env: Mapping[str, str] | None = None,
    accessibility_trusted: bool | None = None,
    input_monitoring_trusted: bool | None = None,
    automation_trusted: bool | None = None,
) -> CapabilityMatrix:
    """The capability matrix for a (platform, display server) pair."""
    if platform is PlatformName.WINDOWS:
        return _windows_matrix()
    if platform is PlatformName.MACOS:
        return _macos_matrix(accessibility_trusted, input_monitoring_trusted, automation_trusted)
    if platform is PlatformName.LINUX and display_server is DisplayServer.X11:
        return _x11_matrix()
    if platform is PlatformName.LINUX and display_server is DisplayServer.WAYLAND:
        return _wayland_matrix(has_xwayland(env))
    # No adapter exists for this combination, so automation is genuinely
    # unavailable here - that is a fact, not an unknown.
    reason = (
        f"no platform adapter is available for {platform.value}/{display_server.value}; "
        "automation cannot be attempted"
    )
    return CapabilityMatrix.from_capabilities(
        Capability(name, CapabilityState.UNAVAILABLE, reason) for name in CapabilityName
    )


def describe_host(
    platform: PlatformName | None = None,
    display_server: DisplayServer | None = None,
    env: Mapping[str, str] | None = None,
    accessibility_trusted: bool | None = None,
    input_monitoring_trusted: bool | None = None,
    automation_trusted: bool | None = None,
) -> PlatformReport:
    """Build a :class:`PlatformReport` for the host (or a simulated one)."""
    platform = platform or detect_platform()
    display_server = display_server or detect_display_server(platform, env)

    if platform is PlatformName.MACOS:
        if accessibility_trusted is None:
            accessibility_trusted = macos_accessibility_trusted()
        if input_monitoring_trusted is None:
            input_monitoring_trusted = macos_input_monitoring_trusted()
        if automation_trusted is None:
            automation_trusted = macos_automation_trusted()

    matrix = build_matrix(
        platform,
        display_server,
        env,
        accessibility_trusted,
        input_monitoring_trusted,
        automation_trusted,
    )
    capabilities = WindowCapabilities.from_matrix(matrix)

    warnings: list[str] = []
    seen: set[str] = set()
    for capability in matrix:
        if capability.state in (CapabilityState.AVAILABLE,):
            continue
        if capability.reason and capability.reason not in seen:
            seen.add(capability.reason)
            warnings.append(capability.reason)
    if matrix.state(CapabilityName.WINDOW_ENUMERATION) is CapabilityState.UNKNOWN:
        warnings.append(_UNPROBED)

    return PlatformReport(
        platform=platform,
        display_server=display_server,
        capabilities=capabilities,
        missing_permissions=matrix.missing_permissions(),
        warnings=tuple(warnings),
        matrix=matrix,
        unsupported_keys=tuple(sorted(unsupported_keys(platform), key=lambda key: key.value)),
    )


class HostCapabilityProbe:
    """:class:`~..ports.capabilities.CapabilityProbe` for the current machine."""

    def probe(self) -> PlatformReport:
        return describe_host()
