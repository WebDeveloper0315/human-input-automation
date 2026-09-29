"""AutoScript panel: open a script, check it, preview it, run it.

Presentation only. What it shows comes from :func:`~.models.script_view`; what
its buttons do is decided by :class:`~.main_window.MainWindow`, through the
application service.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from .models import ScriptView


class ScriptPanel(QGroupBox):
    """The open script, what is wrong with it, and the buttons that act on it."""

    open_requested = Signal()
    reload_requested = Signal()
    dry_run_requested = Signal()
    run_requested = Signal()

    def __init__(self) -> None:
        super().__init__("AutoScript")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        self.title_label = QLabel()
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAccessibleName("Open script")
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setAccessibleName("Script summary")

        self.problems_view = QListWidget()
        self.problems_view.setAccessibleName("Script problems")
        self.problems_view.setMaximumHeight(90)
        self.problems_view.setVisible(False)

        self.open_button = QPushButton("Open script...")
        self.open_button.setAccessibleName("Open an AutoScript file")
        self.open_button.setToolTip("Choose an AutoScript .md file; it is checked, not run")
        self.reload_button = QPushButton("Reload")
        self.reload_button.setAccessibleName("Read the script file again")
        self.reload_button.setToolTip("Read the file again after editing it")
        self.dry_run_button = QPushButton("Dry run script")
        self.dry_run_button.setAccessibleName("Preview the script without sending input")
        self.run_button = QPushButton("Run script")
        self.run_button.setAccessibleName("Run the script")
        self.run_button.setToolTip(
            "Asks first, then counts down (the countdown below) and performs the script"
        )

        self.open_button.clicked.connect(self.open_requested.emit)
        self.reload_button.clicked.connect(self.reload_requested.emit)
        self.dry_run_button.clicked.connect(self.dry_run_requested.emit)
        self.run_button.clicked.connect(self.run_requested.emit)

        buttons = QHBoxLayout()
        for button in (self.open_button, self.reload_button, self.dry_run_button, self.run_button):
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout.addWidget(self.title_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.problems_view)
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
        self._apply_enabled()

    def set_locked(self, locked: bool) -> None:
        """While any run is in flight, nothing here may start another."""
        self._locked = locked
        self._apply_enabled()

    def _apply_enabled(self) -> None:
        idle = not self._locked
        self.open_button.setEnabled(idle)
        self.reload_button.setEnabled(idle and self._view.has_script)
        self.dry_run_button.setEnabled(idle and self._view.can_dry_run)
        self.run_button.setEnabled(idle and self._view.can_run)

    @property
    def problems(self) -> list[str]:
        return [self.problems_view.item(row).text() for row in range(self.problems_view.count())]
