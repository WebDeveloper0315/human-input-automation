"""No-op adapters.

Used as safe defaults (for example before any platform adapter is available)
and as the base for the fakes used in tests.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.dryrun import RecordingKeyboard, RecordingMouse, RecordingWindowControl
from ..core.keys import KeyLike, MouseButton
from ..core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
    WindowCapabilities,
)
from ..ports.clock import CancelToken

__all__ = [
    "NullCapabilityProbe",
    "NullKeyboard",
    "NullMouse",
    "NullWindowBackend",
    "RecordingKeyboard",
    "RecordingMouse",
    "RecordingWindowControl",
]


class NullKeyboard:
    """Keyboard port that does nothing."""

    def type_text(self, text: str) -> None:
        return None

    def key_down(self, key: KeyLike) -> None:
        return None

    def key_up(self, key: KeyLike) -> None:
        return None


class NullMouse:
    """Mouse port that does nothing."""

    def position(self) -> tuple[int, int]:
        return (0, 0)

    def move_to(
        self, x: int, y: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        return None

    def move_by(
        self, dx: int, dy: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        return None

    def button_down(self, button: MouseButton) -> None:
        return None

    def button_up(self, button: MouseButton) -> None:
        return None


class NullWindowBackend:
    """Window discovery and control that knows about no windows."""

    def list_windows(self) -> Sequence[TargetWindow]:
        return ()

    def find(self, handle: str) -> TargetWindow | None:
        return None

    def activate(self, target: TargetWindow) -> bool:
        return False

    def is_active(self, target: TargetWindow) -> bool | None:
        return None


class NullCapabilityProbe:
    """Capability probe reporting that nothing is supported."""

    def probe(self) -> PlatformReport:
        return PlatformReport(
            platform=PlatformName.UNKNOWN,
            display_server=DisplayServer.UNKNOWN,
            capabilities=WindowCapabilities.unknown(),
            warnings=("no platform adapter is installed",),
        )
