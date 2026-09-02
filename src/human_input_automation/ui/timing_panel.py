"""Timing profile panel with a live preview."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import ValidationError
from ..core.timing import TimingProfile
from .models import (
    TIMING_FIELDS,
    build_timing_profile,
    format_preview,
    preview_delays,
    timing_to_values,
)

PREVIEW_COUNT = 5


class TimingPanel(QGroupBox):
    """Edits a :class:`TimingProfile` and previews the delays it produces.

    The preview calls :class:`~...core.timing.TimingService` - the same code the
    engine uses - so what is shown is what will run.
    """

    profile_changed = Signal()

    def __init__(self) -> None:
        super().__init__("Timing")
        self._spins: dict[str, QDoubleSpinBox] = {}
        self._error = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Two columns: ten stacked rows made the panel taller than the window
        # could spare, and the splitter then collapsed it to nothing.
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(4)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        defaults = timing_to_values(TimingProfile())
        for index, spec in enumerate(TIMING_FIELDS):
            spin = QDoubleSpinBox()
            spin.setRange(spec.minimum, spec.maximum)
            spin.setDecimals(0)
            spin.setSingleStep(5)
            spin.setSuffix(spec.suffix)
            spin.setValue(float(defaults[spec.name]))
            spin.setAccessibleName(spec.label)
            spin.setMinimumWidth(96)
            spin.valueChanged.connect(self._on_changed)
            self._spins[spec.name] = spin

            row, column = divmod(index, 2)
            label = QLabel(spec.label)
            label.setBuddy(spin)
            form.addWidget(label, row, column * 2)
            form.addWidget(spin, row, column * 2 + 1)

        self.seed_check = QCheckBox("Use fixed seed (reproducible timing)")
        self.seed_check.setAccessibleName("Use fixed timing seed")
        self.seed_check.toggled.connect(self._on_seed_toggled)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2_147_483_647)
        self.seed_spin.setValue(1234)
        self.seed_spin.setEnabled(False)
        self.seed_spin.setAccessibleName("Timing seed")
        self.seed_spin.valueChanged.connect(self._on_changed)

        seed_row = QHBoxLayout()
        seed_row.setContentsMargins(0, 0, 0, 0)
        seed_row.addWidget(self.seed_check)
        seed_row.addWidget(self.seed_spin)
        seed_row.addStretch(1)
        seed_widget = QWidget()
        seed_widget.setLayout(seed_row)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.error_label.setAccessibleName("Timing validation error")

        self.preview_label = QLabel("Preview: -")
        self.preview_label.setWordWrap(True)
        self.preview_label.setAccessibleName("Timing preview")

        self.preview_button = QPushButton("Refresh preview")
        self.preview_button.setAccessibleName("Refresh timing preview")
        self.preview_button.clicked.connect(self.refresh_preview)

        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview_label, 1)
        preview_row.addWidget(self.preview_button)

        layout.addLayout(form)
        layout.addWidget(seed_widget)
        layout.addWidget(self.error_label)
        layout.addLayout(preview_row)
        layout.addStretch(1)

        # Enough room for the grid plus the seed row and the preview, so a
        # splitter cannot squeeze the fields out of existence.
        self.setMinimumHeight(self.sizeHint().height())
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self.refresh_preview()

    # -- state -------------------------------------------------------------
    @property
    def seed(self) -> int | None:
        return int(self.seed_spin.value()) if self.seed_check.isChecked() else None

    @property
    def error_text(self) -> str:
        return self._error

    def values(self) -> dict[str, float]:
        return {name: float(spin.value()) for name, spin in self._spins.items()}

    def set_values(self, values: Mapping[str, float]) -> None:
        for name, value in values.items():
            spin = self._spins.get(name)
            if spin is not None:
                spin.setValue(float(value))

    def profile(self) -> TimingProfile | None:
        """The current profile, or ``None`` when the inputs are invalid."""
        try:
            profile = build_timing_profile(self.values())
        except ValidationError as error:
            self._set_error("\n".join(issue.message for issue in error.issues))
            return None
        self._set_error("")
        return profile

    def set_locked(self, locked: bool) -> None:
        for spin in self._spins.values():
            spin.setEnabled(not locked)
        self.seed_check.setEnabled(not locked)
        self.seed_spin.setEnabled(not locked and self.seed_check.isChecked())
        self.preview_button.setEnabled(not locked)

    def refresh_preview(self) -> None:
        """Sample the next delays through the real timing service."""
        profile = self.profile()
        if profile is None:
            self.preview_label.setText("Preview unavailable - fix the timing values above.")
            return
        delays = preview_delays(profile, seed=self.seed, count=PREVIEW_COUNT)
        self.preview_label.setText(f"Next delays: {format_preview(delays)}")

    # -- internals ---------------------------------------------------------
    def _on_seed_toggled(self, checked: bool) -> None:
        self.seed_spin.setEnabled(checked)
        self._on_changed()

    def _on_changed(self) -> None:
        self.refresh_preview()
        self.profile_changed.emit()

    def _set_error(self, message: str) -> None:
        self._error = message
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
