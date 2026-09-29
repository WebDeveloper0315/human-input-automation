"""Typing characters on X11 through XTEST.

pynput sends *special* keys (Enter, Tab, the arrows) through the XTEST
extension, but sends *characters* with ``XSendEvent``: a synthetic event
addressed to the focused window. Applications may refuse synthetic events, and
some do by default - xterm's ``allowSendEvents`` is off - so text typed that
way never arrives while Enter still does. Found on an isolated X server with
xterm; recorded in ``docs/PHASE6-REAL-PLATFORM-REPORT.md``.

XTEST input comes from the server's own keyboard, which every application
accepts. So a character that the current keyboard layout can produce - on its
own key, or with Shift - is pressed here through XTEST, exactly as pynput
presses Enter. A character the layout has no key for (most non-Latin text)
returns ``False`` and the caller falls back to pynput, which borrows a spare
keycode for it.
"""

from __future__ import annotations

import contextlib
from typing import Any

#: Characters that are keys rather than glyphs.
_SPECIAL_KEYSYMS = {"\n": 0xFF0D, "\r": 0xFF0D, "\t": 0xFF09, "\b": 0xFF08}
_SHIFT_L = 0xFFE1


def keysym_for(char: str) -> int:
    """The X keysym that produces ``char``."""
    if char in _SPECIAL_KEYSYMS:
        return _SPECIAL_KEYSYMS[char]
    code = ord(char)
    # Latin-1 keysyms equal their code point; the rest of Unicode is offset.
    return code if 0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF else 0x01000000 | code


class XTestTyper:
    """Presses characters through XTEST. ``display`` and ``xtest`` are injectable."""

    def __init__(self, display: Any | None = None, xtest: Any | None = None) -> None:
        if display is None or xtest is None:
            from Xlib import display as xdisplay
            from Xlib.ext import xtest as xtest_module

            display = display or xdisplay.Display()
            xtest = xtest or xtest_module
        self._display = display
        self._xtest = xtest
        self._shift = self._keycode(_SHIFT_L)

    def type_char(self, char: str) -> bool:
        """Press and release ``char``. ``False`` when the layout cannot produce it."""
        found = self._key_for(keysym_for(char))
        if found is None:
            return False
        keycode, shifted = found
        if shifted and self._shift is None:
            return False
        press, release = 2, 3  # X.KeyPress, X.KeyRelease
        if shifted:
            self._xtest.fake_input(self._display, press, self._shift)
        try:
            self._xtest.fake_input(self._display, press, keycode)
            self._xtest.fake_input(self._display, release, keycode)
        finally:
            if shifted:
                self._xtest.fake_input(self._display, release, self._shift)
            self._display.sync()
        return True

    def press_char(self, char: str, down: bool) -> bool:
        """Press or release the key that carries ``char``, without adding Shift.

        For shortcuts (``ctrl+d``): the modifiers are already held by the
        caller, and the key is the one with ``char`` on it at either level.
        """
        found = self._key_for(keysym_for(char))
        if found is None:
            return False
        self._xtest.fake_input(self._display, 2 if down else 3, found[0])
        self._display.sync()
        return True

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._display.close()

    def _key_for(self, keysym: int) -> tuple[int, bool] | None:
        """A key and whether it needs Shift. Only the plain and Shift levels.

        AltGr and the other groups depend on how the layout is switched, which
        XTEST cannot see, so those characters are left to the fallback.
        """
        best: tuple[int, bool] | None = None
        for keycode, index in self._display.keysym_to_keycodes(keysym):
            if index == 0:
                return keycode, False
            if index == 1 and best is None:
                best = (keycode, True)
        return best

    def _keycode(self, keysym: int) -> int | None:
        code = self._display.keysym_to_keycode(keysym)
        return int(code) if code else None
