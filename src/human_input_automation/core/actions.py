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
from enum import StrEnum
from typing import ClassVar

from .errors import ValidationError, ValidationIssue
from .keys import Key, KeyLike, MouseButton, format_key, normalize_key, parse_shortcut


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
class TextAction(Action):
    """Base class for the actions that send a string of text.

    Having one base means the limits, the character count and the validation
    rules are written once and cannot drift apart between the two.
    """

    text: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _require(bool(self.text), f"{self.kind}.empty", "text must not be empty")


@dataclass(frozen=True)
class TypeText(TextAction):
    """Type a literal string, character by character, with per-character timing."""

    kind: ClassVar[str] = "type_text"

    def describe(self) -> str:
        preview = self.text if len(self.text) <= 40 else self.text[:37] + "..."
        return f"type {preview!r} ({len(self.text)} chars)"


class IndentMode(StrEnum):
    """What to do about the indentation a code editor inserts for you.

    Pressing Enter in an editor does not leave the caret in column one: it
    indents the new line for you. Typing your own indentation on top of that is
    what turns a tidy block of code into a staircase.
    """

    #: Select the editor's indentation and type over it. The text comes out
    #: exactly as written.
    RECLAIM = "reclaim"
    #: Drop our own leading whitespace and keep the editor's. The editor decides
    #: the layout, which is what a person gets when they type the code by hand.
    EDITOR = "editor"
    #: Send the text unchanged, editor helpfulness and all.
    OFF = "off"


#: Opening bracket -> the character an editor inserts to match it.
AUTO_CLOSED_PAIRS: dict[str, str] = {"(": ")", "[": "]", "{": "}"}

#: Default chord for "select from the caret to the start of the line". Works in
#: VS Code on every platform; a native macOS editor wants ``meta+shift+left``.
DEFAULT_LINE_START_CHORD = "shift+home"


@dataclass(frozen=True)
class TypeCode(TextAction):
    """Type text into an editor that edits as you type.

    A code editor is not a text box. It indents new lines, closes brackets you
    open, and offers completions that Enter and Tab accept. Sent through
    :class:`TypeText`, a block of code therefore arrives with its indentation
    multiplied, extra closing brackets at the end, and the occasional accepted
    suggestion in the middle.

    This action sends the same text with each of those behaviours compensated
    for. Every compensation is a keystroke - there is no way to ask an editor
    what it is about to do - so each one states the assumption it makes, and can
    be turned off when it does not hold:

    * ``indent`` - see :class:`IndentMode`. Reclaiming assumes the chord in
      ``line_start_chord`` selects to the start of the line.
    * ``drop_auto_pairs`` - after a line that leaves a bracket open, press
      Delete once per open bracket to remove the partner the editor added.
      **Assumes the editor closes brackets.** Where it does not, those presses
      delete real characters to the right of the caret, so switch this off for
      an editor that leaves brackets alone.
    * ``dismiss_suggestions`` - press Escape at the end of every line, so the
      Enter that follows inserts a newline rather than accepting whatever the
      completion popup was offering.

    A blank line keeps whatever indentation the editor gave it: clearing it
    would mean pressing Delete or Backspace with nothing selected, which in an
    editor joins two lines together.
    """

    kind: ClassVar[str] = "type_code"

    indent: IndentMode = IndentMode.RECLAIM
    drop_auto_pairs: bool = True
    dismiss_suggestions: bool = True
    line_start_chord: str = DEFAULT_LINE_START_CHORD

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "indent", IndentMode(self.indent))
        # Parsed now so a chord that cannot be sent is a validation error in the
        # editor, not a surprise in the middle of a run.
        parse_shortcut(self.line_start_chord, location="line_start_chord")

    @property
    def lines(self) -> tuple[str, ...]:
        """The text split into lines, with line endings normalised."""
        return tuple(self.text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))

    @property
    def keys_used(self) -> tuple[KeyLike, ...]:
        """Named keys this action may press, so validation can check them.

        A platform whose backend lacks one of these has to be caught before the
        run starts, in the same way as a key press that names it directly.
        """
        keys: list[KeyLike] = []
        if len(self.lines) > 1:
            keys.append(Key.ENTER)
        if self.indent is IndentMode.RECLAIM:
            keys.extend(parse_shortcut(self.line_start_chord))
        if self.drop_auto_pairs:
            keys.append(Key.DELETE)
        if self.dismiss_suggestions:
            keys.append(Key.ESC)
        return tuple(dict.fromkeys(keys))

    def describe(self) -> str:
        count = len(self.lines)
        compensations = [
            name
            for name, enabled in (
                (f"indent: {self.indent.value}", self.indent is not IndentMode.OFF),
                ("drop auto-pairs", self.drop_auto_pairs),
                ("dismiss suggestions", self.dismiss_suggestions),
            )
            if enabled
        ]
        suffix = f" [{', '.join(compensations)}]" if compensations else ""
        return f"type {count} line(s) into an editor ({len(self.text)} chars){suffix}"


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
    | TypeCode
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
    "AUTO_CLOSED_PAIRS",
    "DEFAULT_LINE_START_CHORD",
    "Action",
    "BuiltinAction",
    "IndentMode",
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
    "TextAction",
    "TypeCode",
    "TypeText",
    "Wait",
]
