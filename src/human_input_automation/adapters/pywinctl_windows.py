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
import time
from collections.abc import Sequence
from typing import Any

from ..core.capabilities import CapabilityName
from ..core.errors import AdapterUnavailableError
from ..core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
)
from ..ports.clock import CancelToken

logger = logging.getLogger(__name__)

#: How long to wait for the window manager to actually move focus. macOS
#: activation is asynchronous - AppleScript returns before the window server
#: has moved keyboard focus - so success has to be confirmed, not assumed.
ACTIVATION_TIMEOUT_SECONDS = 4.0
ACTIVATION_POLL_SECONDS = 0.15

#: macOS activation goes through AppleScript and the window server moves focus
#: on its own schedule; four seconds was measured to be too short there. The
#: wait is cancellable, so a longer budget costs nothing when a run is stopped.
MACOS_ACTIVATION_TIMEOUT_SECONDS = 10.0


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

    def __init__(
        self,
        host: PlatformReport,
        module: Any | None = None,
        activation_timeout: float | None = None,
    ) -> None:
        self._pywinctl = module if module is not None else import_pywinctl()
        self._host = host
        self._activation_timeout = (
            activation_timeout if activation_timeout is not None
            else self._default_timeout(host)
        )
        #: Live window objects from the last enumeration, keyed by handle. On
        #: macOS every attribute of a pywinctl window is an Accessibility round
        #: trip, so enumerating the desktop to answer "is this window focused?"
        #: cost seconds per probe; measured, it made a one-action run take 26 s
        #: and an emergency stop take 10.8 s. The objects are only ever a
        #: starting point - identity is re-checked against the live window
        #: before any of them is used.
        self._known: dict[str, Any] = {}

    @staticmethod
    def _default_timeout(host: PlatformReport) -> float:
        if host.platform is PlatformName.MACOS:
            return MACOS_ACTIVATION_TIMEOUT_SECONDS
        return ACTIVATION_TIMEOUT_SECONDS

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
        known: dict[str, Any] = {}
        for window in windows:
            target = self._to_target(window)
            if target is not None and target.title:
                targets.append(target)
                known[target.handle] = window
        self._known = known
        return targets

    def find(self, handle: str) -> TargetWindow | None:
        for window in self.list_windows():
            if window.handle == handle:
                return window
        return None

    # -- control -----------------------------------------------------------
    def activate(self, target: TargetWindow, cancel: CancelToken | None = None) -> bool:
        """Focus ``target`` and confirm it really took focus.

        ``wait=False`` is deliberate: pywinctl's own retry loop blocks for
        around ten seconds on macOS and cannot be interrupted, so an emergency
        stop during it would go unheard. The waiting is done here instead,
        bounded and cancellable, and success is reported only once focus has
        actually been observed to move.
        """
        if not self._host.capabilities.can_activate:
            return False
        if cancel is not None and cancel.is_stop_requested():
            return False
        window = self._resolve(target)
        if window is None:
            return False
        if cancel is not None and cancel.is_stop_requested():
            return False
        try:
            window.activate(wait=False)
        except Exception as exc:
            logger.info("pywinctl activation failed: %s", exc)
            return False
        return self._await_focus(target, cancel)

    def _await_focus(self, target: TargetWindow, cancel: CancelToken | None) -> bool:
        """Poll until the window is confirmed focused, or the deadline passes.

        A platform that genuinely cannot answer returns ``None`` from
        :meth:`is_active`; there is nothing to confirm, so the request is taken
        at face value and the engine applies its own policy. A platform that
        *can* answer must actually say yes.
        """
        deadline = time.monotonic() + self._activation_timeout
        while True:
            if cancel is not None and cancel.is_stop_requested():
                return False
            active = self.is_active(target)
            if active is None:
                return True
            if active is True:
                return True
            if time.monotonic() >= deadline:
                logger.info("window %s never took focus", target.handle)
                return False
            if cancel is not None:
                if cancel.wait_for_stop(ACTIVATION_POLL_SECONDS):
                    return False
            else:
                time.sleep(ACTIVATION_POLL_SECONDS)

    def is_active(self, target: TargetWindow) -> bool | None:
        """Whether ``target`` holds focus, or ``None`` when unknowable.

        Gated on whether the platform *forbids* the check, not on whether it is
        certain: a permission that merely could not be preflighted is a reason
        to try, not a reason to stop looking. Reporting ``None`` here used to
        disable focus verification on macOS entirely, which let input reach a
        window the user had not selected.
        """
        if not self._host.matrix.is_permitted(CapabilityName.FOCUS_VERIFICATION):
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

        Handles are not equally stable across platforms. On Windows a handle is
        an ``HWND`` and does not change; on macOS pywinctl's handle is
        ``(application, title)``, so it changes the moment the window's title
        does - a saved document, a switched browser tab. When the exact handle
        has gone, fall back to the process behind it, but **only** when exactly
        one window matches: several candidates is ambiguous, and guessing is
        precisely the failure this application must never have.

        The window seen when the desktop was last enumerated is tried first.
        That is a cache of *where to look*, never of the answer: the handle and
        the owning process are re-read from the live window before it is
        accepted, so a window that has closed, been replaced or had its title
        change falls through to a full search.
        """
        remembered = self._known.get(target.handle)
        if remembered is not None:
            if (self._handle_of(remembered) == target.handle
                    and self._same_window(target, remembered)):
                return remembered
            del self._known[target.handle]

        try:
            windows = list(self._pywinctl.getAllWindows())
        except Exception as exc:
            logger.info("pywinctl window lookup failed: %s", exc)
            return None

        for window in windows:
            if self._handle_of(window) != target.handle:
                continue
            if not self._same_window(target, window):
                logger.info("window %s is no longer the selected target", target.handle)
                return None
            self._known[target.handle] = window
            return window
        return self._resolve_by_process(target, windows)

    def _resolve_by_process(self, target: TargetWindow, windows: list[Any]) -> Any:
        """The handle changed; identify the window by its process instead."""
        if target.process_id is None and not target.process_name:
            return None
        candidates = [window for window in windows if self._same_window(target, window)]
        if len(candidates) != 1:
            if candidates:
                logger.info(
                    "%d windows match the target's process; refusing to guess", len(candidates)
                )
            return None
        logger.info("target handle changed; matched by process instead")
        return candidates[0]

    def _same_window(self, target: TargetWindow, window: Any) -> bool:
        """Whether ``window`` belongs to the process the target was chosen from."""
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
