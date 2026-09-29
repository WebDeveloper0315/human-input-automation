"""Capturing a screen position by dragging to it.

Typing coordinates into two spin boxes means reading them off somewhere else
first, or guessing. This is the other way round: press the handle, drag the
pointer to the place you mean, and let go.

Two things make it trustworthy rather than merely convenient:

* the position is read through the **same port that will move the pointer**
  during a run, never from the window system. On a scaled display those two do
  not agree - Qt reports logical pixels where the input backend may want
  physical ones - and a coordinate the run cannot reproduce is worse than no
  coordinate at all;
* it only ever *reads*. Nothing here moves the pointer or sends a click; the
  hand on the mouse is the user's throughout.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QPushButton, QWidget

#: How often the pointer is read while a drag is in progress. Fast enough to
#: read as live, and a single cheap call to the platform each time.
POLL_INTERVAL_MS = 30

#: Reads the pointer, or returns ``None`` when this host has none to read.
PointerReader = Callable[[], "tuple[int, int] | None"]


class PositionPicker(QPushButton):
    """Press, drag to a point on the screen, release.

    Emits :attr:`moved` continuously during the drag and :attr:`picked` once at
    the end. In relative mode both carry the distance travelled since the press
    instead of the position landed on, so a "move by" action can be measured by
    dragging exactly the same way.

    Keyboard activation (Space or Return) captures wherever the pointer is
    standing, which is the only form of this that works without a mouse. There
    is nothing to measure that way in relative mode, so it does nothing there.
    """

    #: The captured value: a position, or a distance in relative mode.
    picked = Signal(int, int)
    #: The value as it stands mid-drag.
    moved = Signal(int, int)
    drag_started = Signal()
    drag_finished = Signal()

    def __init__(
        self, read_pointer: PointerReader | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__("Drag to a point on screen", parent)
        self._read_pointer = read_pointer
        self._origin: tuple[int, int] | None = None
        self._relative = False

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._report_position)

        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName("Pick a screen position")
        self.setAccessibleDescription(
            "Press and drag to a point on the screen to capture its coordinates, "
            "or press Space to capture wherever the pointer is standing."
        )
        self.clicked.connect(self._capture_where_the_pointer_stands)
        self.setEnabled(read_pointer is not None)
        if read_pointer is None:
            self.setToolTip(
                "This host cannot report where the pointer is; type the coordinates instead."
            )

    # -- state -------------------------------------------------------------
    @property
    def is_dragging(self) -> bool:
        return self._origin is not None

    @property
    def relative(self) -> bool:
        return self._relative

    def set_relative(self, relative: bool) -> None:
        """Capture a distance rather than a position."""
        self._relative = bool(relative)
        self.setText(
            "Drag to measure a movement" if self._relative else "Drag to a point on screen"
        )

    # -- dragging ----------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is not Qt.MouseButton.LeftButton or self._read_pointer is None:
            super().mousePressEvent(event)
            return
        origin = self._read_pointer()
        if origin is None:
            super().mousePressEvent(event)
            return
        # Qt delivers every further move and the release to this widget, even
        # while the pointer is over another application's window, so the drag
        # can end anywhere on the desktop.
        self._origin = origin
        self.setDown(True)
        self._timer.start()
        self.drag_started.emit()
        self._report_position()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # The position comes from the timer, which reads the same port the run
        # will use; Qt's own idea of where the pointer is never gets a vote.
        if self._origin is None:
            super().mouseMoveEvent(event)
            return
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._origin is None:
            super().mouseReleaseEvent(event)
            return
        self._timer.stop()
        self.setDown(False)
        value = self.current_value()
        self._origin = None
        self.drag_finished.emit()
        if value is not None:
            self.picked.emit(*value)
        event.accept()

    def current_value(self) -> tuple[int, int] | None:
        """What a release right now would capture."""
        if self._read_pointer is None:
            return None
        position = self._read_pointer()
        if position is None:
            return None
        if not self._relative:
            return position
        if self._origin is None:
            return None
        return (position[0] - self._origin[0], position[1] - self._origin[1])

    # -- internals ---------------------------------------------------------
    def _report_position(self) -> None:
        value = self.current_value()
        if value is not None:
            self.moved.emit(*value)

    def _capture_where_the_pointer_stands(self) -> None:
        """Keyboard activation. Mouse presses never reach this - they are
        handled above and deliberately do not emit ``clicked``."""
        if self._relative:
            return
        value = self.current_value()
        if value is not None:
            self.picked.emit(*value)
