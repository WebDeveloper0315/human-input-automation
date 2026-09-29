"""Running applications on macOS, without walking windows.

pywinctl reaches windows through Accessibility, where every property is a round
trip. Measured on a MacBook Pro with ten windows open: listing them took
13.4 s, and a script paid that on every ``App:`` line. What an ``App:`` line
needs is much less - is the application running, and how many windows does it
have - and macOS answers that in milliseconds:

* ``NSWorkspace.runningApplications`` names every application with a user
  interface;
* Quartz's on-screen window list, ordered front to back, counts each
  application's normal windows and says which one is in front. It is read
  fresh on every call, unlike NSWorkspace's properties, which are refreshed
  through the main run loop.

Activation asks the application to come forward
(``NSRunningApplication.activateWithOptions``). Since macOS 14 an application
may decline that request from a program that is not itself in front, so when
it has not come forward within a second, LaunchServices is asked instead
(``open -a``), which is how the Dock does it. Either way, success is only
reported once the application is confirmed in front.

Every call is wrapped: a failure is an empty list or ``False``, never an
exception. PyObjC and ``open`` are injectable, so this is tested without a Mac.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Any

from ..core.target import PlatformReport, RunningApplication, TargetWindow
from ..ports.clock import CancelToken

logger = logging.getLogger(__name__)

#: How long to wait for the application to come forward on its own before
#: asking LaunchServices, and how long in all.
POLITE_ACTIVATION_S = 1.0
ACTIVATION_TIMEOUT_S = 10.0
POLL_S = 0.05

#: NSApplicationActivationPolicyRegular: applications with a Dock icon and menus.
_REGULAR = 0
#: NSApplicationActivateIgnoringOtherApps.
_IGNORING_OTHER_APPS = 1 << 1


def front_process_id(quartz: Any) -> int | None:
    """The owner of the frontmost normal window (layer 0), from Quartz's window list.

    Panels above that layer - the menu bar, Spotlight - are skipped: they are
    the system's, not an application's document.
    """
    try:
        windows = quartz.CGWindowListCopyWindowInfo(
            quartz.kCGWindowListOptionOnScreenOnly | quartz.kCGWindowListExcludeDesktopElements,
            quartz.kCGNullWindowID,
        )
        for info in windows or ():
            if int(info.get("kCGWindowLayer", -1)) == 0:
                return int(info["kCGWindowOwnerPID"])
    except Exception:
        logger.debug("front window query failed", exc_info=True)
    return None


class MacApplications:
    """Implements :class:`~..ports.applications.ApplicationPort` on macOS."""

    def __init__(
        self,
        host: PlatformReport,
        *,
        appkit: Any | None = None,
        quartz: Any | None = None,
        run: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if appkit is None or quartz is None:
            import AppKit
            import Quartz

            appkit = appkit or AppKit
            quartz = quartz or Quartz
        self._appkit = appkit
        self._quartz = quartz
        self._host = host
        self._run = run
        self._sleep = sleep

    def applications(self) -> Sequence[RunningApplication]:
        windows: dict[int, int] = {}
        names: dict[int, str] = {}
        try:
            listed = self._quartz.CGWindowListCopyWindowInfo(
                self._quartz.kCGWindowListOptionOnScreenOnly
                | self._quartz.kCGWindowListExcludeDesktopElements,
                self._quartz.kCGNullWindowID,
            )
            for info in listed or ():
                if int(info.get("kCGWindowLayer", -1)) != 0:
                    continue
                pid = int(info["kCGWindowOwnerPID"])
                windows[pid] = windows.get(pid, 0) + 1
                owner = info.get("kCGWindowOwnerName")
                if owner:
                    names.setdefault(pid, str(owner))
        except Exception:
            logger.debug("window list failed", exc_info=True)
        try:
            workspace = self._appkit.NSWorkspace.sharedWorkspace()
            for app in workspace.runningApplications():
                if int(app.activationPolicy()) != _REGULAR:
                    continue
                pid = int(app.processIdentifier())
                name = app.localizedName()
                if name:
                    names[pid] = str(name)
        except Exception:
            logger.debug("running applications failed", exc_info=True)
        return [
            RunningApplication(name, pid, windows.get(pid, 0), self._target(name, pid))
            for pid, name in names.items()
        ]

    def activate_application(
        self, application: RunningApplication, cancel: CancelToken | None = None
    ) -> bool:
        pid = application.process_id
        if front_process_id(self._quartz) == pid:
            return True
        try:
            running = self._appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
                pid
            )
        except Exception:
            running = None
        if running is None:
            return False  # it has quit
        try:
            running.activateWithOptions_(_IGNORING_OTHER_APPS)
        except Exception:
            logger.debug("activateWithOptions failed", exc_info=True)
        if self._came_forward(pid, POLITE_ACTIVATION_S, cancel):
            return True
        if cancel is not None and cancel.is_stop_requested():
            return False
        path = self._bundle_path(running)
        if path is None:
            return False
        try:
            self._run(["open", "-a", path], capture_output=True, timeout=5.0, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return self._came_forward(pid, ACTIVATION_TIMEOUT_S - POLITE_ACTIVATION_S, cancel)

    def _came_forward(self, pid: int, seconds: float, cancel: CancelToken | None) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            if front_process_id(self._quartz) == pid:
                return True
            if time.monotonic() >= deadline:
                return False
            if cancel is not None:
                if cancel.wait_for_stop(POLL_S):
                    return False
            else:
                self._sleep(POLL_S)

    def _bundle_path(self, running: Any) -> str | None:
        try:
            url = running.bundleURL()
            return str(url.path()) if url is not None else None
        except Exception:
            return None

    def _target(self, name: str, pid: int) -> TargetWindow:
        return TargetWindow(
            handle=f"application:{pid}",
            title=name,
            platform=self._host.platform,
            display_server=self._host.display_server,
            process_name=name,
            process_id=pid,
            app_id=name,
            capabilities=self._host.capabilities,
        )
