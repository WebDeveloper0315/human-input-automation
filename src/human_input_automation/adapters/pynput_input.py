"""Keyboard and mouse adapter backed by pynput.

pynput is the one dependency that reaches the real desktop, so it is imported
lazily: the core, the tests and CI never load it, and a missing or unusable
installation is reported as :class:`AdapterUnavailableError` instead of an
import crash. Both classes accept an injected module pair, which is how the
adapter logic is unit tested without pynput and without a desktop.

Key translation lives in :mod:`.keymap`, never here.

Platform notes (see ``docs/PHASE3-PLATFORM-REPORT.md`` for what was actually
executed):

* Windows and macOS use OS-level synthetic input APIs; macOS requires
  Accessibility permission before any of it does anything.
* On Linux, pynput drives X11 through XTEST. **In a Wayland session with
  XWayland running, pynput still loads its X11 backend** - verified on Ubuntu
  26.04 GNOME/Wayland - so input reaches X11 clients only, and native Wayland
  windows silently ignore it.
"""

from __future__ import annotations

import time
from typing import Any

from ..core.errors import AdapterUnavailableError
from ..core.keys import KeyLike, MouseButton
from ..ports.clock import CancelToken
from .keymap import resolve_button, resolve_key

#: One interpolation step. Also the upper bound on how long an emergency stop
#: can be delayed by a movement in progress (the sleep between steps is itself
#: interruptible, so the wait is a single position update, not the rest of the
#: movement).
MOVE_STEP_MS = 8.0


def import_pynput() -> tuple[Any, Any]:
    """Import pynput, turning any failure into an actionable adapter error."""
    try:
        from pynput import keyboard, mouse
    except Exception as exc:  # ImportError, or X display errors on headless hosts
        raise AdapterUnavailableError(
            f"pynput is not usable on this host: {exc}",
            remedy='install the desktop extra: pip install ".[desktop]", '
            "and run inside a graphical session",
        ) from exc
    return keyboard, mouse


class PynputKeyboard:
    """Implements :class:`~..ports.input.KeyboardPort`."""

    def __init__(self, keyboard_module: Any | None = None) -> None:
        if keyboard_module is None:
            keyboard_module, _ = import_pynput()
        self._keyboard = keyboard_module
        self._controller = keyboard_module.Controller()

    @property
    def backend_name(self) -> str:
        """The pynput backend actually in use, e.g. ``pynput.keyboard._xorg``."""
        return str(getattr(self._keyboard.Controller, "__module__", "unknown"))

    def type_text(self, text: str) -> None:
        self._controller.type(text)

    def key_down(self, key: KeyLike) -> None:
        self._controller.press(resolve_key(self._keyboard, key))

    def key_up(self, key: KeyLike) -> None:
        self._controller.release(resolve_key(self._keyboard, key))


class PynputMouse:
    """Implements :class:`~..ports.input.MousePort`.

    Movement is interpolated here rather than in the engine so the engine stays
    free of any notion of screen geometry or frame rate. Steps are scheduled
    against a deadline, so a requested duration is actually honoured instead of
    drifting with the cost of each position write.
    """

    def __init__(self, mouse_module: Any | None = None) -> None:
        if mouse_module is None:
            _, mouse_module = import_pynput()
        self._mouse = mouse_module
        self._controller = mouse_module.Controller()

    @property
    def backend_name(self) -> str:
        return str(getattr(self._mouse.Controller, "__module__", "unknown"))

    def position(self) -> tuple[int, int]:
        x, y = self._controller.position
        return (int(x), int(y))

    def move_to(
        self, x: int, y: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        """Move to an absolute position over ``duration_ms``.

        A stop request ends the movement at the point it has reached; the
        pointer is never left mid-flight for the remaining duration.
        """
        if duration_ms <= 0:
            self._controller.position = (x, y)
            return

        start_x, start_y = self.position()
        started = time.monotonic()
        duration_s = duration_ms / 1000.0
        steps = max(1, int(duration_ms / MOVE_STEP_MS))

        for step in range(1, steps + 1):
            if cancel is not None and cancel.is_stop_requested():
                return
            progress = step / steps
            self._controller.position = (
                round(start_x + (x - start_x) * progress),
                round(start_y + (y - start_y) * progress),
            )
            remaining = (started + duration_s * progress) - time.monotonic()
            if remaining <= 0:
                continue
            if cancel is not None:
                if cancel.wait_for_stop(remaining):
                    return
            else:
                time.sleep(remaining)

    def move_by(
        self, dx: int, dy: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        x, y = self.position()
        self.move_to(x + dx, y + dy, duration_ms, cancel)

    def button_down(self, button: MouseButton) -> None:
        self._controller.press(resolve_button(self._mouse, button))

    def button_up(self, button: MouseButton) -> None:
        self._controller.release(resolve_button(self._mouse, button))
