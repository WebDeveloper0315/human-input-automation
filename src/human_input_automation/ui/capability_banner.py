"""Persistent capability and permission banner."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from .models import BannerModel, CapabilityLevel

#: Background tints are decoration only - the marker text carries the meaning,
#: so the banner is readable without colour perception.
_TINTS: dict[CapabilityLevel, str] = {
    CapabilityLevel.AVAILABLE: "#e6f4ea",
    CapabilityLevel.RESTRICTED: "#fff4e5",
    CapabilityLevel.DENIED: "#fdecea",
    CapabilityLevel.UNKNOWN: "#eef1f5",
    CapabilityLevel.UNAVAILABLE: "#fdecea",
}


class CapabilityBanner(QFrame):
    """Shows what the host supports, and why something is unavailable."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("capabilityBanner")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName("Platform capability status")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        self.headline_label = QLabel()
        self.headline_label.setWordWrap(True)
        self.headline_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = self.headline_label.font()
        font.setBold(True)
        self.headline_label.setFont(font)

        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self.headline_label)
        layout.addWidget(self.details_label)
        self._model: BannerModel | None = None

    @property
    def model(self) -> BannerModel | None:
        return self._model

    def show_model(self, model: BannerModel) -> None:
        """Render a banner model. The status word is always spelled out."""
        self._model = model
        self.headline_label.setText(model.as_text())
        details = "\n".join(f"• {detail}" for detail in model.details)
        self.details_label.setText(details)
        self.details_label.setVisible(bool(details))
        self.setStyleSheet(
            f"#capabilityBanner {{ background-color: {_TINTS[model.level]}; "
            "border: 1px solid rgba(0, 0, 0, 0.15); border-radius: 4px; }"
        )
        self.setAccessibleDescription(model.as_text())
        self.setToolTip(details or model.headline)
