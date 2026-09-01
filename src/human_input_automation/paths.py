"""Where the application keeps its data, and how it finds bundled resources.

Two jobs, both of which packaging makes important:

* **User data** (profiles, logs) lives in the platform's per-user directory,
  never inside the installation directory. An installed application may sit in
  a read-only, administrator-owned location; user data must not.
* **Bundled resources** live next to the executable when frozen and inside the
  source tree otherwise. :func:`resource_path` hides that difference so no
  other module needs to know whether it is running from a bundle.

Every input is injectable, so tests never read or write the real directories.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .metadata import APP_SLUG

#: Import name of this package; also its directory name inside a bundle.
PACKAGE_DIRECTORY_NAME = "human_input_automation"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_directory() -> Path:
    """Where this package's bundled resources live.

    In a PyInstaller bundle the spec copies them to
    ``<_MEIPASS>/human_input_automation/…`` so they keep their package-relative
    layout; from a source checkout that is simply the package directory. Both
    cases therefore resolve the same relative paths.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(str(meipass)) / PACKAGE_DIRECTORY_NAME
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """Locate a bundled resource, frozen or not."""
    return bundle_directory().joinpath(*parts)


def user_data_directory(
    platform_id: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Per-user application data directory.

    Windows ``%APPDATA%``, macOS ``~/Library/Application Support``, otherwise
    ``$XDG_DATA_HOME`` or ``~/.local/share``.
    """
    platform = (platform_id if platform_id is not None else sys.platform).lower()
    environ = env if env is not None else os.environ
    base_home = home if home is not None else Path.home()

    if platform.startswith("win"):
        appdata = environ.get("APPDATA")
        base = Path(appdata) if appdata else base_home / "AppData" / "Roaming"
    elif platform == "darwin":
        base = base_home / "Library" / "Application Support"
    else:
        xdg = environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else base_home / ".local" / "share"
    return base / APP_SLUG


def user_log_directory(
    platform_id: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Per-user log directory.

    macOS has a dedicated ``~/Library/Logs``; Linux uses ``$XDG_STATE_HOME``
    (the freedesktop location for logs) and Windows keeps logs beside its data.
    """
    platform = (platform_id if platform_id is not None else sys.platform).lower()
    environ = env if env is not None else os.environ
    base_home = home if home is not None else Path.home()

    if platform == "darwin":
        return base_home / "Library" / "Logs" / APP_SLUG
    if platform.startswith("win"):
        return user_data_directory(platform_id, env, home) / "logs"
    state = environ.get("XDG_STATE_HOME")
    base = Path(state) if state else base_home / ".local" / "state"
    return base / APP_SLUG / "logs"


@dataclass(frozen=True)
class ApplicationPaths:
    """The directories one run of the application uses."""

    data: Path
    profiles: Path
    logs: Path

    @classmethod
    def for_host(
        cls,
        platform_id: str | None = None,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> ApplicationPaths:
        data = user_data_directory(platform_id, env, home)
        return cls(
            data=data,
            profiles=data / "profiles",
            logs=user_log_directory(platform_id, env, home),
        )

    @property
    def first_run_marker(self) -> Path:
        """Written after the first successful start-up."""
        return self.data / ".initialised"

    @property
    def is_first_run(self) -> bool:
        return not self.first_run_marker.exists()

    def ensure(self) -> tuple[Path, ...]:
        """Create any missing directories; returns the ones actually created.

        Failures propagate: a startup that cannot create its data directory
        must say so rather than silently losing profiles later.
        """
        created: list[Path] = []
        for directory in (self.data, self.profiles, self.logs):
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created.append(directory)
        return tuple(created)

    def mark_initialised(self) -> None:
        """Record that first-run initialisation completed."""
        # Non-fatal: if the marker cannot be written the onboarding simply
        # shows again next time, which is better than failing to start.
        with contextlib.suppress(OSError):
            self.first_run_marker.write_text("", encoding="utf-8")
