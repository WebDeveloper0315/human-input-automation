"""Bundled UI resources.

Resources are looked up through :func:`~..paths.resource_path`, so the same code
finds the icon in a source checkout and inside a PyInstaller bundle. A missing
icon is never fatal - the application simply runs without one.
"""

from __future__ import annotations

import logging
from typing import Any

from ..paths import resource_path

logger = logging.getLogger(__name__)

ICON_RELATIVE_PATH = ("resources", "icons", "app.png")


def icon_path() -> Any:
    """Filesystem path of the application icon, whether frozen or not."""
    return resource_path(*ICON_RELATIVE_PATH)


def application_icon() -> Any:
    """The window icon, or ``None`` when it is unavailable."""
    from PySide6.QtGui import QIcon

    path = icon_path()
    if not path.is_file():
        logger.info("application icon not found at %s", path)
        return None
    icon = QIcon(str(path))
    return None if icon.isNull() else icon
