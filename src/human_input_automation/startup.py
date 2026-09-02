"""Start-up failure handling for a packaged application.

An installed build fails in ways a source checkout never does: a Qt plugin that
did not make it into the bundle, no display on the machine, a data directory the
user cannot write to. Each of those produces a specific, actionable message
instead of a traceback in a console nobody is looking at.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .metadata import APP_NAME


@dataclass(frozen=True)
class StartupProblem:
    """A start-up failure, phrased for the person who hit it."""

    headline: str
    detail: str
    exit_code: int = 2

    def render(self) -> str:
        return f"{APP_NAME}: {self.headline}\n\n{self.detail}"


MISSING_GUI = StartupProblem(
    headline="the graphical interface is not available",
    detail=(
        "PySide6 is not installed in this environment.\n"
        'From a source checkout, install the GUI extra: pip install ".[gui]"\n'
        "In a packaged build this indicates a broken installation - reinstall "
        "the application."
    ),
)

NO_DISPLAY = StartupProblem(
    headline="no graphical display was found",
    detail=(
        "There is no X11 or Wayland session for the window to appear on "
        "(DISPLAY and WAYLAND_DISPLAY are both unset).\n"
        "Run the application from a desktop session, or use the headless "
        "commands:\n"
        "  --check      short capability summary\n"
        "  --diagnose   full platform report (sends no input)"
    ),
)


def qt_plugin_problem(error: Exception) -> StartupProblem:
    """A Qt platform plugin failed to load - usually a packaging fault."""
    return StartupProblem(
        headline="the Qt platform plugin could not be loaded",
        detail=(
            f"Qt reported: {error}\n\n"
            "On a packaged build this means the bundle is incomplete or a "
            "system library is missing; reinstall the application.\n"
            "On Linux, the usual cause is a missing libxkbcommon, libEGL or "
            "libGL. Run with --diagnose for platform details, or set "
            "QT_QPA_PLATFORM=offscreen to confirm the rest of the application "
            "works."
        ),
    )


def data_directory_problem(path: object, error: Exception) -> StartupProblem:
    """The per-user data directory could not be created."""
    return StartupProblem(
        headline="the application data directory could not be created",
        detail=(
            f"{path}\n{error}\n\n"
            "Profiles and logs are stored there. Check the permissions on that "
            "directory, or set XDG_DATA_HOME (Linux) or APPDATA (Windows) to a "
            "writable location."
        ),
    )


def has_display(env: dict[str, str], platform: str | None = None) -> bool:
    """Whether some display server is reachable.

    ``DISPLAY`` and ``WAYLAND_DISPLAY`` are an X11 and Wayland convention, and
    asking about them anywhere else is meaningless: macOS draws through Quartz
    and Windows through the desktop window manager, neither of which advertises
    itself in the environment. Checking them unconditionally turned every macOS
    launch into "no graphical display was found".

    ``QT_QPA_PLATFORM`` overrides everything, because that is how offscreen and
    headless testing runs.
    """
    if env.get("QT_QPA_PLATFORM"):
        return True
    if (platform if platform is not None else sys.platform) not in ("linux", "linux2"):
        return True
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
