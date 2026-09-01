"""Centralised key and mouse-button translation.

All platform key knowledge lives here. The engine and the rest of the core only
ever speak :class:`~..core.keys.Key` and :class:`~..core.keys.MouseButton`;
nothing else in the codebase may contain a platform key name.

Two facts drive this module, both verified against the installed pynput 1.8
sources rather than assumed:

1. ``pynput.keyboard.Controller.press`` accepts a ``Key``, a ``KeyCode`` or a
   *single-character* string. A multi-character string such as ``"enter"``
   raises ``ValueError``, so named keys must be translated before they reach
   pynput.
2. pynput's ``Key`` enum is defined per backend and the backends differ. The
   macOS backend has no ``insert`` member, so ``Key.INSERT`` cannot be sent on
   macOS at all. That is a platform gap, not a bug to paper over: it is
   reported as a capability and caught by validation *before* a run starts,
   instead of raising halfway through a plan.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import AdapterUnavailableError
from ..core.keys import Key, KeyLike, MouseButton
from ..core.target import PlatformName

#: Our name -> pynput's name, where they differ.
#: ``META`` is the platform command modifier; pynput calls it ``cmd`` on every
#: backend (Command on macOS, the Windows key on Windows, Super on X11).
_PYNPUT_NAMES: dict[Key, str] = {Key.META: "cmd"}

#: Keys pynput's backend does not define, per platform. Source: the ``Key``
#: enums in ``pynput/keyboard/_win32.py``, ``_darwin.py`` and ``_xorg.py``.
_UNSUPPORTED_KEYS: dict[PlatformName, frozenset[Key]] = {
    PlatformName.WINDOWS: frozenset(),
    PlatformName.MACOS: frozenset({Key.INSERT}),
    PlatformName.LINUX: frozenset(),
    PlatformName.UNKNOWN: frozenset(),
}

#: Mouse buttons pynput's backend does not define, per platform. All three
#: backends provide left, right and middle.
_UNSUPPORTED_BUTTONS: dict[PlatformName, frozenset[MouseButton]] = {
    platform: frozenset() for platform in PlatformName
}


def pynput_key_name(key: Key) -> str:
    """The attribute name of ``key`` on ``pynput.keyboard.Key``."""
    return _PYNPUT_NAMES.get(key, key.value)


def unsupported_keys(platform: PlatformName) -> frozenset[Key]:
    """Keys that cannot be sent on ``platform``."""
    return _UNSUPPORTED_KEYS.get(platform, frozenset())


def unsupported_buttons(platform: PlatformName) -> frozenset[MouseButton]:
    """Mouse buttons that cannot be sent on ``platform``."""
    return _UNSUPPORTED_BUTTONS.get(platform, frozenset())


def is_key_supported(key: KeyLike, platform: PlatformName) -> bool:
    """False only for named keys the platform's backend genuinely lacks."""
    return not (isinstance(key, Key) and key in unsupported_keys(platform))


def resolve_key(keyboard_module: Any, key: KeyLike) -> Any:
    """Translate ``key`` into a pynput key object.

    Single characters become ``KeyCode`` instances; named keys become members of
    the backend's ``Key`` enum. A key the backend lacks raises
    :class:`AdapterUnavailableError` naming the key, never a bare
    ``AttributeError``.
    """
    if isinstance(key, Key):
        name = pynput_key_name(key)
        try:
            return getattr(keyboard_module.Key, name)
        except AttributeError as exc:
            raise AdapterUnavailableError(
                f"the key {key.value!r} is not available in pynput's backend on this platform",
                remedy="use a different key; this is a platform limitation, not a setting",
            ) from exc
    if len(key) != 1:  # pynput itself raises ValueError for multi-character strings
        raise AdapterUnavailableError(
            f"{key!r} is not a single character or a known key name",
        )
    return keyboard_module.KeyCode.from_char(key)


def resolve_button(mouse_module: Any, button: MouseButton) -> Any:
    """Translate ``button`` into a pynput button object."""
    try:
        return getattr(mouse_module.Button, button.value)
    except AttributeError as exc:
        raise AdapterUnavailableError(
            f"the {button.value} mouse button is not available in pynput's backend here"
        ) from exc
