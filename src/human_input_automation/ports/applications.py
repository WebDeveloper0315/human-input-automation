"""Running applications, as a whole.

Optional: where it is missing, a script finds applications through window
discovery instead, which is fast on X11 and slow on macOS.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..core.target import RunningApplication
from .clock import CancelToken


@runtime_checkable
class ApplicationPort(Protocol):
    def applications(self) -> Sequence[RunningApplication]:
        """Every application with a user interface, best-effort and possibly empty."""
        ...

    def activate_application(
        self, application: RunningApplication, cancel: CancelToken | None = None
    ) -> bool:
        """Bring the application to the front and confirm it is there.

        Returns promptly when ``cancel`` reports a stop.
        """
        ...
