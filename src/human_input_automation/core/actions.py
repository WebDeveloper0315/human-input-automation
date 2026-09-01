"""The action model.

Actions are small frozen dataclasses forming a discriminated union rather than
one struct with a ``type`` tag and a dozen optional fields. That choice makes
invalid states unrepresentable (a click always has a button, a wait always has a
duration) and lets the engine dispatch on type.

Adding a new action later is a three-line change: define a dataclass here,
write a handler, register it. The engine itself never changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from .errors import ValidationError, ValidationIssue
from .keys import Key, KeyLike, MouseButton, format_key, normalize_key


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ValidationError([ValidationIssue(code, message)])


@dataclass(frozen=True)
class Action:
    """Base class for every action.

    ``delay_after_ms`` overrides the timing profile's action delay for this one
    action; ``None`` means "use the profile".
    """

    #: Stable identifier used for serialisation and logs.
    kind: ClassVar[str] = "action"

    delay_after_ms: float | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.delay_after_ms is not None:
            _require(
                self.delay_after_ms >= 0,
                "action.delay_negative",
                f"delay_after_ms must be >= 0, got {self.delay_after_ms}",
            )

    def describe(self) -> str:
        """Human-readable summary, shown in dry-run output and the run log."""
        return self.kind


@dataclass(frozen=True)
class TypeText(Action):
    """Type a literal string, character by character, with per-character timing."""

    kind: ClassVar[str] = "type_text"

    text: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _require(bool(self.text), "type_text.empty", "text must not be empty")

    def describe(self) -> str:
        preview = self.text if len(self.text) <= 40 else self.text[:37] + "..."
        return f"type {preview!r} ({len(self.text)} chars)"


@dataclass(frozen=True)
class KeyPress(Action):
    """Press and release a single key, optionally repeated."""

    kind: ClassVar[str] = "key_press"

    key: KeyLike
    count: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "key", normalize_key(self.key))
        _require(self.count >= 1, "key_press.count", f"count must be >= 1, got {self.count}")

    def describe(self) -> str:
        suffix = f" x{self.count}" if self.count > 1 else ""
        return f"press {format_key(self.key)}{suffix}"


@dataclass(frozen=True)
class KeyDown(Action):
    """Hold a key down. The engine releases anything still held when a run ends."""

    kind: ClassVar[str] = "key_down"

    key: KeyLike

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "key", normalize_key(self.key))

    def describe(self) -> str:
        return f"key down {format_key(self.key)}"


@dataclass(frozen=True)
class KeyUp(Action):
    """Release a previously held key."""

    kind: ClassVar[str] = "key_up"

    key: KeyLike

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "key", normalize_key(self.key))

    def describe(self) -> str:
        return f"key up {format_key(self.key)}"


@dataclass(frozen=True)
class Shortcut(Action):
    """A chord such as ``ctrl+shift+p``.

    Every key but the last is held, the last is tapped, then the held keys are
    released in reverse order.
    """

    kind: ClassVar[str] = "shortcut"

    keys: tuple[KeyLike, ...]

    MAX_KEYS: ClassVar[int] = 6

    def __post_init__(self) -> None:
        super().__post_init__()
        _require(bool(self.keys), "shortcut.empty", "shortcut needs at least one key")
        _require(
            len(self.keys) <= self.MAX_KEYS,
            "shortcut.too_many_keys",
            f"shortcut supports at most {self.MAX_KEYS} keys, got {len(self.keys)}",
        )
        object.__setattr__(
            self, "keys", tuple(normalize_key(key, location="shortcut") for key in self.keys)
        )

    @classmethod
    def parse(cls, text: str, *, delay_after_ms: float | None = None) -> Shortcut:
        """Build a shortcut from ``"ctrl+s"`` notation."""
        from .keys import parse_shortcut

        return cls(keys=parse_shortcut(text), delay_after_ms=delay_after_ms)

    @property
    def modifiers(self) -> tuple[KeyLike, ...]:
        return self.keys[:-1]

    @property
    def main_key(self) -> KeyLike:
        return self.keys[-1]

    def describe(self) -> str:
        return "shortcut " + "+".join(format_key(key) for key in self.keys)


@dataclass(frozen=True)
class MouseMove(Action):
    """Move the pointer, absolutely or relative to its current position."""

    kind: ClassVar[str] = "mouse_move"

    x: int
    y: int
    relative: bool = False
    duration_ms: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.relative:
            _require(
                self.x >= 0 and self.y >= 0,
                "mouse_move.negative",
                f"absolute coordinates must be >= 0, got ({self.x}, {self.y})",
            )
        if self.duration_ms is not None:
            _require(
                self.duration_ms >= 0,
                "mouse_move.duration",
                f"duration_ms must be >= 0, got {self.duration_ms}",
            )

    def describe(self) -> str:
        mode = "by" if self.relative else "to"
        return f"move mouse {mode} ({self.x}, {self.y})"


@dataclass(frozen=True)
class MouseClick(Action):
    """Click a mouse button, optionally moving to a position first."""

    kind: ClassVar[str] = "mouse_click"

    button: MouseButton = MouseButton.LEFT
    x: int | None = None
    y: int | None = None
    count: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        _require(
            (self.x is None) == (self.y is None),
            "mouse_click.coordinates",
            "x and y must be given together or not at all",
        )
        if self.x is not None and self.y is not None:
            _require(
                self.x >= 0 and self.y >= 0,
                "mouse_click.negative",
                f"coordinates must be >= 0, got ({self.x}, {self.y})",
            )
        _require(self.count >= 1, "mouse_click.count", f"count must be >= 1, got {self.count}")

    @property
    def position(self) -> tuple[int, int] | None:
        if self.x is None or self.y is None:
            return None
        return (self.x, self.y)

    def describe(self) -> str:
        where = f" at ({self.x}, {self.y})" if self.position else ""
        suffix = f" x{self.count}" if self.count > 1 else ""
        return f"{self.button.value} click{where}{suffix}"


@dataclass(frozen=True)
class MouseDown(Action):
    """Press and hold a mouse button (drag start)."""

    kind: ClassVar[str] = "mouse_down"

    button: MouseButton = MouseButton.LEFT

    def describe(self) -> str:
        return f"{self.button.value} button down"


@dataclass(frozen=True)
class MouseUp(Action):
    """Release a mouse button (drag end)."""

    kind: ClassVar[str] = "mouse_up"

    button: MouseButton = MouseButton.LEFT

    def describe(self) -> str:
        return f"{self.button.value} button up"


@dataclass(frozen=True)
class Wait(Action):
    """Sleep for a fixed duration. Interruptible: stop requests abort the wait."""

    kind: ClassVar[str] = "wait"

    duration_ms: float

    def __post_init__(self) -> None:
        super().__post_init__()
        _require(
            self.duration_ms >= 0,
            "wait.duration",
            f"duration_ms must be >= 0, got {self.duration_ms}",
        )

    def describe(self) -> str:
        return f"wait {self.duration_ms:g} ms"


#: Convenience alias for the union of built-in actions.
BuiltinAction = (
    TypeText
    | KeyPress
    | KeyDown
    | KeyUp
    | Shortcut
    | MouseMove
    | MouseClick
    | MouseDown
    | MouseUp
    | Wait
)

__all__ = [
    "Action",
    "BuiltinAction",
    "Key",
    "KeyDown",
    "KeyPress",
    "KeyUp",
    "MouseButton",
    "MouseClick",
    "MouseDown",
    "MouseMove",
    "MouseUp",
    "Shortcut",
    "TypeText",
    "Wait",
]
