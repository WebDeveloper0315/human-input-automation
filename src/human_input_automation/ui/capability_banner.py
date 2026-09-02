"""Persistent capability and permission banner.

One line, always visible: what this computer will and will not let the
application do. It exists because most "it didn't type anything" questions are
answered by the operating system's own restrictions - a Wayland session that
will not move the pointer, a macOS permission that has not been granted - and
finding that out *after* a run fails is too late.

The full detail lives behind the button, in the platform and permissions
dialog. The banner itself stays one line so it never crowds out the panels that
do the actual work.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from .models import BannerModel, CapabilityLevel

#: Background tint per level, for light and dark themes. Colour is decoration
#: only - the marker word ("OK", "LIMITED", "DENIED") carries the meaning, so
#: the banner reads correctly without colour perception. The foreground is set
#: explicitly alongside it: a hard-coded background with the theme's default
#: text colour is unreadable in dark mode.
_LIGHT_TINTS: dict[CapabilityLevel, tuple[str, str]] = {
    CapabilityLevel.AVAILABLE: ("#e6f4ea", "#0b3d1e"),
    CapabilityLevel.RESTRICTED: ("#fff4e5", "#5a3200"),
    CapabilityLevel.DENIED: ("#fdecea", "#5c1512"),
    CapabilityLevel.UNKNOWN: ("#eef1f5", "#22303c"),
    CapabilityLevel.UNAVAILABLE: ("#fdecea", "#5c1512"),
}

_DARK_TINTS: dict[CapabilityLevel, tuple[str, str]] = {
    CapabilityLevel.AVAILABLE: ("#1d3326", "#b7e4c7"),
    CapabilityLevel.RESTRICTED: ("#3a2f1a", "#f5d9a8"),
    CapabilityLevel.DENIED: ("#3a1f1d", "#f5b7b1"),
    CapabilityLevel.UNKNOWN: ("#262b31", "#cdd6e0"),
    CapabilityLevel.UNAVAILABLE: ("#3a1f1d", "#f5b7b1"),
}


class CapabilityBanner(QFrame):
    """One-line summary of what the host allows, with the detail behind a button."""

    details_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("capabilityBanner")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName("Platform capability status")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        self.headline_label = QLabel()
        # Deliberately not word-wrapped: the banner must stay one line tall.
        # The whole text is in the tooltip and in the details dialog.
        self.headline_label.setWordWrap(False)
        self.headline_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.headline_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = self.headline_label.font()
        font.setBold(True)
        self.headline_label.setFont(font)

        self.count_label = QLabel()
        self.count_label.setAccessibleName("Number of platform notes")

        self.details_button = QPushButton("Platform && permissions...")
        self.details_button.setAccessibleName("Show platform and permission details")
        self.details_button.setToolTip(
            "What this computer allows, and which permissions are still needed"
        )
        self.details_button.clicked.connect(self.details_requested.emit)

        header = QHBoxLayout()
        header.addWidget(self.headline_label, 1)
        header.addWidget(self.count_label)
        header.addWidget(self.details_button)
        layout.addLayout(header)

        self._model: BannerModel | None = None

    @property
    def model(self) -> BannerModel | None:
        return self._model

    @property
    def details_text(self) -> str:
        """The full detail, which the dialog and the tooltip both show."""
        model = self._model
        return "\n".join(model.details) if model else ""

    def show_model(self, model: BannerModel) -> None:
        """Render a banner model. The status word is always spelled out."""
        self._model = model
        self.headline_label.setText(model.as_text())

        notes = len(model.details)
        self.count_label.setText(f"{notes} note(s)" if notes else "")
        self.count_label.setVisible(bool(notes))

        tooltip = model.as_text()
        if model.details:
            tooltip += "\n\n" + "\n".join(f"• {detail}" for detail in model.details)
        self.setToolTip(tooltip)
        self.headline_label.setToolTip(tooltip)
        self.setAccessibleDescription(tooltip)

        background, foreground = self._tint(model.level)
        self.setStyleSheet(
            f"#capabilityBanner {{ background-color: {background}; "
            "border: 1px solid rgba(128, 128, 128, 0.35); border-radius: 4px; }"
            f"#capabilityBanner QLabel {{ color: {foreground}; background: transparent; }}"
        )

    def _tint(self, level: CapabilityLevel) -> tuple[str, str]:
        """Pick colours that suit the active theme, light or dark."""
        window = self.palette().color(QPalette.ColorRole.Window)
        tints = _DARK_TINTS if window.lightness() < 128 else _LIGHT_TINTS
        return tints[level]
