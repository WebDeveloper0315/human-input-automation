"""Platform-neutral key and mouse-button vocabulary.

The core never speaks in platform key codes. It uses :class:`Key` for named
keys and single characters for printable ones; adapters translate both into the
representation their backend needs (pynput ``Key``/``KeyCode``, Win32 virtual
key codes, macOS key codes, X11 keysyms, ...).
"""

from __future__ import annotations

from enum import StrEnum

from .errors import ValidationError, ValidationIssue


class Key(StrEnum):
    """Named, non-printable keys.

    ``META`` is the platform "command" modifier: Command on macOS, Windows key
    on Windows, Super on Linux. Adapters are responsible for that mapping so
    plans stay portable.
    """

    ENTER = "enter"
    TAB = "tab"
    ESC = "esc"
    SPACE = "space"
    BACKSPACE = "backspace"
    DELETE = "delete"
    INSERT = "insert"
    HOME = "home"
    END = "end"
    PAGE_UP = "page_up"
    PAGE_DOWN = "page_down"
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    SHIFT = "shift"
    CTRL = "ctrl"
    ALT = "alt"
    META = "meta"
    CAPS_LOCK = "caps_lock"
    F1 = "f1"
    F2 = "f2"
    F3 = "f3"
    F4 = "f4"
    F5 = "f5"
    F6 = "f6"
    F7 = "f7"
    F8 = "f8"
    F9 = "f9"
    F10 = "f10"
    F11 = "f11"
    F12 = "f12"


class MouseButton(StrEnum):
    """Mouse buttons the core can express."""

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


#: A key is either a named key or a single printable character.
KeyLike = Key | str

MODIFIERS: frozenset[Key] = frozenset({Key.SHIFT, Key.CTRL, Key.ALT, Key.META})

_ALIASES: dict[str, Key] = {
    "return": Key.ENTER,
    "escape": Key.ESC,
    "esc": Key.ESC,
    "del": Key.DELETE,
    "control": Key.CTRL,
    "ctl": Key.CTRL,
    "option": Key.ALT,
    "alt_gr": Key.ALT,
    "cmd": Key.META,
    "command": Key.META,
    "super": Key.META,
    "win": Key.META,
    "windows": Key.META,
    "meta": Key.META,
    "pgup": Key.PAGE_UP,
    "pgdn": Key.PAGE_DOWN,
    "pageup": Key.PAGE_UP,
    "pagedown": Key.PAGE_DOWN,
    "spacebar": Key.SPACE,
}


def normalize_key(value: KeyLike, *, location: str = "key") -> Key | str:
    """Coerce ``value`` into a :class:`Key` or a single-character string.

    Raises :class:`ValidationError` for anything else, so an invalid key can
    never reach an adapter.
    """
    if isinstance(value, Key):
        return value
    if not isinstance(value, str):  # pragma: no cover - defensive, mypy blocks this
        raise ValidationError(
            [ValidationIssue("key.type", f"expected Key or str, got {type(value)!r}", location)]
        )
    if len(value) == 1 and not value.isspace():
        return value
    lowered = value.strip().lower().replace("-", "_").replace(" ", "_")
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    try:
        return Key(lowered)
    except ValueError:
        raise ValidationError(
            [
                ValidationIssue(
                    "key.unknown",
                    f"unknown key {value!r}; use a single character or one of: "
                    f"{', '.join(sorted(k.value for k in Key))}",
                    location,
                )
            ]
        ) from None


def is_modifier(key: KeyLike) -> bool:
    """True when ``key`` is a modifier that can be held down for a shortcut."""
    return isinstance(key, Key) and key in MODIFIERS


def parse_shortcut(text: str, *, location: str = "shortcut") -> tuple[Key | str, ...]:
    """Parse ``"ctrl+shift+p"`` into a tuple of keys.

    The final element is the key that is tapped; everything before it is held.
    """
    # A trailing "+" is the literal plus key (e.g. "ctrl++"), not a separator.
    literal_plus = len(text) > 1 and text.endswith("+")
    body = text[:-1] if literal_plus else text
    parts = [part for part in body.split("+") if part.strip()]
    if literal_plus:
        parts.append("+")
    if not parts:
        raise ValidationError(
            [ValidationIssue("shortcut.empty", f"empty shortcut {text!r}", location)]
        )
    return tuple(normalize_key(part, location=location) for part in parts)


def format_key(key: KeyLike) -> str:
    """Human-readable rendering used in logs and dry-run output."""
    return key.value if isinstance(key, Key) else key
