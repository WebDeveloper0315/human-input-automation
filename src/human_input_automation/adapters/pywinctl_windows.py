"""Window discovery and control backed by pywinctl.

pywinctl wraps Win32, the macOS Accessibility APIs and X11 behind one surface,
which makes it the reference window backend on Windows and macOS.

It is **not** trusted blindly. On Ubuntu 26.04 GNOME/Wayland
``pywinctl.getAllWindows()`` raises ``KeyError: 'id'`` (reproduced on this
machine) and ``getActiveWindow()`` returns a phantom 1x1 window, so every call
here is wrapped: failures become empty results or ``False``/``None``, never an
exception escaping into the engine or the UI. Linux prefers
:mod:`.x11_windows` instead; see :func:`.registry.build_window_adapter`.

The pywinctl module is injectable so the logic below is unit tested without it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..core.errors import AdapterUnavailableError
from ..core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
)

logger = logging.getLogger(__name__)


def import_pywinctl() -> Any:
    """Import pywinctl, turning any failure into an actionable adapter error."""
    try:
        import pywinctl
    except Exception as exc:
        raise AdapterUnavailableError(
            f"pywinctl is not usable on this host: {exc}",
            remedy='install the desktop extra: pip install ".[desktop]"',
        ) from exc
    return pywinctl


class PyWinCtlWindows:
    """Implements the window discovery and control ports."""

    def __init__(self, host: PlatformReport, module: Any | None = None) -> None:
        self._pywinctl = module if module is not None else import_pywinctl()
        self._host = host

    # -- discovery ---------------------------------------------------------
    def list_windows(self) -> Sequence[TargetWindow]:
        """Enumerate windows. Never raises; a backend failure yields ``()``."""
        if not self._host.capabilities.can_enumerate:
            return ()
        try:
            windows = self._pywinctl.getAllWindows()
        except Exception as exc:
            logger.info("pywinctl window enumeration failed: %s", exc)
            return ()
        targets: list[TargetWindow] = []
        for window in windows:
            target = self._to_target(window)
            if target is not None and target.title:
                targets.append(target)
        return targets

    def find(self, handle: str) -> TargetWindow | None:
        for window in self.list_windows():
            if window.handle == handle:
                return window
        return None

    # -- control -----------------------------------------------------------
    def activate(self, target: TargetWindow) -> bool:
        """Focus ``target``; ``False`` when it cannot be done or verified."""
        if not self._host.capabilities.can_activate:
            return False
        window = self._resolve(target)
        if window is None:
            return False
        try:
            return bool(window.activate(wait=True))
        except Exception as exc:
            logger.info("pywinctl activation failed: %s", exc)
            return False

    def is_active(self, target: TargetWindow) -> bool | None:
        if not self._host.capabilities.can_verify_focus:
            return None
        window = self._resolve(target)
        if window is None:
            return None
        try:
            return bool(window.isActive)
        except Exception:
            return None

    # -- internals ---------------------------------------------------------
    def _resolve(self, target: TargetWindow) -> Any:
        """Find the live window for ``target``, checking it is the same one.

        A window id can be reused after the original window closes, so the
        process behind it is compared as well. A mismatch resolves to ``None``,
        which the engine turns into a failed run rather than typing into a
        different application.
        """
        try:
            windows = self._pywinctl.getAllWindows()
        except Exception as exc:
            logger.info("pywinctl window lookup failed: %s", exc)
            return None
        for window in windows:
            if self._handle_of(window) != target.handle:
                continue
            if not self._same_window(target, window):
                logger.info("window %s is no longer the selected target", target.handle)
                return None
            return window
        return None

    def _same_window(self, target: TargetWindow, window: Any) -> bool:
        pid = self._pid_of(window)
        if target.process_id is not None and pid is not None:
            return target.process_id == pid
        app = self._app_of(window)
        if target.process_name and app:
            return target.process_name == app
        return True

    def _handle_of(self, window: Any) -> str:
        try:
            return str(window.getHandle())
        except Exception:
            return str(id(window))

    def _pid_of(self, window: Any) -> int | None:
        try:
            return int(window.getPID())
        except Exception:
            return None

    def _app_of(self, window: Any) -> str | None:
        try:
            name = str(window.getAppName())
        except Exception:
            return None
        return name or None

    def _to_target(self, window: Any) -> TargetWindow | None:
        try:
            title = str(window.title)
        except Exception:
            return None
        app_name = self._app_of(window)
        return TargetWindow(
            handle=self._handle_of(window),
            title=title,
            platform=self._host.platform,
            display_server=self._host.display_server,
            process_name=app_name,
            process_id=self._pid_of(window),
            app_id=app_name,
            capabilities=self._host.capabilities,
        )


def unsupported_reason(host: PlatformReport) -> str | None:
    """Explain why window targeting is unavailable, or ``None`` if it is fine."""
    if host.platform is PlatformName.LINUX and host.display_server is DisplayServer.WAYLAND:
        return (
            "Wayland does not allow applications to enumerate or focus other windows; "
            "focus the target window manually and use the focused-window target"
        )
    if not host.capabilities.can_enumerate:
        return "this platform/adapter cannot enumerate windows"
    return None
