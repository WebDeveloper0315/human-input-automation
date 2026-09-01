"""Global emergency-stop hotkey backed by pynput.

pynput is already a dependency of the input adapter, so no new library is
needed. It is imported lazily, and every failure path degrades to "not active"
rather than raising: a missing hotkey must never prevent the application from
starting, because the on-screen emergency stop is the real safety control.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .hotkeys import DEFAULT_EMERGENCY_HOTKEY, DEFAULT_EMERGENCY_HOTKEY_LABEL

logger = logging.getLogger(__name__)


class PynputHotkey:
    """Implements :class:`~..ports.hotkeys.HotkeyPort` with ``GlobalHotKeys``."""

    def __init__(
        self,
        combination: str = DEFAULT_EMERGENCY_HOTKEY,
        label: str = DEFAULT_EMERGENCY_HOTKEY_LABEL,
    ) -> None:
        self._combination = combination
        self._label = label
        self._listener: Any | None = None

    @property
    def description(self) -> str:
        return self._label

    @property
    def is_active(self) -> bool:
        listener = self._listener
        return bool(listener is not None and listener.is_alive())

    def start(self, on_trigger: Callable[[], None]) -> bool:
        if self._listener is not None:
            return self.is_active
        try:
            from pynput import keyboard

            listener = keyboard.GlobalHotKeys({self._combination: on_trigger})
            listener.daemon = True
            listener.start()
        except Exception as exc:  # no display, no permission, unsupported platform
            logger.info("global hotkey unavailable: %s", exc)
            self._listener = None
            return False
        self._listener = listener
        return True

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:  # pragma: no cover - platform specific
            logger.debug("failed to stop global hotkey listener", exc_info=True)
