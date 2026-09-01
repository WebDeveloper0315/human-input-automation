"""Screen geometry port.

Coordinate validation needs to know where the monitors are. That is platform
knowledge, so the core only sees this interface and a
:class:`~..core.screen.ScreenGeometry` value object.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.screen import ScreenGeometry


@runtime_checkable
class ScreenPort(Protocol):
    """Reports the monitor layout."""

    def geometry(self) -> ScreenGeometry:
        """Current monitor layout.

        Must never raise: an unavailable backend returns
        :meth:`ScreenGeometry.unknown`, and unknown geometry disables coordinate
        validation rather than blocking a run.
        """
        ...
