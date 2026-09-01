"""Monitor layout adapters.

``pymonctl`` ships as a pywinctl dependency, so reading the monitor layout adds
no new package. It is imported lazily and every failure degrades to "unknown"
geometry, which disables coordinate validation instead of blocking a run.

Coordinate spaces differ per platform and are reported, not guessed:

* Windows and X11 hand the input APIs physical pixels.
* macOS uses logical points; a Retina display has two device pixels per point.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.screen import CoordinateSpace, MonitorInfo, ScreenGeometry
from ..core.target import PlatformName

logger = logging.getLogger(__name__)

_COORDINATE_SPACES = {
    PlatformName.WINDOWS: CoordinateSpace.PHYSICAL,
    PlatformName.MACOS: CoordinateSpace.LOGICAL,
    PlatformName.LINUX: CoordinateSpace.PHYSICAL,
    PlatformName.UNKNOWN: CoordinateSpace.UNKNOWN,
}


class NullScreens:
    """Screen port for hosts whose geometry cannot be read."""

    def __init__(self, reason: str = "no screen adapter is available") -> None:
        self._reason = reason

    def geometry(self) -> ScreenGeometry:
        return ScreenGeometry.unknown(self._reason)


class PyMonCtlScreens:
    """Reads the monitor layout through pymonctl."""

    def __init__(self, platform: PlatformName, module: Any | None = None) -> None:
        self._platform = platform
        self._module = module if module is not None else self._import_pymonctl()

    @staticmethod
    def _import_pymonctl() -> Any | None:
        try:
            import pymonctl
        except Exception as exc:
            logger.info("pymonctl unavailable: %s", exc)
            return None
        return pymonctl

    def geometry(self) -> ScreenGeometry:
        if self._module is None:
            return ScreenGeometry.unknown("pymonctl is not installed")
        try:
            monitors = list(self._module.getAllMonitors())
        except Exception as exc:
            logger.info("monitor enumeration failed: %s", exc)
            return ScreenGeometry.unknown(f"monitor enumeration failed: {exc}")
        if not monitors:
            return ScreenGeometry.unknown("the platform reported no monitors")

        infos: list[MonitorInfo] = []
        seen: set[tuple[str, int, int, int, int]] = set()
        for index, monitor in enumerate(monitors):
            info = self._to_info(monitor, is_first=index == 0)
            if info is None:
                continue
            # pymonctl can report the same monitor several times; a duplicate
            # entry is never meaningful and would distort the desktop bounds.
            key = (info.name, info.x, info.y, info.width, info.height)
            if key in seen:
                continue
            seen.add(key)
            infos.append(info)
        if not infos:
            return ScreenGeometry.unknown("monitor details could not be read")
        return ScreenGeometry(
            monitors=tuple(infos),
            coordinate_space=_COORDINATE_SPACES.get(self._platform, CoordinateSpace.UNKNOWN),
        )

    def _to_info(self, monitor: Any, *, is_first: bool) -> MonitorInfo | None:
        try:
            position = monitor.position
            size = monitor.size
        except Exception:
            return None
        try:
            name = str(monitor.name)
        except Exception:
            name = "display"
        try:
            primary = bool(monitor.isPrimary)
        except Exception:
            primary = is_first
        scale: float | None = None
        try:  # pymonctl returns None where the backend cannot report scaling
            raw_scale = monitor.scale
            if raw_scale is not None:
                first = raw_scale[0] if isinstance(raw_scale, (tuple, list)) else raw_scale
                scale = float(first) / 100.0 if float(first) > 10 else float(first)
        except Exception:
            scale = None
        return MonitorInfo(
            name=name,
            x=int(position[0]),
            y=int(position[1]),
            width=int(size[0]),
            height=int(size[1]),
            is_primary=primary,
            scale=scale,
        )
