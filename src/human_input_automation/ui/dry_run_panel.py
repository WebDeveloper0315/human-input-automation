"""Dry-run preview panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QListWidget, QVBoxLayout

from .models import DryRunView


class DryRunPanel(QGroupBox):
    """Shows what a run would do, without any input being sent."""

    def __init__(self) -> None:
        super().__init__("Dry run / preview")
        layout = QVBoxLayout(self)

        self.header_label = QLabel(DryRunView().header)
        header_font = self.header_label.font()
        header_font.setBold(True)
        self.header_label.setFont(header_font)
        self.header_label.setAccessibleName("Dry run notice")

        self.target_label = QLabel("Target: none selected")
        self.target_label.setWordWrap(True)
        self.duration_label = QLabel("Estimated duration: -")
        self.result_label = QLabel("Run a dry run to preview the plan.")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.actions_view = QListWidget()
        self.actions_view.setAccessibleName("Dry run actions")
        self.actions_view.setMaximumHeight(120)

        layout.addWidget(self.header_label)
        layout.addWidget(self.target_label)
        layout.addWidget(self.duration_label)
        layout.addWidget(self.actions_view)
        layout.addWidget(self.result_label)

    def show_view(self, view: DryRunView) -> None:
        self.header_label.setText(view.header)
        self.target_label.setText(view.target_text)
        self.duration_label.setText(view.estimated_duration)
        self.actions_view.clear()
        self.actions_view.addItems(list(view.lines))
        warnings = "".join(f"\nWarning: {warning}" for warning in view.warnings)
        self.result_label.setText(f"{view.result}{warnings}")

    @property
    def action_lines(self) -> list[str]:
        return [self.actions_view.item(row).text() for row in range(self.actions_view.count())]
