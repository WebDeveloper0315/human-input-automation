"""The Script tab: an AutoScript file in place of the action list.

Presentation only. What it shows comes from :func:`~.models.script_view`; the
Run row's Start and Dry run act on it whenever this tab is the one showing,
decided by :class:`~.main_window.MainWindow` through the application service.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .models import ScriptView


class ScriptPanel(QWidget):
    """The open script: its steps, what is wrong with it, and where it came from."""

    open_requested = Signal()
    reload_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.title_label = QLabel()
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        self.title_label.setAccessibleName("Open script")
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setAccessibleName("Script summary")

        self.problems_view = QListWidget()
        self.problems_view.setAccessibleName("Script problems")
        self.problems_view.setMaximumHeight(80)
        self.problems_view.setVisible(False)

        self.steps_view = QListWidget()
        self.steps_view.setAccessibleName("Script steps")
        self.steps_view.setToolTip("The script's steps as written. Start runs them in order.")

        self.open_button = QPushButton("Open script...")
        self.open_button.setAccessibleName("Open an AutoScript file")
        self.open_button.setToolTip("Choose an AutoScript .md file; it is checked, not run")
        self.reload_button = QPushButton("Reload")
        self.reload_button.setAccessibleName("Read the script file again")
        self.reload_button.setToolTip("Read the file again after editing it")
        self.open_button.clicked.connect(self.open_requested.emit)
        self.reload_button.clicked.connect(self.reload_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.reload_button)
        buttons.addStretch(1)

        layout.addWidget(self.title_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.problems_view)
        layout.addWidget(self.steps_view, 1)
        layout.addLayout(buttons)

        self._view = ScriptView()
        self._locked = False
        self.show_view(self._view)

    def show_view(self, view: ScriptView) -> None:
        self._view = view
        self.title_label.setText(view.title)
        self.summary_label.setText(view.summary)
        self.problems_view.clear()
        self.problems_view.addItems(list(view.problems))
        self.problems_view.setVisible(bool(view.problems))
        self.steps_view.clear()
        self.steps_view.addItems(list(view.steps))
        self._apply_enabled()

    @property
    def view(self) -> ScriptView:
        return self._view

    def set_locked(self, locked: bool) -> None:
        """While any run is in flight, the script cannot be swapped under it."""
        self._locked = locked
        self._apply_enabled()

    def _apply_enabled(self) -> None:
        idle = not self._locked
        self.open_button.setEnabled(idle)
        self.reload_button.setEnabled(idle and self._view.has_script)

    @property
    def problems(self) -> list[str]:
        return [self.problems_view.item(row).text() for row in range(self.problems_view.count())]

    @property
    def steps(self) -> list[str]:
        return [self.steps_view.item(row).text() for row in range(self.steps_view.count())]
