"""Target-window selection panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..application.service import TargetListing
from ..core.target import TargetWindow
from .models import TargetRow, active_target_text

_COLUMNS = ("Title", "Application", "PID", "Platform")


class TargetPanel(QGroupBox):
    """Lists windows and keeps exactly one selected.

    The panel never falls back to "whatever has focus": if the user has not
    picked a window, there is no target and Start stays disabled.
    """

    target_changed = Signal(object)  # TargetWindow | None
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Target")
        self._targets: tuple[TargetWindow, ...] = ()
        self._selected: TargetWindow | None = None
        self._available = True

        layout = QVBoxLayout(self)

        self.refresh_button = QPushButton("Refresh windows")
        self.refresh_button.setAccessibleName("Refresh window list")
        self.refresh_button.setToolTip("Re-enumerate the windows available on this system")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setAccessibleName("Available target windows")
        self.table.setMinimumHeight(96)  # header plus two full rows
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        self.reason_label = QLabel()
        self.reason_label.setWordWrap(True)
        self.reason_label.setVisible(False)
        self.reason_label.setAccessibleName("Target list status")

        self.active_label = QLabel(active_target_text(None))
        self.active_label.setWordWrap(True)
        self.active_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.active_label.setAccessibleName("Active target")
        active_font = self.active_label.font()
        active_font.setBold(True)
        self.active_label.setFont(active_font)

        layout.addWidget(self.refresh_button)
        layout.addWidget(self.table)
        layout.addWidget(self.reason_label)
        layout.addWidget(self.active_label)

    # -- state -------------------------------------------------------------
    @property
    def selected_target(self) -> TargetWindow | None:
        return self._selected

    @property
    def targets(self) -> tuple[TargetWindow, ...]:
        return self._targets

    def set_listing(self, listing: TargetListing) -> None:
        """Replace the window list, keeping the selection when its handle survives."""
        previous = self._selected.handle if self._selected else None
        self._targets = tuple(listing.targets)

        self.table.blockSignals(True)
        self.table.setRowCount(len(self._targets))
        for row, target in enumerate(self._targets):
            view = TargetRow.from_target(target)
            for column, value in enumerate((view.title, view.process, view.pid, view.platform)):
                item = QTableWidgetItem(value)
                item.setToolTip(target.describe())
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

        self.reason_label.setText(listing.reason or "")
        self.reason_label.setVisible(bool(listing.reason))

        restored = None
        if previous is not None:
            restored = next((t for t in self._targets if t.handle == previous), None)
        if restored is not None:
            # Re-select by handle and re-store the refreshed object: the title
            # and other metadata may have changed while the handle did not.
            self.select_handle(restored.handle)
            self._set_selected(restored)
        else:
            self._set_selected(None)

    def clear_selection(self) -> None:
        """Drop the current selection.

        Used when a profile's target could not be resolved: leaving a stale
        selection behind would let Start run the plan against a window the
        profile never referred to.
        """
        self.table.clearSelection()
        self._set_selected(None)

    def select_handle(self, handle: str) -> None:
        """Select the row with ``handle``; handles identify windows, titles do not."""
        for row, target in enumerate(self._targets):
            if target.handle == handle:
                self.table.selectRow(row)
                return

    def set_target_available(self, available: bool) -> None:
        """Mark the selected target as gone without clearing the selection."""
        self._available = available
        self._update_active_label()

    def set_locked(self, locked: bool) -> None:
        """Lock target editing while a run is in flight."""
        self.table.setEnabled(not locked)
        self.refresh_button.setEnabled(not locked)

    # -- internals ---------------------------------------------------------
    def _on_selection_changed(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            self._set_selected(None)
            return
        row = next(iter(rows))
        self._set_selected(self._targets[row] if 0 <= row < len(self._targets) else None)

    def _set_selected(self, target: TargetWindow | None) -> None:
        """Store the selection, refreshing metadata without re-announcing it.

        ``target_changed`` fires only when the *handle* changes, so a refresh
        that merely picks up a new window title does not look like a new
        selection.
        """
        previous_handle = self._selected.handle if self._selected else None
        new_handle = target.handle if target else None
        self._selected = target
        if previous_handle != new_handle:
            self._available = True
        self._update_active_label()
        if previous_handle != new_handle:
            self.target_changed.emit(target)

    def _update_active_label(self) -> None:
        text = active_target_text(self._selected, available=self._available)
        self.active_label.setText(text)
        self.active_label.setAccessibleDescription(text)
