"""Capturing a screen position by dragging to it."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI extra not installed")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QSpinBox

from human_input_automation.core.actions import MouseClick, MouseMove
from human_input_automation.core.screen import CoordinateSpace, MonitorInfo, ScreenGeometry
from human_input_automation.ui.action_editor import ActionDialog
from human_input_automation.ui.models import PointerSource, position_readout
from human_input_automation.ui.position_picker import PositionPicker

pytestmark = pytest.mark.usefixtures("qt_app")


class FakePointer:
    """A pointer the test moves by hand, in place of a real desktop."""

    def __init__(self, *positions: tuple[int, int]) -> None:
        self.positions = list(positions) or [(0, 0)]
        self.reads = 0

    def __call__(self) -> tuple[int, int] | None:
        self.reads += 1
        # Stay on the last position once the script runs out, the way a pointer
        # that has stopped moving would.
        return self.positions[min(self.reads - 1, len(self.positions) - 1)]

    def at(self, x: int, y: int) -> None:
        self.positions = [(x, y)]
        self.reads = 0


def drag(picker: PositionPicker) -> None:
    """Press and release on the picker; the pointer script does the moving."""
    QTest.mousePress(picker, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(picker, Qt.MouseButton.LeftButton)


TWO_SCREENS = ScreenGeometry(
    monitors=(
        MonitorInfo("HDMI-1", 0, 0, 1920, 1080, is_primary=True),
        MonitorInfo("DP-2", 1920, 0, 1280, 1024),
    ),
    coordinate_space=CoordinateSpace.PHYSICAL,
)


# ---------------------------------------------------------------------------
# The picker
# ---------------------------------------------------------------------------


def test_dragging_captures_the_position_the_pointer_ends_on() -> None:
    pointer = FakePointer((10, 10), (640, 400))
    picker = PositionPicker(pointer)
    captured: list[tuple[int, int]] = []
    picker.picked.connect(lambda x, y: captured.append((x, y)))

    drag(picker)

    assert captured == [(640, 400)]
    assert not picker.is_dragging


def test_dragging_in_relative_mode_captures_the_distance_travelled() -> None:
    pointer = FakePointer((500, 500), (460, 512))
    picker = PositionPicker(pointer)
    picker.set_relative(True)
    captured: list[tuple[int, int]] = []
    picker.picked.connect(lambda x, y: captured.append((x, y)))

    drag(picker)

    assert captured == [(-40, 12)]
    assert "movement" in picker.text()


def test_the_position_is_reported_while_the_drag_is_still_going() -> None:
    pointer = FakePointer((10, 10), (300, 200))
    picker = PositionPicker(pointer)
    seen: list[tuple[int, int]] = []
    picker.moved.connect(lambda x, y: seen.append((x, y)))

    QTest.mousePress(picker, Qt.MouseButton.LeftButton)
    assert picker.is_dragging
    assert seen == [(300, 200)]  # reported as soon as the drag starts
    QTest.mouseRelease(picker, Qt.MouseButton.LeftButton)


def test_a_drag_announces_its_start_and_end() -> None:
    picker = PositionPicker(FakePointer((1, 2)))
    events: list[str] = []
    picker.drag_started.connect(lambda: events.append("start"))
    picker.drag_finished.connect(lambda: events.append("end"))

    drag(picker)

    assert events == ["start", "end"]


def test_the_picker_is_unusable_when_the_pointer_cannot_be_read() -> None:
    """A host with no real pointer says so rather than capturing (0, 0)."""
    picker = PositionPicker(None)
    captured: list[tuple[int, int]] = []
    picker.picked.connect(lambda x, y: captured.append((x, y)))

    assert not picker.isEnabled()
    assert "type the coordinates" in picker.toolTip()
    drag(picker)
    assert captured == []


def test_a_pointer_that_stops_answering_captures_nothing() -> None:
    class Silent:
        def __call__(self) -> tuple[int, int] | None:
            return None

    picker = PositionPicker(Silent())
    captured: list[tuple[int, int]] = []
    picker.picked.connect(lambda x, y: captured.append((x, y)))

    drag(picker)

    assert captured == []
    assert not picker.is_dragging


def test_keyboard_activation_captures_where_the_pointer_stands() -> None:
    """The only form of this that works without a mouse."""
    picker = PositionPicker(FakePointer((77, 88)))
    captured: list[tuple[int, int]] = []
    picker.picked.connect(lambda x, y: captured.append((x, y)))

    picker.click()

    assert captured == [(77, 88)]


def test_keyboard_activation_measures_nothing_in_relative_mode() -> None:
    picker = PositionPicker(FakePointer((77, 88)))
    picker.set_relative(True)
    captured: list[tuple[int, int]] = []
    picker.picked.connect(lambda x, y: captured.append((x, y)))

    picker.click()

    assert captured == []


def test_a_mouse_drag_is_not_also_a_click() -> None:
    """Otherwise every drag would capture twice, once with the wrong value."""
    picker = PositionPicker(FakePointer((5, 5)))
    clicks: list[bool] = []
    picker.clicked.connect(lambda: clicks.append(True))

    drag(picker)

    assert clicks == []


# ---------------------------------------------------------------------------
# In the action dialog
# ---------------------------------------------------------------------------


def dialog_for(kind: str, pointer: Any, **screen: Any) -> ActionDialog:
    source = PointerSource(position=pointer, geometry=lambda: screen.get("screen", TWO_SCREENS))
    return ActionDialog(kind=kind, pointer=source)


def test_a_drag_fills_in_both_coordinates() -> None:
    pointer = FakePointer((0, 0), (1204, 640))
    dialog = dialog_for("mouse_move", pointer)
    assert dialog.picker is not None

    drag(dialog.picker)

    values = dialog.values()
    assert (values["x"], values["y"]) == (1204, 640)
    action = dialog.try_build()
    assert action == MouseMove(x=1204, y=640)


def test_a_drag_on_a_click_action_also_turns_the_position_on() -> None:
    """A captured position the action would then ignore is a trap."""
    pointer = FakePointer((0, 0), (300, 300))
    dialog = dialog_for("mouse_click", pointer)
    assert isinstance(dialog._editors["use_position"], QCheckBox)
    assert not dialog._editors["use_position"].isChecked()

    drag(dialog.picker)  # type: ignore[arg-type]

    assert dialog._editors["use_position"].isChecked()
    assert dialog.try_build() == MouseClick(x=300, y=300)


def test_the_picker_follows_the_relative_checkbox() -> None:
    pointer = FakePointer((500, 500), (540, 480))
    dialog = dialog_for("mouse_move", pointer)
    relative = dialog._editors["relative"]
    assert isinstance(relative, QCheckBox)
    relative.setChecked(True)

    assert dialog.picker is not None and dialog.picker.relative
    drag(dialog.picker)

    assert dialog.try_build() == MouseMove(x=40, y=-20, relative=True)


def test_the_dialog_gets_out_of_the_way_while_a_position_is_picked() -> None:
    """The point being aimed at is often behind this very dialog."""
    dialog = dialog_for("mouse_move", FakePointer((10, 10)))
    assert dialog.picker is not None

    QTest.mousePress(dialog.picker, Qt.MouseButton.LeftButton)
    # Qt keeps opacity to 8 bits, so 0.3 comes back as 76/255.
    assert dialog.windowOpacity() == pytest.approx(ActionDialog.DRAGGING_OPACITY, abs=0.01)
    QTest.mouseRelease(dialog.picker, Qt.MouseButton.LeftButton)
    assert dialog.windowOpacity() == pytest.approx(1.0)


def test_the_dialog_says_where_a_captured_point_landed() -> None:
    dialog = dialog_for("mouse_move", FakePointer((0, 0), (2000, 500)))
    assert dialog.position_label is not None

    drag(dialog.picker)  # type: ignore[arg-type]

    assert "DP-2" in dialog.position_label.text()


def test_an_action_without_coordinates_has_no_picker() -> None:
    assert ActionDialog(kind="type_text").picker is None
    assert ActionDialog(kind="key_press").picker is None


def test_the_picker_appears_when_the_action_type_changes() -> None:
    dialog = ActionDialog(kind="type_text", pointer=PointerSource(position=FakePointer((1, 1))))
    assert "x" not in dialog.values()  # nothing to capture, so nothing to capture with

    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("mouse_move"))

    assert dialog.picker is not None
    assert isinstance(dialog._editors["x"], QSpinBox)


def test_a_dialog_with_no_pointer_source_still_edits_coordinates() -> None:
    """The spin boxes are the primary control; the picker is a convenience."""
    dialog = ActionDialog(kind="mouse_move")
    assert dialog.picker is not None and not dialog.picker.isEnabled()

    dialog.set_values({"x": 12, "y": 34, "relative": False, "duration_ms": None})
    assert dialog.try_build() == MouseMove(x=12, y=34)


# ---------------------------------------------------------------------------
# The readout
# ---------------------------------------------------------------------------


def test_the_readout_names_the_monitor_a_point_is_on() -> None:
    assert position_readout((100, 100), screen=TWO_SCREENS) == "(100, 100) on HDMI-1"
    assert position_readout((2000, 100), screen=TWO_SCREENS) == "(2000, 100) on DP-2"


def test_the_readout_flags_a_point_on_no_monitor_at_all() -> None:
    text = position_readout((5000, 5000), screen=TWO_SCREENS)
    assert "not on any monitor" in text


def test_the_readout_shows_a_signed_distance_in_relative_mode() -> None:
    assert "(-40, +12)" in position_readout((-40, 12), relative=True)


def test_the_readout_says_nothing_it_cannot_know() -> None:
    assert position_readout((10, 20)) == "(10, 20)"
    assert position_readout((10, 20), screen=ScreenGeometry.unknown()) == "(10, 20)"
    assert "drag" in position_readout(None).lower()
