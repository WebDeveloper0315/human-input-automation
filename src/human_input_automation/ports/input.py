"""Keyboard and mouse ports.

Implementations receive platform-neutral :class:`~..core.keys.Key` values and
single characters, and are responsible for translating them. They must not
implement policy (timing, sequencing, retries) - that lives in the engine.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.keys import KeyLike, MouseButton
from .clock import CancelToken


@runtime_checkable
class KeyboardPort(Protocol):
    """Synthetic keyboard input."""

    def type_text(self, text: str) -> None:
        """Type a literal string as-is, without added delays."""
        ...

    def key_down(self, key: KeyLike) -> None:
        """Press ``key`` and hold it."""
        ...

    def key_up(self, key: KeyLike) -> None:
        """Release ``key``. Must not raise if the key was not held."""
        ...


@runtime_checkable
class MousePort(Protocol):
    """Synthetic pointer input."""

    def position(self) -> tuple[int, int]:
        """Current pointer position in screen coordinates."""
        ...

    def move_to(
        self, x: int, y: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        """Move the pointer to an absolute position over ``duration_ms``.

        Implementations should block for approximately ``duration_ms`` and must
        abandon the movement as soon as ``cancel`` reports a stop, so an
        emergency stop is never delayed by a long movement.
        """
        ...

    def move_by(
        self, dx: int, dy: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        """Move the pointer relative to its current position."""
        ...

    def button_down(self, button: MouseButton) -> None:
        """Press and hold ``button``."""
        ...

    def button_up(self, button: MouseButton) -> None:
        """Release ``button``. Must not raise if it was not held."""
        ...
