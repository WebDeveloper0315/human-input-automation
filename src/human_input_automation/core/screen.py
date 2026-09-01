"""Screen geometry.

Absolute mouse coordinates only mean something relative to a coordinate space,
and the three platforms do not agree on one:

* **Windows** reports physical pixels to the input APIs, but per-monitor DPI
  scaling means the numbers a user reads off a screenshot may be logical.
* **macOS** uses logical points; a Retina display has two device pixels per
  point, so a "2560 wide" screenshot is a 1280-point-wide screen.
* **X11** uses physical pixels across a single virtual screen.

Rather than guessing, the coordinate space is reported explicitly and defaults
to :attr:`CoordinateSpace.UNKNOWN`. Validation only rejects coordinates when the
geometry is actually known.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CoordinateSpace(StrEnum):
    """Which pixels an (x, y) pair refers to."""

    PHYSICAL = "physical"
    LOGICAL = "logical"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MonitorInfo:
    """One display in the virtual desktop.

    ``scale`` is ``None`` when the backend cannot report it - which is the case
    for the X11 backend used on Linux.
    """

    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool = False
    scale: float | None = None

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def describe(self) -> str:
        scale = f", scale {self.scale:g}x" if self.scale else ", scale unknown"
        primary = " (primary)" if self.is_primary else ""
        return f"{self.name}{primary}: {self.width}x{self.height} at ({self.x}, {self.y}){scale}"


@dataclass(frozen=True)
class ScreenGeometry:
    """The virtual desktop: every monitor plus the coordinate space in use."""

    monitors: tuple[MonitorInfo, ...] = field(default_factory=tuple)
    coordinate_space: CoordinateSpace = CoordinateSpace.UNKNOWN
    reason: str = ""

    @classmethod
    def unknown(cls, reason: str = "screen geometry could not be determined") -> ScreenGeometry:
        return cls(reason=reason)

    @property
    def is_known(self) -> bool:
        return bool(self.monitors)

    @property
    def is_multi_monitor(self) -> bool:
        return len(self.monitors) > 1

    def virtual_bounds(self) -> tuple[int, int, int, int]:
        """``(left, top, right, bottom)`` of the whole desktop.

        Monitors placed left of or above the primary produce negative
        coordinates, which is normal and must not be treated as invalid.
        """
        if not self.monitors:
            return (0, 0, 0, 0)
        return (
            min(monitor.x for monitor in self.monitors),
            min(monitor.y for monitor in self.monitors),
            max(monitor.right for monitor in self.monitors),
            max(monitor.bottom for monitor in self.monitors),
        )

    def contains(self, x: int, y: int) -> bool:
        """True when the point falls on a real monitor.

        Unknown geometry accepts everything: refusing to run because we could
        not measure the desktop would be worse than trying.
        """
        if not self.monitors:
            return True
        return any(monitor.contains(x, y) for monitor in self.monitors)

    def monitor_at(self, x: int, y: int) -> MonitorInfo | None:
        return next((monitor for monitor in self.monitors if monitor.contains(x, y)), None)

    def describe(self) -> str:
        if not self.monitors:
            if self.reason:
                return f"screen geometry unknown ({self.reason})"
            return "screen geometry unknown"
        left, top, right, bottom = self.virtual_bounds()
        return (
            f"{len(self.monitors)} monitor(s), virtual desktop "
            f"{right - left}x{bottom - top} from ({left}, {top}), "
            f"{self.coordinate_space.value} coordinates"
        )
