"""Adapter selection.

This is the only place that decides which concrete adapter a platform gets. It
degrades gracefully: when a desktop adapter cannot be constructed, the caller
gets a null adapter plus an explanation, instead of an exception at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.errors import AdapterUnavailableError
from ..core.target import PlatformReport
from ..ports.clock import Clock
from ..ports.hotkeys import HotkeyPort
from ..ports.input import KeyboardPort, MousePort
from ..ports.window import WindowControlPort, WindowDiscoveryPort
from .hotkeys import HotkeySupport, NullHotkey, describe_hotkey_support
from .null import NullKeyboard, NullMouse, NullWindowBackend
from .platform_info import describe_host
from .system_clock import SystemClock

if TYPE_CHECKING:
    from .pywinctl_windows import PyWinCtlWindows


@dataclass(frozen=True)
class AdapterSet:
    """The adapters the application layer wires into the engine."""

    keyboard: KeyboardPort
    mouse: MousePort
    windows: WindowControlPort | None
    discovery: WindowDiscoveryPort | None
    clock: Clock
    host: PlatformReport
    hotkey: HotkeyPort = field(default_factory=NullHotkey)
    hotkey_support: HotkeySupport = field(
        default_factory=lambda: HotkeySupport(None, "Global hotkey support was not probed.")
    )
    problems: tuple[str, ...] = ()

    @property
    def is_functional(self) -> bool:
        """True when real input can actually be sent on this host."""
        return not isinstance(self.keyboard, NullKeyboard)


def build_input_adapters() -> tuple[KeyboardPort, MousePort]:
    """Construct the real input adapters, or raise :class:`AdapterUnavailableError`."""
    from .pynput_input import PynputKeyboard, PynputMouse

    return PynputKeyboard(), PynputMouse()


def build_window_adapter(host: PlatformReport) -> PyWinCtlWindows:
    """Construct the real window adapter, or raise :class:`AdapterUnavailableError`."""
    from .pywinctl_windows import PyWinCtlWindows

    return PyWinCtlWindows(host)


def build_hotkey_adapter() -> HotkeyPort:
    """Construct the global-hotkey adapter (it registers nothing until started)."""
    from .pynput_hotkey import PynputHotkey

    return PynputHotkey()


def build_adapters(*, allow_desktop: bool = True) -> AdapterSet:
    """Best-effort wiring of every adapter for the current host."""
    host = describe_host()
    problems: list[str] = list(host.warnings) + [
        f"missing permission: {permission}" for permission in host.missing_permissions
    ]
    keyboard: KeyboardPort = NullKeyboard()
    mouse: MousePort = NullMouse()
    windows: WindowControlPort | None = None
    discovery: WindowDiscoveryPort | None = None
    hotkey: HotkeyPort = NullHotkey()
    hotkey_support = describe_hotkey_support(host)

    if allow_desktop:
        try:
            keyboard, mouse = build_input_adapters()
        except AdapterUnavailableError as exc:
            problems.append(str(exc))
        try:
            backend = build_window_adapter(host)
            windows, discovery = backend, backend
        except AdapterUnavailableError as exc:
            problems.append(str(exc))
            fallback = NullWindowBackend()
            windows, discovery = fallback, fallback
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
        hotkey=hotkey,
        hotkey_support=hotkey_support,
        problems=tuple(problems),
    )
