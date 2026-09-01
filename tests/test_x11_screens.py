"""Monitor layout from RandR, driven by a fake X display.

Regression cover for a real defect found in Phase 6: with DISPLAY pointing at a
1024x768 X server, pymonctl reported seven monitors - the real one three times
plus two monitors belonging to a *different* display twice each - producing a
3840x1080 desktop. Coordinate validation would then have accepted points that
are nowhere on screen.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from human_input_automation.adapters.x11_screens import X11Screens
from human_input_automation.core.screen import CoordinateSpace


class FakeMonitor(SimpleNamespace):
    pass


def monitor(name: int, x: int, y: int, width: int, height: int, primary: int = 0) -> FakeMonitor:
    return FakeMonitor(
        name=name, x=x, y=y, width_in_pixels=width, height_in_pixels=height, primary=primary
    )


class FakeDisplay:
    def __init__(self, width: int = 1024, height: int = 768, names: dict[int, str] | None = None):
        self.width = width
        self.height = height
        self.names = names or {}
        self.closed = False

    def screen(self) -> Any:
        return SimpleNamespace(
            root=SimpleNamespace(), width_in_pixels=self.width, height_in_pixels=self.height
        )

    def get_atom_name(self, atom: int) -> str:
        return self.names[atom]

    def close(self) -> None:
        self.closed = True


class BrokenDisplay(FakeDisplay):
    def screen(self) -> Any:
        raise RuntimeError("X connection lost")


def randr_returning(*monitors: FakeMonitor) -> SimpleNamespace:
    return SimpleNamespace(
        get_monitors=lambda root: SimpleNamespace(monitors=list(monitors))
    )


def randr_failing() -> SimpleNamespace:
    def explode(root: Any) -> Any:
        raise RuntimeError("RandR not supported")

    return SimpleNamespace(get_monitors=explode)


def test_a_single_monitor_display_is_read_exactly() -> None:
    display = FakeDisplay(1024, 768, {1: "screen"})
    screens = X11Screens(display, randr_returning(monitor(1, 0, 0, 1024, 768, primary=1)))
    geometry = screens.geometry()
    assert geometry.is_known
    assert not geometry.is_multi_monitor
    assert geometry.virtual_bounds() == (0, 0, 1024, 768)
    assert geometry.monitors[0].name == "screen"
    assert geometry.monitors[0].is_primary
    assert geometry.coordinate_space is CoordinateSpace.PHYSICAL


def test_two_monitors_side_by_side() -> None:
    """The layout of the machine this was developed on."""
    display = FakeDisplay(3840, 1080, {1: "HDMI-2", 2: "DP-1"})
    geometry = X11Screens(
        display,
        randr_returning(
            monitor(1, 0, 0, 1920, 1080, primary=1), monitor(2, 1920, 0, 1920, 1080)
        ),
    ).geometry()
    assert geometry.virtual_bounds() == (0, 0, 3840, 1080)
    assert [m.name for m in geometry.monitors] == ["HDMI-2", "DP-1"]
    assert geometry.monitors[0].is_primary and not geometry.monitors[1].is_primary


def test_a_monitor_left_of_the_primary_keeps_its_negative_origin() -> None:
    display = FakeDisplay(3840, 1080, {1: "left", 2: "primary"})
    geometry = X11Screens(
        display,
        randr_returning(monitor(1, -1920, 0, 1920, 1080), monitor(2, 0, 0, 1920, 1080, primary=1)),
    ).geometry()
    assert geometry.virtual_bounds() == (-1920, 0, 1920, 1080)
    assert geometry.contains(-100, 500)


def test_scale_is_reported_as_unknown_not_assumed() -> None:
    display = FakeDisplay(1024, 768, {1: "screen"})
    geometry = X11Screens(display, randr_returning(monitor(1, 0, 0, 1024, 768))).geometry()
    assert geometry.monitors[0].scale is None
    assert "scale unknown" in geometry.monitors[0].describe()


def test_zero_sized_monitors_are_ignored() -> None:
    display = FakeDisplay(1024, 768, {1: "real", 2: "disconnected"})
    geometry = X11Screens(
        display, randr_returning(monitor(1, 0, 0, 1024, 768), monitor(2, 0, 0, 0, 0))
    ).geometry()
    assert [m.name for m in geometry.monitors] == ["real"]


def test_the_x_screen_is_used_when_randr_is_unavailable() -> None:
    geometry = X11Screens(FakeDisplay(1280, 1024), randr_failing()).geometry()
    assert geometry.is_known
    assert geometry.virtual_bounds() == (0, 0, 1280, 1024)
    assert geometry.monitors[0].is_primary


def test_a_broken_display_yields_unknown_geometry_rather_than_raising() -> None:
    geometry = X11Screens(BrokenDisplay(), randr_failing()).geometry()
    assert not geometry.is_known
    assert geometry.reason


def test_unknown_geometry_disables_coordinate_validation() -> None:
    """Better to attempt a move than to block a run because we cannot measure."""
    geometry = X11Screens(BrokenDisplay(), randr_failing()).geometry()
    assert geometry.contains(99_999, 99_999)


def test_close_releases_the_display() -> None:
    display = FakeDisplay()
    screens = X11Screens(display, randr_failing())
    screens.geometry()
    screens.close()
    assert display.closed
    screens.close()  # safe to call twice
