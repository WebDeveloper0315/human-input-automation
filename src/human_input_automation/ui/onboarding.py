"""First-run briefing and permission onboarding.

Shown once on first launch, and on demand from the capability banner. It
reports one entry *per permission* - on macOS, Accessibility and Input
Monitoring are separate grants that unlock different things, so a single "grant
permissions" prompt would leave the user guessing which pane to open.

The dialog never asks the OS to change a setting and never bypasses one: it
explains what is missing, what it blocks, where to grant it, and whether a
restart is needed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..metadata import METADATA
from .models import FirstRunSummary, PermissionGuidance


class OnboardingDialog(QDialog):
    """Explains the host's capabilities and any permissions still needed."""

    def __init__(self, summary: FirstRunSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {METADATA.name}")
        self.setMinimumWidth(560)
        self._summary = summary

        layout = QVBoxLayout(self)

        heading = QLabel(f"{METADATA.name} {METADATA.version}")
        heading_font = heading.font()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        for text in (summary.platform_line, summary.capability_line):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body_layout.addWidget(label)

        for guidance in summary.permissions:
            body_layout.addWidget(self._permission_widget(guidance))

        if summary.notes:
            notes = QLabel("\n".join(f"• {note}" for note in summary.notes))
            notes.setWordWrap(True)
            notes.setAccessibleName("Platform notes")
            body_layout.addWidget(notes)

        locations = []
        if summary.profile_directory:
            locations.append(f"Profiles are stored in {summary.profile_directory}")
        if summary.log_directory:
            locations.append(f"Logs are written to {summary.log_directory}")
        if locations:
            label = QLabel("\n".join(locations))
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setAccessibleName("Storage locations")
            body_layout.addWidget(label)

        footer = QLabel(
            "Nothing runs automatically. Build a plan, choose a target window, "
            "and press Start when you are ready."
        )
        footer.setWordWrap(True)
        body_layout.addWidget(footer)
        body_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _permission_widget(guidance: PermissionGuidance) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 8)

        title = QLabel(f"{guidance.permission} - {guidance.state_word}")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        title.setWordWrap(True)
        title.setAccessibleName(f"Permission: {guidance.permission}")

        why = QLabel(guidance.why())
        why.setWordWrap(True)

        how = QLabel(guidance.instructions())
        how.setWordWrap(True)
        how.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        for widget in (title, why, how):
            layout.addWidget(widget)
        return container

    @property
    def summary(self) -> FirstRunSummary:
        return self._summary
