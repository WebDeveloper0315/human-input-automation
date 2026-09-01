"""Window discovery and control backed by pywinctl.

pywinctl gives one cross-platform surface over Win32, the macOS Accessibility
APIs and X11, which is why it is used as the Phase 1 reference implementation.
Where it cannot answer (notably Wayland), this adapter reports "unknown" rather
than guessing - the engine refuses to type into a window it cannot confirm.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..core.errors import AdapterUnavailableError
from ..core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
    WindowCapabilities,
)


def _import_pywinctl() -> Any:
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

    def __init__(self, host: PlatformReport) -> None:
        self._pywinctl = _import_pywinctl()
        self._host = host

    # -- discovery ---------------------------------------------------------
    def list_windows(self) -> Sequence[TargetWindow]:
        if not self._host.capabilities.can_enumerate:
            return ()
        windows: list[TargetWindow] = []
        for window in self._pywinctl.getAllWindows():
            target = self._to_target(window)
            if target is not None and target.title:
                windows.append(target)
        return windows

    def find(self, handle: str) -> TargetWindow | None:
        for window in self.list_windows():
            if window.handle == handle:
                return window
        return None

    # -- control -----------------------------------------------------------
    def activate(self, target: TargetWindow) -> bool:
        window = self._resolve(target)
        if window is None:
            return False
        try:
            return bool(window.activate(wait=True))
        except Exception:
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
        for window in self._pywinctl.getAllWindows():
            if self._handle_of(window) == target.handle:
                return window
        return None

    def _handle_of(self, window: Any) -> str:
        return str(getattr(window, "getHandle", lambda: id(window))())

    def _to_target(self, window: Any) -> TargetWindow | None:
        try:
            pid = int(window.getPID())
        except Exception:
            pid = 0
        try:
            app_name = str(window.getAppName())
        except Exception:
            app_name = ""
        try:
            title = str(window.title)
        except Exception:
            return None
        return TargetWindow(
            handle=self._handle_of(window),
            title=title,
            platform=self._host.platform,
            display_server=self._host.display_server,
            process_name=app_name or None,
            process_id=pid or None,
            app_id=app_name or None,
            capabilities=self._host.capabilities,
        )


def unsupported_reason(host: PlatformReport) -> str | None:
    """Explain why window targeting is unavailable, or ``None`` if it is fine."""
    if host.platform is PlatformName.LINUX and host.display_server is DisplayServer.WAYLAND:
        return (
            "Wayland does not allow applications to enumerate or focus other windows; "
            "focus the target window manually and use the focused-window target"
        )
    if host.capabilities is WindowCapabilities.unknown():  # pragma: no cover - defensive
        return "platform capabilities are unknown"
    if not host.capabilities.can_enumerate:
        return "this platform/adapter cannot enumerate windows"
    return None
