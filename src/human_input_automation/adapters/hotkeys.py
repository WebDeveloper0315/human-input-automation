"""Global hotkey support: capability reporting and the no-op implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core.target import DisplayServer, PlatformName, PlatformReport

#: Default emergency-stop combination.
#:
#: Chosen from measured behaviour, not taste. On X11, pynput's ``GlobalHotKeys``
#: was verified against a real X server and two shapes never fire:
#:
#: * anything holding **Ctrl and Alt together** (``<ctrl>+<alt>+.``,
#:   ``<ctrl>+<alt>+q`` and ``<ctrl>+<alt>+<f9>`` all failed), and
#: * any **character key**, with or without modifiers (``<ctrl>+.`` failed),
#:   because a modified character reports a different key identity than the one
#:   the combination was parsed into.
#:
#: Combinations of named keys with Ctrl and/or Shift fire reliably, so the
#: default is one of those. See :func:`problematic_combination`.
DEFAULT_EMERGENCY_HOTKEY = "<ctrl>+<shift>+<f9>"
DEFAULT_EMERGENCY_HOTKEY_LABEL = "Ctrl+Shift+F9"


@dataclass(frozen=True)
class HotkeySupport:
    """Whether a global hotkey can be registered on this host.

    ``available`` is ``None`` when it genuinely cannot be determined; that is
    reported as "unknown", never as "no".
    """

    available: bool | None
    reason: str

    @property
    def is_known_unsupported(self) -> bool:
        return self.available is False


def describe_hotkey_support(host: PlatformReport) -> HotkeySupport:
    """Report global-hotkey support without attempting to register anything."""
    if host.platform is PlatformName.WINDOWS:
        return HotkeySupport(True, "Global hotkey supported.")
    if host.platform is PlatformName.MACOS:
        if host.missing_permissions:
            return HotkeySupport(
                False,
                "macOS blocks global key monitoring until Accessibility/Input Monitoring "
                "permission is granted to this application.",
            )
        return HotkeySupport(
            None,
            "macOS may require Input Monitoring permission before the global hotkey works.",
        )
    if host.platform is PlatformName.LINUX:
        if host.display_server is DisplayServer.WAYLAND:
            return HotkeySupport(
                False,
                "Wayland does not let applications observe global key presses; "
                "use the on-screen emergency stop.",
            )
        if host.display_server is DisplayServer.X11:
            return HotkeySupport(True, "Global hotkey supported on X11.")
    return HotkeySupport(None, "Global hotkey support is unknown on this platform.")


def problematic_combination(combination: str) -> str | None:
    """Describe why a combination is unlikely to fire, or ``None`` if it is fine.

    Based on behaviour measured against a real X server; the same shapes are
    reported for every platform because the matching logic is pynput's, not the
    window system's. A warning, never a refusal: the combination is still
    registered, and the on-screen emergency stop is unaffected either way.
    """
    parts = [part.strip().lower() for part in combination.split("+") if part.strip()]
    named = {part.strip("<>") for part in parts if part.startswith("<")}
    characters = [part for part in parts if not part.startswith("<")]

    if {"ctrl", "alt"} <= named:
        return (
            "combinations holding Ctrl and Alt together were observed never to fire "
            "with pynput on X11; use Ctrl and/or Shift with a function key instead"
        )
    if characters:
        return (
            f"character keys ({', '.join(characters)}) do not match reliably once a "
            "modifier is held; use a named key such as <f9> instead"
        )
    return None


class NullHotkey:
    """Hotkey port that never registers anything."""

    def __init__(self, description: str = DEFAULT_EMERGENCY_HOTKEY_LABEL) -> None:
        self._description = description

    @property
    def description(self) -> str:
        return self._description

    @property
    def is_active(self) -> bool:
        return False

    def start(self, on_trigger: Callable[[], None]) -> bool:
        return False

    def stop(self) -> None:
        return None
