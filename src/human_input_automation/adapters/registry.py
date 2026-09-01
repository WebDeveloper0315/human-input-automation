"""Adapter selection.

This is the only place that decides which concrete adapter a platform gets. It
degrades gracefully: when a desktop adapter cannot be constructed, the caller
gets a null adapter plus an explanation, instead of an exception at import time.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from ..core.capabilities import CapabilityName
from ..core.errors import AdapterUnavailableError
from ..core.screen import ScreenGeometry
from ..core.target import DisplayServer, PlatformName, PlatformReport
from ..ports.clock import Clock
from ..ports.hotkeys import HotkeyPort
from ..ports.input import KeyboardPort, MousePort
from ..ports.screen import ScreenPort
from ..ports.window import WindowControlPort, WindowDiscoveryPort
from .hotkeys import HotkeySupport, NullHotkey, describe_hotkey_support
from .null import NullKeyboard, NullMouse, NullWindowBackend
from .platform_info import describe_host
from .screens import NullScreens, PyMonCtlScreens
from .system_clock import SystemClock


@dataclass(frozen=True)
class AdapterSet:
    """The adapters the application layer wires into the engine."""

    keyboard: KeyboardPort
    mouse: MousePort
    windows: WindowControlPort | None
    discovery: WindowDiscoveryPort | None
    clock: Clock
    host: PlatformReport
    screens: ScreenPort = field(default_factory=NullScreens)
    window_backend: str = "none"
    hotkey: HotkeyPort = field(default_factory=NullHotkey)
    hotkey_support: HotkeySupport = field(
        default_factory=lambda: HotkeySupport(None, "Global hotkey support was not probed.")
    )
    problems: tuple[str, ...] = ()

    @property
    def is_functional(self) -> bool:
        """True when real input can actually be sent on this host."""
        return not isinstance(self.keyboard, NullKeyboard)

    def geometry(self) -> ScreenGeometry:
        """Monitor layout, or unknown geometry when it cannot be read."""
        return self.screens.geometry()

    def close(self) -> None:
        """Release adapter resources (X connections, hotkey listeners).

        Safe to call more than once, and safe when an adapter has no resources
        to release.
        """
        self.hotkey.stop()
        for adapter in (self.windows, self.discovery):
            close = getattr(adapter, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()


def build_input_adapters() -> tuple[KeyboardPort, MousePort]:
    """Construct the real input adapters, or raise :class:`AdapterUnavailableError`."""
    from .pynput_input import PynputKeyboard, PynputMouse

    return PynputKeyboard(), PynputMouse()


def select_window_backend(host: PlatformReport) -> str:
    """Pick a window backend from *capabilities*, not from the OS name alone.

    Linux is two platforms: an X11 session gets the EWMH backend (pywinctl's
    Linux path raises ``KeyError: 'id'`` on GNOME), a Wayland session with
    XWayland gets the same backend in its restricted form, and a Wayland session
    without XWayland gets none at all. Windows and macOS use pywinctl.
    """
    if not host.matrix.is_permitted(CapabilityName.WINDOW_ENUMERATION):
        return "none"
    if host.platform is PlatformName.LINUX:
        if host.display_server in (DisplayServer.X11, DisplayServer.WAYLAND):
            return "x11"
        return "none"
    if host.platform in (PlatformName.WINDOWS, PlatformName.MACOS):
        return "pywinctl"
    return "none"


def build_window_adapter(host: PlatformReport) -> Any:
    """Construct the window adapter chosen by :func:`select_window_backend`."""
    backend = select_window_backend(host)
    if backend == "x11":
        from .x11_windows import X11Windows

        return X11Windows(host)
    if backend == "pywinctl":
        from .pywinctl_windows import PyWinCtlWindows

        return PyWinCtlWindows(host)
    raise AdapterUnavailableError(
        "no window backend is available for this platform and display server",
        remedy=host.matrix.reason(CapabilityName.WINDOW_ENUMERATION),
    )


def build_hotkey_adapter() -> HotkeyPort:
    """Construct the global-hotkey adapter (it registers nothing until started)."""
    from .pynput_hotkey import PynputHotkey

    return PynputHotkey()


def build_screen_adapter(host: PlatformReport) -> ScreenPort:
    """Pick the monitor-layout source for this host.

    X11 reads RandR directly: it is authoritative for the display we are
    connected to, whereas pymonctl was observed returning duplicated monitors
    and monitors belonging to a different display. Windows and macOS keep
    pymonctl, which is the only cross-platform option available there.
    """
    if host.platform is PlatformName.LINUX and host.display_server in (
        DisplayServer.X11,
        DisplayServer.WAYLAND,
    ):
        from .x11_screens import X11Screens

        return X11Screens()
    return PyMonCtlScreens(host.platform)


def build_adapters(*, allow_desktop: bool = True) -> AdapterSet:
    """Best-effort wiring of every adapter for the current host."""
    host = describe_host()
    # Adapter problems only: platform warnings and permissions are already
    # carried by the host report, and repeating them here reads as duplicates.
    problems: list[str] = [
        f"missing permission: {permission}" for permission in host.missing_permissions
    ]
    keyboard: KeyboardPort = NullKeyboard()
    mouse: MousePort = NullMouse()
    windows: WindowControlPort | None = None
    discovery: WindowDiscoveryPort | None = None
    hotkey: HotkeyPort = NullHotkey()
    hotkey_support = describe_hotkey_support(host)
    screens: ScreenPort = NullScreens()
    backend_name = "none"

    if allow_desktop:
        try:
            keyboard, mouse = build_input_adapters()
        except AdapterUnavailableError as exc:
            problems.append(str(exc))
        try:
            backend = build_window_adapter(host)
            windows, discovery = backend, backend
            backend_name = select_window_backend(host)
        except AdapterUnavailableError as exc:
            problems.append(str(exc))
            fallback = NullWindowBackend()
            windows, discovery = fallback, fallback
        try:
            screens = build_screen_adapter(host)
        except AdapterUnavailableError as exc:
            problems.append(str(exc))
        if not hotkey_support.is_known_unsupported:
            try:
                hotkey = build_hotkey_adapter()
            except AdapterUnavailableError as exc:  # pragma: no cover - import guarded
                problems.append(str(exc))

    return AdapterSet(
        keyboard=keyboard,
        mouse=mouse,
        windows=windows,
        discovery=discovery,
        clock=SystemClock(),
        host=host,
        screens=screens,
        window_backend=backend_name,
        hotkey=hotkey,
        hotkey_support=hotkey_support,
        problems=tuple(problems),
    )
