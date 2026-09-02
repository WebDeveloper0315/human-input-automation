"""Run controls: start, pause, resume, stop, dry run and the emergency stop."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from .models import ControlsState

#: The emergency stop is styled to stand out, but its meaning is carried by its
#: label and accessible name - never by colour alone.
_EMERGENCY_STYLE = (
    "QPushButton { background-color: #b3261e; color: white; font-weight: bold; padding: 12px; }"
    "QPushButton:hover { background-color: #8c1d18; }"
    "QPushButton:focus { border: 2px solid #000000; }"
)


class RunControls(QGroupBox):
    """Buttons that drive the run, plus the always-available emergency stop."""

    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    emergency_requested = Signal()
    dry_run_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Run")
        layout = QVBoxLayout(self)

        self.status_label = QLabel("Idle")
        self.status_label.setAccessibleName("Run state")
        status_font = self.status_label.font()
        status_font.setBold(True)
        self.status_label.setFont(status_font)

        self.countdown_label = QLabel("")
        self.countdown_label.setAccessibleName("Countdown")
        self.countdown_label.setVisible(False)

        self.countdown_spin = QSpinBox()
        self.countdown_spin.setRange(0, 60)
        self.countdown_spin.setValue(3)
        self.countdown_spin.setSuffix(" s countdown")
        self.countdown_spin.setAccessibleName("Countdown before starting")
        self.countdown_spin.setToolTip("Seconds to wait before the target is activated")

        self.minimise_check = QCheckBox("Minimise while running")
        self.minimise_check.setChecked(True)
        self.minimise_check.setAccessibleName("Minimise the window while running")
        self.minimise_check.setToolTip(
            "Get this window out of the way during a run. A small always-on-top "
            "emergency stop stays visible."
        )

        self.start_button = QPushButton("Start")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        self.dry_run_button = QPushButton("Dry run")

        self.emergency_button = QPushButton("EMERGENCY STOP")
        self.emergency_button.setStyleSheet(_EMERGENCY_STYLE)
        self.emergency_button.setAccessibleName("Emergency stop")
        self.emergency_button.setAccessibleDescription(
            "Immediately stop automation and release any held keys or buttons"
        )
        self.emergency_button.setShortcut(QKeySequence("Ctrl+."))
        self.emergency_button.setToolTip("Stop everything now (Ctrl+.)")
        self.emergency_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.emergency_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.start_button.clicked.connect(self.start_requested.emit)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.dry_run_button.clicked.connect(self.dry_run_requested.emit)
        self.emergency_button.clicked.connect(self.emergency_requested.emit)

        row = QHBoxLayout()
        for button, name in (
            (self.start_button, "Start automation"),
            (self.pause_button, "Pause automation"),
            (self.resume_button, "Resume automation"),
            (self.stop_button, "Stop automation"),
            (self.dry_run_button, "Dry run preview"),
        ):
            button.setAccessibleName(name)
            row.addWidget(button)
        row.addWidget(self.countdown_spin)
        row.addWidget(self.minimise_check)
        row.addStretch(1)

        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.countdown_label)
        status_row.addStretch(1)

        layout.addLayout(status_row)
        layout.addLayout(row)
        layout.addWidget(self.emergency_button)

        self.setTabOrder(self.start_button, self.pause_button)
        self.setTabOrder(self.pause_button, self.resume_button)
        self.setTabOrder(self.resume_button, self.stop_button)
        self.setTabOrder(self.stop_button, self.dry_run_button)
        self.setTabOrder(self.dry_run_button, self.emergency_button)

    @property
    def countdown_seconds(self) -> float:
        return float(self.countdown_spin.value())

    @property
    def minimise_while_running(self) -> bool:
        """Whether the main window should get out of the way during a run."""
        return bool(self.minimise_check.isChecked())

    def apply_state(self, state: ControlsState) -> None:
        """Enable/disable controls. The emergency stop is never disabled."""
        self.start_button.setEnabled(state.start_enabled)
        self.pause_button.setEnabled(state.pause_enabled)
        self.resume_button.setEnabled(state.resume_enabled)
        self.stop_button.setEnabled(state.stop_enabled)
        self.dry_run_button.setEnabled(state.dry_run_enabled)
        self.countdown_spin.setEnabled(state.editing_enabled)
        self.minimise_check.setEnabled(state.editing_enabled)
        self.emergency_button.setEnabled(True)
        self.status_label.setText(f"State: {state.status_text}")
        self.status_label.setAccessibleDescription(state.status_text)

    def show_countdown(self, text: str) -> None:
        self.countdown_label.setText(text)
        self.countdown_label.setVisible(bool(text))
