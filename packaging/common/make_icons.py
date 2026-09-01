"""Generate the application icons.

The project ships no artwork, so this draws a simple, neutral placeholder mark
and writes the three formats packaging needs. Qt can write PNG, ICO and ICNS
directly, so this needs no image library and - importantly - **no network
access**: the icons are reproducible from this script alone.

    python packaging/common/make_icons.py

Replace this with real artwork by dropping the files into
``src/human_input_automation/resources/icons/`` and leaving this script unused;
nothing depends on it at runtime.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
ICON_DIRECTORY = ROOT / "src" / "human_input_automation" / "resources" / "icons"
SIZES = (16, 32, 48, 64, 128, 256, 512)

BACKGROUND = "#1f2933"
KEY_FILL = "#e4e7eb"
ACCENT = "#3b82f6"


def draw(size: int) -> Any:
    """A keycap with a pointer dot: keyboard and mouse automation."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    unit = size / 32.0
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(BACKGROUND)))
    painter.drawRoundedRect(QRectF(0, 0, size, size), 6 * unit, 6 * unit)

    # Keycap
    painter.setBrush(QBrush(QColor(KEY_FILL)))
    painter.drawRoundedRect(QRectF(6 * unit, 6 * unit, 14 * unit, 14 * unit), 2 * unit, 2 * unit)
    painter.setPen(QPen(QColor(BACKGROUND), max(1.0, unit * 0.8)))
    painter.drawLine(
        int(9 * unit), int(13 * unit), int(17 * unit), int(13 * unit)
    )

    # Pointer dot with a motion trail
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(ACCENT)))
    painter.drawEllipse(QRectF(18 * unit, 18 * unit, 8 * unit, 8 * unit))
    painter.setBrush(QBrush(QColor(ACCENT).lighter(140)))
    painter.drawEllipse(QRectF(15 * unit, 22 * unit, 3 * unit, 3 * unit))
    painter.end()
    return image


def main() -> int:
    from PySide6.QtGui import QImage, QImageWriter
    from PySide6.QtWidgets import QApplication

    QApplication(sys.argv[:1])
    ICON_DIRECTORY.mkdir(parents=True, exist_ok=True)
    images: list[QImage] = [draw(size) for size in SIZES]
    written: list[Path] = []

    for size, image in zip(SIZES, images, strict=True):
        path = ICON_DIRECTORY / f"app-{size}.png"
        if not image.save(str(path), "PNG"):
            print(f"failed to write {path}", file=sys.stderr)
            return 1
        written.append(path)

    main_png = ICON_DIRECTORY / "app.png"
    images[SIZES.index(256)].save(str(main_png), "PNG")
    written.append(main_png)

    for name, image_format in (("app.ico", "ICO"), ("app.icns", "ICNS")):
        path = ICON_DIRECTORY / name
        writer = QImageWriter(str(path), image_format.encode())
        # Qt writes ICO uncompressed, so a 256px source would be a ~256 KB
        # file for no visible gain; 128px is the practical Windows size.
        source = images[SIZES.index(128)] if image_format == "ICO" else images[SIZES.index(512)]
        if not writer.write(source):
            print(f"failed to write {path}: {writer.errorString()}", file=sys.stderr)
            return 1
        written.append(path)

    for path in written:
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
