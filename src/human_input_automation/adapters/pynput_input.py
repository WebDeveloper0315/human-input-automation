"""Keyboard and mouse adapter backed by pynput.

pynput is the one dependency that reaches the real desktop, so it is imported
lazily: the core, the tests and CI never load it, and a missing or unusable
installation is reported as :class:`AdapterUnavailableError` instead of an
import crash.

Platform notes:

* Windows and macOS use OS-level synthetic input APIs (macOS requires
  Accessibility permission).
* On Linux, pynput drives X11. Under Wayland it can only reach XWayland
  clients, if anything - see ``platform_info.describe_host``.
"""

from __future__ import annotations

import time
from typing import Any

from ..core.errors import AdapterUnavailableError
from ..core.keys import Key, KeyLike, MouseButton

#: Named keys whose pynput spelling differs from ours.
_KEY_NAME_OVERRIDES: dict[Key, str] = {Key.META: "cmd", Key.ESC: "esc"}

_MOVE_STEP_MS = 8.0  # ~120 updates per second while interpolating movement


def _import_pynput() -> tuple[Any, Any]:
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

    def __init__(self) -> None:
        keyboard, _ = _import_pynput()
        self._keyboard_module = keyboard
        self._controller = keyboard.Controller()

    def _resolve(self, key: KeyLike) -> Any:
        if isinstance(key, Key):
            name = _KEY_NAME_OVERRIDES.get(key, key.value)
            try:
                return getattr(self._keyboard_module.Key, name)
            except AttributeError as exc:  # pragma: no cover - platform specific
                raise AdapterUnavailableError(
                    f"key {key.value!r} is not supported by pynput on this platform"
                ) from exc
        return self._keyboard_module.KeyCode.from_char(key)

    def type_text(self, text: str) -> None:
        self._controller.type(text)

    def key_down(self, key: KeyLike) -> None:
        self._controller.press(self._resolve(key))

    def key_up(self, key: KeyLike) -> None:
        self._controller.release(self._resolve(key))


class PynputMouse:
    """Implements :class:`~..ports.input.MousePort`.

    Movement is interpolated here rather than in the engine so the engine stays
    free of any notion of screen geometry or frame rate.
    """

    def __init__(self) -> None:
        _, mouse = _import_pynput()
        self._mouse_module = mouse
        self._controller = mouse.Controller()

    def _resolve(self, button: MouseButton) -> Any:
        return getattr(self._mouse_module.Button, button.value)

    def position(self) -> tuple[int, int]:
        x, y = self._controller.position
        return (int(x), int(y))

    def move_to(self, x: int, y: int, duration_ms: float) -> None:
        start_x, start_y = self.position()
        steps = max(1, int(duration_ms / _MOVE_STEP_MS)) if duration_ms > 0 else 1
        for step in range(1, steps + 1):
            progress = step / steps
            self._controller.position = (
                int(start_x + (x - start_x) * progress),
                int(start_y + (y - start_y) * progress),
            )
            if step < steps:
                time.sleep(duration_ms / steps / 1000.0)

    def move_by(self, dx: int, dy: int, duration_ms: float) -> None:
        x, y = self.position()
        self.move_to(x + dx, y + dy, duration_ms)

    def button_down(self, button: MouseButton) -> None:
        self._controller.press(self._resolve(button))

    def button_up(self, button: MouseButton) -> None:
        self._controller.release(self._resolve(button))
