"""Run log panel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout


class RunLog(QGroupBox):
    """Append-only view of run events.

    Lines arrive from :class:`~.run_bridge.RunEventBridge` slots, i.e. always on
    the Qt main thread.
    """

    MAX_BLOCKS = 2000

    #: The user asked to keep the log; the window decides where it goes.
    save_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Run log")
        layout = QVBoxLayout(self)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(self.MAX_BLOCKS)
        self.view.setAccessibleName("Run log")
        self.view.setPlaceholderText("Run events appear here.")

        self.clear_button = QPushButton("Clear log")
        self.clear_button.setAccessibleName("Clear run log")
        self.clear_button.clicked.connect(self.clear)

        self.save_button = QPushButton("Save log...")
        self.save_button.setAccessibleName("Save the run log to a file")
        self.save_button.setToolTip(
            "Write everything in this log to a text file you choose - for test reports"
        )
        self.save_button.clicked.connect(self.save_requested.emit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.clear_button)

        layout.addWidget(self.view)
        layout.addLayout(buttons)

    def append_line(self, line: str) -> None:
        self.view.appendPlainText(line)

    def clear(self) -> None:
        self.view.clear()

    @property
    def lines(self) -> list[str]:
        text = self.view.toPlainText()
        return text.splitlines() if text else []
