"""Monitor layout for X11, read from RandR.

Why this exists: on Linux, ``pymonctl`` returns a monitor list that is both
duplicated and, worse, not necessarily for the display this process is
connected to. Verified on this machine - with ``DISPLAY`` pointing at a
1024x768 X server, ``pymonctl.getAllMonitors()`` returned seven monitors: the
1024x768 screen three times, plus the two 1920x1080 monitors of a *different*
display twice each. The resulting virtual desktop was 3840x1080 instead of
1024x768, which would let coordinate validation accept points that are nowhere
on screen.

RandR is the authoritative source for the display we actually hold a connection
to, and python-xlib is already a dependency of the X11 window adapter. Where
RandR is unavailable, the X screen dimensions are used as a single monitor.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.screen import CoordinateSpace, MonitorInfo, ScreenGeometry
from .x11_windows import open_display

logger = logging.getLogger(__name__)


class X11Screens:
    """Implements :class:`~..ports.screen.ScreenPort` for X11."""

    def __init__(
        self,
        display: Any | None = None,
        randr: Any | None = None,
        display_name: str | None = None,
    ) -> None:
        self._display = display
        self._randr = randr
        self._display_name = display_name

    def _connect(self) -> Any:
        if self._display is None:
            self._display = open_display(self._display_name)
        return self._display

    def _extension(self) -> Any | None:
        if self._randr is None:
            try:
                from Xlib.ext import randr
            except Exception as error:  # pragma: no cover - python-xlib is a dependency
                logger.info("RandR unavailable: %s", error)
                return None
            self._randr = randr
        return self._randr

    def geometry(self) -> ScreenGeometry:
        """The monitor layout of the connected display. Never raises."""
        try:
            display = self._connect()
        except Exception as error:
            return ScreenGeometry.unknown(f"no X display: {error}")

        monitors = self._from_randr(display)
        if monitors:
            return ScreenGeometry(
                monitors=tuple(monitors), coordinate_space=CoordinateSpace.PHYSICAL
            )
        fallback = self._from_screen(display)
        if fallback:
            return ScreenGeometry(
                monitors=tuple(fallback), coordinate_space=CoordinateSpace.PHYSICAL
            )
        return ScreenGeometry.unknown("the X server reported no usable screen")

    def _from_randr(self, display: Any) -> list[MonitorInfo]:
        randr = self._extension()
        if randr is None:
            return []
        try:
            root = display.screen().root
            reply = randr.get_monitors(root)
        except Exception as error:
            logger.info("RandR monitor query failed: %s", error)
            return []

        monitors: list[MonitorInfo] = []
        for monitor in getattr(reply, "monitors", []):
            try:
                name = display.get_atom_name(monitor.name)
            except Exception:
                name = "display"
            monitors.append(
                MonitorInfo(
                    name=str(name),
                    x=int(monitor.x),
                    y=int(monitor.y),
                    width=int(monitor.width_in_pixels),
                    height=int(monitor.height_in_pixels),
                    is_primary=bool(getattr(monitor, "primary", 0)),
                    # X11 reports no per-monitor scale factor; saying "unknown"
                    # is honest, assuming 1.0 would not be.
                    scale=None,
                )
            )
        return [monitor for monitor in monitors if monitor.width > 0 and monitor.height > 0]

    def _from_screen(self, display: Any) -> list[MonitorInfo]:
        """Pre-RandR fallback: the X screen is one monitor."""
        try:
            screen = display.screen()
            width = int(screen.width_in_pixels)
            height = int(screen.height_in_pixels)
        except Exception as error:
            logger.info("could not read the X screen size: %s", error)
            return []
        if width <= 0 or height <= 0:
            return []
        return [MonitorInfo(name="screen", x=0, y=0, width=width, height=height, is_primary=True)]

    def close(self) -> None:
        display, self._display = self._display, None
        if display is not None:
            try:
                display.close()
            except Exception:  # pragma: no cover - depends on the X connection
                logger.debug("failed to close the X display", exc_info=True)
