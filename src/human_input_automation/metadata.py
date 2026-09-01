"""Application metadata: one source of truth for names, version and identifiers.

Packaging needs this in half a dozen places - the PyInstaller spec, the macOS
``Info.plist``, the Windows installer, the Linux ``.desktop`` entry - and a
mismatch between them is the classic packaging bug. They all read from here, and
``tests/test_metadata.py`` asserts this file agrees with ``pyproject.toml``.

Nothing here imports Qt or a platform library, so the frozen application and the
headless CLI can both use it.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import __version__

#: Human-readable product name, shown in window titles and installers.
APP_NAME = "Human Input Automation"

#: Filesystem-safe name used for executables, directories and package files.
APP_SLUG = "human-input-automation"

#: Reverse-DNS identifier for the macOS bundle and the Linux desktop entry.
APP_ID = "io.github.humaninputautomation.app"

APP_DESCRIPTION = "Cross-platform keyboard and mouse automation desktop application"
APP_PUBLISHER = "Human Input Automation contributors"
APP_URL = "https://github.com/human-input-automation/human-input-automation"
APP_LICENSE = "MIT"

#: Executable name inside a packaged build (``.exe`` is appended on Windows).
EXECUTABLE_NAME = "HumanInputAutomation"

#: Freedesktop categories for the Linux desktop entry.
DESKTOP_CATEGORIES = ("Utility", "Accessibility")


@dataclass(frozen=True)
class ApplicationMetadata:
    """Everything a packaging step needs to describe the application."""

    name: str = APP_NAME
    slug: str = APP_SLUG
    identifier: str = APP_ID
    version: str = __version__
    description: str = APP_DESCRIPTION
    publisher: str = APP_PUBLISHER
    url: str = APP_URL
    license: str = APP_LICENSE
    executable: str = EXECUTABLE_NAME

    def artifact_name(self, platform: str, architecture: str, suffix: str) -> str:
        """Release artifact filename, e.g. ``…-0.6.0-linux-x86_64.AppImage``."""
        return f"{self.executable}-{self.version}-{platform}-{architecture}{suffix}"

    def user_agent(self) -> str:
        return f"{self.slug}/{self.version}"


METADATA = ApplicationMetadata()
