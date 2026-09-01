"""Screen geometry and the coordinate space it belongs to."""

from __future__ import annotations

from human_input_automation.core.screen import CoordinateSpace, MonitorInfo, ScreenGeometry


def geometry(
    *monitors: MonitorInfo, space: CoordinateSpace = CoordinateSpace.PHYSICAL
) -> ScreenGeometry:
    return ScreenGeometry(monitors=monitors, coordinate_space=space)


PRIMARY = MonitorInfo("primary", 0, 0, 1920, 1080, is_primary=True)
RIGHT = MonitorInfo("right", 1920, 0, 1920, 1080)
LEFT = MonitorInfo("left", -1920, 0, 1920, 1080)
ABOVE = MonitorInfo("above", 0, -1080, 1920, 1080)


def test_single_monitor_bounds() -> None:
    assert geometry(PRIMARY).virtual_bounds() == (0, 0, 1920, 1080)


def test_monitor_to_the_right_extends_the_desktop() -> None:
    """The layout on the machine this was developed on: two 1920x1080 side by side."""
    assert geometry(PRIMARY, RIGHT).virtual_bounds() == (0, 0, 3840, 1080)
    assert geometry(PRIMARY, RIGHT).is_multi_monitor


def test_monitor_left_of_primary_produces_negative_coordinates() -> None:
    bounds = geometry(PRIMARY, LEFT).virtual_bounds()
    assert bounds == (-1920, 0, 1920, 1080)
    assert geometry(PRIMARY, LEFT).contains(-100, 500)


def test_monitor_above_primary_produces_negative_y() -> None:
    assert geometry(PRIMARY, ABOVE).virtual_bounds() == (0, -1080, 1920, 1080)
    assert geometry(PRIMARY, ABOVE).contains(10, -10)


def test_points_in_the_gap_between_monitors_are_not_contained() -> None:
    detached = MonitorInfo("detached", 3000, 0, 1920, 1080)
    layout = geometry(PRIMARY, detached)
    assert layout.virtual_bounds() == (0, 0, 4920, 1080)
    assert not layout.contains(2500, 500), "the gap is inside the bounds but on no monitor"
    assert layout.contains(3100, 500)


def test_monitor_at_identifies_the_display() -> None:
    layout = geometry(PRIMARY, RIGHT)
    monitor = layout.monitor_at(2000, 100)
    assert monitor is not None and monitor.name == "right"
    assert layout.monitor_at(10_000, 10_000) is None


def test_edges_are_exclusive_on_the_far_side() -> None:
    layout = geometry(PRIMARY)
    assert layout.contains(0, 0)
    assert not layout.contains(1920, 0)
    assert not layout.contains(0, 1080)


def test_unknown_geometry_accepts_every_coordinate() -> None:
    """Refusing to run because we could not measure the desktop would be worse."""
    unknown = ScreenGeometry.unknown("no backend")
    assert not unknown.is_known
    assert unknown.contains(-5000, 99999)
    assert "no backend" in unknown.describe()


def test_scale_is_optional_and_reported_as_unknown() -> None:
    assert "scale unknown" in PRIMARY.describe()
    assert "scale 2x" in MonitorInfo("retina", 0, 0, 1440, 900, scale=2.0).describe()


def test_describe_states_the_coordinate_space() -> None:
    text = geometry(PRIMARY, RIGHT, space=CoordinateSpace.LOGICAL).describe()
    assert "3840x1080" in text and "logical coordinates" in text
