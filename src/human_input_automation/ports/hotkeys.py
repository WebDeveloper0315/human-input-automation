"""Global emergency-stop hotkey port.

A global hotkey is a *convenience*, never the primary safety control: the
on-screen emergency stop must work whether or not a hotkey can be registered.
Implementations therefore report their support honestly instead of pretending
to have grabbed a key they did not get.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class HotkeyPort(Protocol):
    """Registers one global hotkey that triggers an emergency stop."""

    @property
    def description(self) -> str:
        """Human-readable combination, e.g. ``Ctrl+Shift+F9``."""
        ...

    @property
    def is_active(self) -> bool:
        """True only once the hotkey is actually listening."""
        ...

    def start(self, on_trigger: Callable[[], None]) -> bool:
        """Begin listening. Returns False when the platform will not allow it.

        ``on_trigger`` is called from the listener's own thread and must only
        signal a stop - never touch a GUI directly.
        """
        ...

    def stop(self) -> None:
        """Stop listening. Must be safe to call when never started."""
        ...
