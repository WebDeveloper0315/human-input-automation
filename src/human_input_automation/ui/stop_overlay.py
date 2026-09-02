"""A small always-on-top emergency stop, shown while the main window is hidden.

Minimising the application during a run keeps it out of the way of the target -
and would also hide the emergency stop, which is the one control that must never
be more than a click away. This overlay carries that control: a compact,
frameless, always-on-top window holding the stop button and the run state.

It is deliberately tiny and has exactly one action. Nothing else belongs here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

_STYLE = (
    "QPushButton { background-color: #b3261e; color: white; font-weight: bold; padding: 10px; }"
    "QPushButton:hover { background-color: #8c1d18; }"
    "QPushButton:focus { border: 2px solid #000000; }"
)


class StopOverlay(QWidget):
    """Always-on-top emergency stop for use while the main window is minimised."""

    emergency_requested = Signal()
    restore_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Automation running")
        self.setAccessibleName("Automation running - emergency stop")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        inner = QVBoxLayout(frame)

        self.status_label = QLabel("Running")
        font = self.status_label.font()
        font.setBold(True)
        self.status_label.setFont(font)
        self.status_label.setAccessibleName("Run state")

        self.stop_button = QPushButton("EMERGENCY STOP")
        self.stop_button.setStyleSheet(_STYLE)
        self.stop_button.setAccessibleName("Emergency stop")
        self.stop_button.setAccessibleDescription(
            "Immediately stop automation and release any held keys or buttons"
        )
        self.stop_button.setShortcut(QKeySequence("Ctrl+."))
        self.stop_button.setToolTip("Stop everything now (Ctrl+.)")
        self.stop_button.clicked.connect(self.emergency_requested.emit)

        self.restore_button = QPushButton("Show window")
        self.restore_button.setAccessibleName("Restore the main window")
        self.restore_button.clicked.connect(self.restore_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.stop_button, 2)
        buttons.addWidget(self.restore_button, 1)

        inner.addWidget(self.status_label)
        inner.addLayout(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(frame)
        self.resize(320, 96)

    def show_state(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setAccessibleDescription(text)

    def show_for_run(self, state_text: str) -> None:
        """Appear without stealing focus from the automation target."""
        self.show_state(state_text)
        self.show()
        self.raise_()
