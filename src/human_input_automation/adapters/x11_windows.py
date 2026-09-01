"""Window discovery and control for X11, via EWMH and python-xlib.

Why this exists: on Ubuntu 26.04 GNOME the pywinctl Linux path raises
``KeyError: 'id'`` from ``getAllWindows()`` (reproduced on this machine), so it
cannot be the only Linux window backend. EWMH - the freedesktop standard every
X11 window manager implements - is queried directly instead, which also gives
stable window ids, process ids and WM classes without a helper library.

Behaviour by session type:

* **X11 session** - full enumeration; activation via the standard
  ``_NET_ACTIVE_WINDOW`` client message.
* **Wayland session with XWayland** - ``_NET_CLIENT_LIST`` lists the XWayland
  (X11) clients only; native Wayland windows are invisible. Verified on this
  machine. Activation is refused, because the capability matrix reports it as
  unavailable there and no verified mechanism exists.

The display connection is injectable, so all of the logic below is unit tested
without an X server.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from ..core.errors import AdapterUnavailableError
from ..core.target import PlatformReport, TargetWindow

_ANY_PROPERTY_TYPE = 0
_NET_CLIENT_LIST = "_NET_CLIENT_LIST"
_NET_ACTIVE_WINDOW = "_NET_ACTIVE_WINDOW"
_NET_WM_NAME = "_NET_WM_NAME"
_NET_WM_PID = "_NET_WM_PID"
_UTF8_STRING = "UTF8_STRING"


def open_display(display_name: str | None = None) -> Any:
    """Open an X display, or raise an actionable adapter error."""
    try:
        from Xlib import display as xdisplay

        return xdisplay.Display(display_name)
    except Exception as exc:
        raise AdapterUnavailableError(
            f"could not open an X11 display: {exc}",
            remedy='install the desktop extra (pip install ".[desktop]") and run '
            "inside an X11 session, or under XWayland with DISPLAY set",
        ) from exc


def format_handle(window_id: int) -> str:
    """Stable, printable form of an X11 window id."""
    return f"0x{int(window_id):08x}"


class X11Windows:
    """Implements the window discovery and control ports for X11."""

    def __init__(
        self,
        host: PlatformReport,
        display: Any | None = None,
        xlib: Any | None = None,
    ) -> None:
        self._host = host
        self._display = display if display is not None else open_display()
        self._xlib = xlib

    def _load_xlib(self) -> Any | None:
        """The ``Xlib`` constants and protocol module, injectable for tests."""
        if self._xlib is None:
            try:
                from Xlib import X, protocol

                self._xlib = SimpleNamespace(X=X, protocol=protocol)
            except Exception:
                return None
        return self._xlib

    # -- discovery ---------------------------------------------------------
    def list_windows(self) -> Sequence[TargetWindow]:
        """Every managed top-level window the X server will admit to.

        Never raises: a broken or restricted X connection yields an empty list,
        and the caller reports the capability reason instead of a traceback.
        """
        if not self._host.capabilities.can_enumerate:
            return ()
        targets: list[TargetWindow] = []
        for window_id in self._client_ids():
            target = self._to_target(window_id)
            if target is not None and target.title:
                targets.append(target)
        return tuple(targets)

    def find(self, handle: str) -> TargetWindow | None:
        """Re-resolve by handle. Titles change; window ids do not."""
        for window_id in self._client_ids():
            if format_handle(window_id) == handle:
                return self._to_target(window_id)
        return None

    # -- control -----------------------------------------------------------
    def activate(self, target: TargetWindow) -> bool:
        """Ask the window manager to focus ``target``.

        Returns ``False`` rather than raising - including when the window has
        gone, when the process behind the handle changed, or when the session
        does not permit activation. The engine turns that into a failed run, so
        input is never sent to whatever happened to be focused instead.
        """
        if not self._host.capabilities.can_activate:
            return False
        current = self.find(target.handle)
        if current is None or not self._same_window(target, current):
            return False
        window_id = self._parse_handle(target.handle)
        if window_id is None:
            return False
        xlib = self._load_xlib()
        if xlib is None:
            return False
        try:
            window = self._display.create_resource_object("window", window_id)
            atom = self._display.intern_atom(_NET_ACTIVE_WINDOW)
            event = xlib.protocol.event.ClientMessage(
                window=window,
                client_type=atom,
                data=(32, [2, xlib.X.CurrentTime, 0, 0, 0]),  # source 2 == pager
            )
            mask = xlib.X.SubstructureRedirectMask | xlib.X.SubstructureNotifyMask
            self._display.screen().root.send_event(event, event_mask=mask)
            window.configure(stack_mode=xlib.X.Above)
            self._display.sync()
        except Exception:
            return False
        return self.is_active(target) is not False

    def is_active(self, target: TargetWindow) -> bool | None:
        """Whether ``target`` holds focus, or ``None`` when unknowable."""
        if not self._host.capabilities.can_verify_focus:
            return None
        active = self.active_handle()
        if active is None:
            return None
        return active == target.handle

    def active_handle(self) -> str | None:
        """Handle of the focused window, or ``None`` if it cannot be read."""
        try:
            root = self._display.screen().root
            prop = root.get_full_property(
                self._display.intern_atom(_NET_ACTIVE_WINDOW), _ANY_PROPERTY_TYPE
            )
        except Exception:
            return None
        if prop is None or not getattr(prop, "value", None):
            return None
        return format_handle(prop.value[0])

    def close(self) -> None:
        """Release the X connection. Safe to call more than once."""
        with contextlib.suppress(Exception):  # depends on the X connection
            self._display.close()

    # -- internals ---------------------------------------------------------
    def _client_ids(self) -> list[int]:
        try:
            root = self._display.screen().root
            prop = root.get_full_property(
                self._display.intern_atom(_NET_CLIENT_LIST), _ANY_PROPERTY_TYPE
            )
        except Exception:
            return []
        if prop is None or not getattr(prop, "value", None):
            return []
        return [int(value) for value in prop.value]

    def _to_target(self, window_id: int) -> TargetWindow | None:
        try:
            window = self._display.create_resource_object("window", window_id)
        except Exception:
            return None
        title = self._title(window)
        if title is None:
            return None
        return TargetWindow(
            handle=format_handle(window_id),
            title=title,
            platform=self._host.platform,
            display_server=self._host.display_server,
            process_name=self._wm_class(window),
            process_id=self._pid(window),
            app_id=self._wm_class(window),
            capabilities=self._host.capabilities,
        )

    def _title(self, window: Any) -> str | None:
        try:
            prop = window.get_full_property(
                self._display.intern_atom(_NET_WM_NAME),
                self._display.intern_atom(_UTF8_STRING),
            )
        except Exception:
            return None
        if prop is not None and getattr(prop, "value", None):
            value = prop.value
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace")
            return str(value)
        try:  # pre-EWMH fallback
            name = window.get_wm_name()
        except Exception:
            return None
        return str(name) if name else ""

    def _pid(self, window: Any) -> int | None:
        try:
            prop = window.get_full_property(
                self._display.intern_atom(_NET_WM_PID), _ANY_PROPERTY_TYPE
            )
        except Exception:
            return None
        if prop is None or not getattr(prop, "value", None):
            return None
        return int(prop.value[0])

    def _wm_class(self, window: Any) -> str | None:
        try:
            wm_class = window.get_wm_class()
        except Exception:
            return None
        if not wm_class:
            return None
        return str(wm_class[-1])

    @staticmethod
    def _parse_handle(handle: str) -> int | None:
        try:
            return int(handle, 16) if handle.startswith("0x") else int(handle)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _same_window(expected: TargetWindow, current: TargetWindow) -> bool:
        """Guard against a recycled window id belonging to a different process."""
        if expected.process_id is not None and current.process_id is not None:
            return expected.process_id == current.process_id
        if expected.process_name and current.process_name:
            return expected.process_name == current.process_name
        return True
