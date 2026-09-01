"""Window discovery and control ports.

Discovery is used by the UI to build the target list; control is the only window
capability the engine itself needs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..core.target import TargetWindow


@runtime_checkable
class WindowDiscoveryPort(Protocol):
    """Enumerating candidate target windows."""

    def list_windows(self) -> Sequence[TargetWindow]:
        """All windows the user could target, best-effort and possibly empty."""
        ...

    def find(self, handle: str) -> TargetWindow | None:
        """Re-resolve a handle, e.g. to confirm a saved target still exists."""
        ...


@runtime_checkable
class WindowControlPort(Protocol):
    """Focusing a window and checking whether it is focused."""

    def activate(self, target: TargetWindow) -> bool:
        """Bring ``target`` to the foreground. Returns False if it failed."""
        ...

    def is_active(self, target: TargetWindow) -> bool | None:
        """Whether ``target`` currently has focus.

        Returns ``None`` when the platform cannot answer (Wayland, missing
        permissions). ``None`` means "unknown", never "no".
        """
        ...
