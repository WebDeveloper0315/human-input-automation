"""Run log panel."""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout


class RunLog(QGroupBox):
    """Append-only view of run events.

    Lines arrive from :class:`~.run_bridge.RunEventBridge` slots, i.e. always on
    the Qt main thread.
    """

    MAX_BLOCKS = 2000

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

        buttons = QHBoxLayout()
        buttons.addStretch(1)
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
