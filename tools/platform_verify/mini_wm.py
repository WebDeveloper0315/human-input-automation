"""A minimal EWMH window manager, for verification only.

An X server with no window manager has no ``_NET_CLIENT_LIST`` and no
``_NET_ACTIVE_WINDOW``, so the window adapter has nothing to read and nothing
to activate. On a real desktop that never happens; on a bare ``Xvfb`` used for
isolated testing it always does.

This supplies the smallest EWMH surface the adapter actually uses:

* maps windows that ask to be mapped
* maintains ``_NET_CLIENT_LIST`` and ``_NET_ACTIVE_WINDOW``
* honours ``_NET_ACTIVE_WINDOW`` client messages by focusing and raising

It is **not** a usable window manager - no decorations, no layout, no input
handling - and it is **not** evidence about GNOME, KDE, i3 or any other real
window manager. Results obtained with it must be reported as "verified against
a minimal EWMH window manager on Xvfb", never as "verified on a native X11
desktop".

    python tools/platform_verify/mini_wm.py --display :99
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

SUPPORTED_ATOMS = (
    "_NET_SUPPORTED",
    "_NET_CLIENT_LIST",
    "_NET_ACTIVE_WINDOW",
    "_NET_WM_NAME",
    "_NET_WM_PID",
    "_NET_SUPPORTING_WM_CHECK",
)


class MiniWindowManager:
    """Just enough EWMH for the window adapter to be exercised."""

    def __init__(self, display_name: str | None = None) -> None:
        from Xlib import X, display

        self.X = X
        self.display = display.Display(display_name)
        self.root = self.display.screen().root
        self.clients: list[int] = []
        self.active: int | None = None
        self._atoms: dict[str, int] = {}

        self.root.change_attributes(
            event_mask=(
                X.SubstructureRedirectMask
                | X.SubstructureNotifyMask
                | X.PropertyChangeMask
                | X.FocusChangeMask
            )
        )
        self.display.sync()
        self._announce()

    # -- properties --------------------------------------------------------
    def atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = self.display.intern_atom(name)
        return self._atoms[name]

    def _announce(self) -> None:
        """Advertise EWMH support the way a real window manager does."""
        from Xlib import X, Xatom

        check = self.root.create_window(-100, -100, 1, 1, 0, self.display.screen().root_depth)
        check.change_property(self.atom("_NET_SUPPORTING_WM_CHECK"), Xatom.WINDOW, 32, [check.id])
        check.change_property(
            self.atom("_NET_WM_NAME"), self.atom("UTF8_STRING"), 8, b"mini-wm"
        )
        self.root.change_property(
            self.atom("_NET_SUPPORTING_WM_CHECK"), Xatom.WINDOW, 32, [check.id]
        )
        self.root.change_property(
            self.atom("_NET_SUPPORTED"),
            Xatom.ATOM,
            32,
            [self.atom(name) for name in SUPPORTED_ATOMS],
        )
        self._publish_clients()
        self.display.sync()
        assert X is not None

    def _publish_clients(self) -> None:
        from Xlib import Xatom

        self.root.change_property(
            self.atom("_NET_CLIENT_LIST"), Xatom.WINDOW, 32, list(self.clients)
        )

    def _publish_active(self) -> None:
        from Xlib import Xatom

        self.root.change_property(
            self.atom("_NET_ACTIVE_WINDOW"), Xatom.WINDOW, 32, [self.active or 0]
        )

    # -- window handling ---------------------------------------------------
    def _focus(self, window_id: int) -> None:
        try:
            window = self.display.create_resource_object("window", window_id)
            window.configure(stack_mode=self.X.Above)
            window.set_input_focus(self.X.RevertToParent, self.X.CurrentTime)
            self.active = window_id
            self._publish_active()
            self.display.sync()
        except Exception as error:  # a window that vanished mid-focus
            print(f"mini-wm: could not focus {window_id:#x}: {error}", file=sys.stderr)

    def _add(self, window_id: int) -> None:
        if window_id not in self.clients:
            self.clients.append(window_id)
            self._publish_clients()

    def _remove(self, window_id: int) -> None:
        if window_id in self.clients:
            self.clients.remove(window_id)
            self._publish_clients()
        if self.active == window_id:
            self.active = self.clients[-1] if self.clients else None
            self._publish_active()

    # -- event loop --------------------------------------------------------
    def handle(self, event: Any) -> None:
        name = event.__class__.__name__
        if name == "MapRequest":
            event.window.map()
            self._add(event.window.id)
            self._focus(event.window.id)
        elif name == "ConfigureRequest":
            event.window.configure(
                x=event.x, y=event.y, width=event.width, height=event.height
            )
        elif name in ("DestroyNotify", "UnmapNotify"):
            self._remove(event.window.id)
        elif name == "ClientMessage" and event.client_type == self.atom("_NET_ACTIVE_WINDOW"):
            self._focus(event.window.id)

    def run(self, seconds: float = 0.0) -> None:
        deadline = time.monotonic() + seconds if seconds > 0 else None
        print(f"mini-wm: managing {self.display.get_display_name()}", flush=True)
        while deadline is None or time.monotonic() < deadline:
            while self.display.pending_events():
                self.handle(self.display.next_event())
            time.sleep(0.01)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default=None, help="X display, e.g. :99")
    parser.add_argument("--seconds", type=float, default=0.0, help="exit after this long")
    arguments = parser.parse_args(argv)
    MiniWindowManager(arguments.display).run(arguments.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
