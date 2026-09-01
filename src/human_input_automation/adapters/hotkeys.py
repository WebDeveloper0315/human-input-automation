"""Global hotkey support: capability reporting and the no-op implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core.target import DisplayServer, PlatformName, PlatformReport

#: Default emergency-stop combination. Chosen to be unlikely to clash with
#: application shortcuts, and to be typable one-handed.
DEFAULT_EMERGENCY_HOTKEY = "<ctrl>+<alt>+."
DEFAULT_EMERGENCY_HOTKEY_LABEL = "Ctrl+Alt+."


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
