"""No-op input implementations used by dry-run mode and by tests.

These live in the core (not in ``adapters/``) because they are platform-neutral
by definition: dry run must be guaranteed to send nothing, whatever platform the
application happens to be running on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ports.clock import CancelToken
from .keys import KeyLike, MouseButton, format_key
from .target import TargetWindow


@dataclass
class RecordingKeyboard:
    """Keyboard port that records calls instead of performing them."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))

    def key_down(self, key: KeyLike) -> None:
        self.calls.append(("key_down", format_key(key)))

    def key_up(self, key: KeyLike) -> None:
        self.calls.append(("key_up", format_key(key)))


@dataclass
class RecordingMouse:
    """Mouse port that records calls instead of performing them."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    _position: tuple[int, int] = (0, 0)

    def position(self) -> tuple[int, int]:
        return self._position

    def move_to(
        self, x: int, y: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        self._position = (x, y)
        self.calls.append(("move_to", f"{x},{y}"))

    def move_by(
        self, dx: int, dy: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        self._position = (self._position[0] + dx, self._position[1] + dy)
        self.calls.append(("move_by", f"{dx},{dy}"))

    def button_down(self, button: MouseButton) -> None:
        self.calls.append(("button_down", button.value))

    def button_up(self, button: MouseButton) -> None:
        self.calls.append(("button_up", button.value))


@dataclass
class RecordingWindowControl:
    """Window control that pretends activation succeeded, without touching windows."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def activate(self, target: TargetWindow) -> bool:
        self.calls.append(("activate", target.handle))
        return True

    def is_active(self, target: TargetWindow) -> bool | None:
        return True


class VirtualClock:
    """Clock that advances instantly instead of sleeping.

    Dry runs use it so a preview returns immediately while
    :attr:`RunReport.elapsed_ms` still reports how long the plan *would* take.
    """

    def __init__(self) -> None:
        self._now = 0.0

    def monotonic(self) -> float:
        return self._now

    def sleep_ms(self, milliseconds: float, cancel: CancelToken | None = None) -> bool:
        if cancel is not None and cancel.is_stop_requested():
            return True
        self._now += max(0.0, milliseconds) / 1000.0
        return False
