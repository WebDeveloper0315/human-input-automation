"""Profile management panel.

Presentation only: it knows nothing about JSON, file paths or the schema, and
talks to the rest of the application exclusively through signals that
:class:`~.main_window.MainWindow` connects to the profile service.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..application.profiles import ProfileSummary
from .models import TargetStatusView, profile_choices, profile_title


class ProfilePanel(QGroupBox):
    """Picker plus the profile actions, and the loaded profile's target state."""

    profile_selected = Signal(str)
    new_requested = Signal()
    save_requested = Signal()
    save_as_requested = Signal()
    duplicate_requested = Signal()
    delete_requested = Signal()
    import_requested = Signal()
    export_requested = Signal()
    resolve_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Profile")
        self._loading = False

        layout = QVBoxLayout(self)

        self.combo = QComboBox()
        self.combo.setAccessibleName("Stored profiles")
        self.combo.setToolTip("Load a saved automation profile")
        self.combo.currentIndexChanged.connect(self._on_selected)

        self.name_label = QLabel(profile_title(None, dirty=False))
        name_font = self.name_label.font()
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setAccessibleName("Current profile")

        picker = QHBoxLayout()
        picker.addWidget(QLabel("Profile:"))
        picker.addWidget(self.combo, 1)
        picker.addWidget(self.name_label)

        self.new_button = QPushButton("New")
        self.save_button = QPushButton("Save")
        self.save_as_button = QPushButton("Save As")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        self.import_button = QPushButton("Import")
        self.export_button = QPushButton("Export")

        self.new_button.clicked.connect(self.new_requested.emit)
        self.save_button.clicked.connect(self.save_requested.emit)
        self.save_as_button.clicked.connect(self.save_as_requested.emit)
        self.duplicate_button.clicked.connect(self.duplicate_requested.emit)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.import_button.clicked.connect(self.import_requested.emit)
        self.export_button.clicked.connect(self.export_requested.emit)

        buttons = QHBoxLayout()
        for button, name in (
            (self.new_button, "New profile"),
            (self.save_button, "Save profile"),
            (self.save_as_button, "Save profile as"),
            (self.duplicate_button, "Duplicate profile"),
            (self.delete_button, "Delete profile"),
            (self.import_button, "Import profile"),
            (self.export_button, "Export profile"),
        ):
            button.setAccessibleName(name)
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.setAccessibleName("Profile target status")

        self.resolve_button = QPushButton("Resolve target")
        self.resolve_button.setAccessibleName("Resolve profile target")
        self.resolve_button.setToolTip("Look for the profile's window again")
        self.resolve_button.clicked.connect(self.resolve_requested.emit)

        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.resolve_button)

        layout.addLayout(picker)
        layout.addLayout(buttons)
        layout.addLayout(status_row)

    # -- state -------------------------------------------------------------
    def set_profiles(self, summaries: Sequence[ProfileSummary], current_id: str | None) -> None:
        """Repopulate the picker without emitting a selection change."""
        self._loading = True
        try:
            self.combo.clear()
            self.combo.addItem("(unsaved profile)", "")
            for identifier, label in profile_choices(summaries):
                self.combo.addItem(label, identifier)
            index = self.combo.findData(current_id or "")
            self.combo.setCurrentIndex(max(0, index))
        finally:
            self._loading = False

    def set_current(self, name: str | None, *, dirty: bool) -> None:
        self.name_label.setText(profile_title(name, dirty=dirty))
        self.name_label.setAccessibleDescription(
            "unsaved changes" if dirty else "no unsaved changes"
        )

    def set_status(self, view: TargetStatusView) -> None:
        text = view.as_text()
        if view.detail:
            text = f"{text}\n{view.detail}"
        self.status_label.setText(text)
        self.status_label.setAccessibleDescription(text)

    def set_locked(self, locked: bool) -> None:
        """Profiles cannot be changed while a run is in flight."""
        for widget in (
            self.combo,
            self.new_button,
            self.save_button,
            self.save_as_button,
            self.duplicate_button,
            self.delete_button,
            self.import_button,
            self.export_button,
            self.resolve_button,
        ):
            widget.setEnabled(not locked)

    @property
    def selected_id(self) -> str:
        return str(self.combo.currentData() or "")

    # -- internals ---------------------------------------------------------
    def _on_selected(self) -> None:
        if self._loading:
            return
        identifier = self.selected_id
        if identifier:
            self.profile_selected.emit(identifier)
