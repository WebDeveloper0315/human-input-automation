"""The pymonctl screen adapter, driven by a fake module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from human_input_automation.adapters.screens import NullScreens, PyMonCtlScreens
from human_input_automation.core.screen import CoordinateSpace
from human_input_automation.core.target import PlatformName


def monitor(
    name: str, x: int, y: int, w: int, h: int, primary: bool = False, scale: Any = None
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        position=(x, y),
        size=(w, h),
        isPrimary=primary,
        scale=scale,
    )


def module(*monitors: Any, fail: bool = False) -> SimpleNamespace:
    def get_all() -> list[Any]:
        if fail:
            raise RuntimeError("no display")
        return list(monitors)

    return SimpleNamespace(getAllMonitors=get_all)


def test_monitors_are_mapped_with_positions_and_sizes() -> None:
    """Mirrors the real two-monitor layout this was developed against."""
    adapter = PyMonCtlScreens(
        PlatformName.LINUX,
        module(
            monitor("HDMI-2", 0, 0, 1920, 1080, primary=True),
            monitor("DP-1", 1920, 0, 1920, 1080),
        ),
    )
    geometry = adapter.geometry()
    assert geometry.is_known and geometry.is_multi_monitor
    assert geometry.virtual_bounds() == (0, 0, 3840, 1080)
    assert geometry.monitors[0].is_primary
    assert geometry.coordinate_space is CoordinateSpace.PHYSICAL


def test_macos_is_reported_as_logical_coordinates() -> None:
    adapter = PyMonCtlScreens(PlatformName.MACOS, module(monitor("Retina", 0, 0, 1440, 900)))
    assert adapter.geometry().coordinate_space is CoordinateSpace.LOGICAL


def test_missing_scale_stays_unknown_rather_than_defaulting_to_one() -> None:
    adapter = PyMonCtlScreens(PlatformName.LINUX, module(monitor("HDMI-2", 0, 0, 1920, 1080)))
    assert adapter.geometry().monitors[0].scale is None


def test_percentage_scaling_is_normalised() -> None:
    adapter = PyMonCtlScreens(
        PlatformName.WINDOWS, module(monitor("Laptop", 0, 0, 2560, 1440, scale=(150, 150)))
    )
    assert adapter.geometry().monitors[0].scale == 1.5


def test_backend_failure_degrades_to_unknown_geometry() -> None:
    adapter = PyMonCtlScreens(PlatformName.LINUX, module(fail=True))
    geometry = adapter.geometry()
    assert not geometry.is_known
    assert "no display" in geometry.reason


def test_no_monitors_is_unknown_not_an_empty_desktop() -> None:
    adapter = PyMonCtlScreens(PlatformName.LINUX, module())
    assert not adapter.geometry().is_known


def test_a_monitor_that_cannot_be_read_is_skipped() -> None:
    broken = SimpleNamespace()
    adapter = PyMonCtlScreens(
        PlatformName.LINUX, module(broken, monitor("ok", 0, 0, 800, 600))
    )
    geometry = adapter.geometry()
    assert [m.name for m in geometry.monitors] == ["ok"]


def test_missing_pymonctl_is_unknown_geometry() -> None:
    adapter = PyMonCtlScreens(PlatformName.LINUX, module())
    adapter._module = None  # simulate the import having failed
    assert "not installed" in adapter.geometry().reason


def test_null_screens_reports_its_reason() -> None:
    assert "no screen adapter" in NullScreens().geometry().reason


def test_duplicate_monitors_are_collapsed() -> None:
    """pymonctl was observed reporting the same monitor several times."""
    duplicate = monitor("HDMI-2", 0, 0, 1920, 1080, primary=True)
    adapter = PyMonCtlScreens(
        PlatformName.WINDOWS,
        module(duplicate, monitor("HDMI-2", 0, 0, 1920, 1080, primary=True),
               monitor("DP-1", 1920, 0, 1920, 1080)),
    )
    geometry = adapter.geometry()
    assert [m.name for m in geometry.monitors] == ["HDMI-2", "DP-1"]
    assert geometry.virtual_bounds() == (0, 0, 3840, 1080)
