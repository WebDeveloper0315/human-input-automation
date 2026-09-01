"""The X11/EWMH window adapter, driven by a fake Xlib display.

The adapter was also run live against this machine's X server (see
docs/PHASE3-PLATFORM-REPORT.md); these tests pin the logic so it stays correct
without an X server present.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from human_input_automation.adapters.x11_windows import X11Windows, format_handle
from human_input_automation.core.capabilities import (
    Capability,
    CapabilityMatrix,
    CapabilityName,
    CapabilityState,
)
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
    WindowCapabilities,
)


class FakeProperty:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeWindow:
    def __init__(
        self,
        title: str,
        pid: int | None,
        wm_class: tuple[str, ...] | None,
        window_id: int = 0,
    ) -> None:
        self.id = window_id  # real Xlib window objects carry their id
        self.title = title
        self.pid = pid
        self.wm_class = wm_class
        self.configured: list[Any] = []

    def get_full_property(self, atom: str, kind: Any) -> FakeProperty | None:
        if atom == "_NET_WM_NAME":
            return FakeProperty(self.title.encode("utf-8"))
        if atom == "_NET_WM_PID":
            return FakeProperty([self.pid]) if self.pid is not None else None
        return None

    def get_wm_name(self) -> str:
        return self.title

    def get_wm_class(self) -> tuple[str, ...] | None:
        return self.wm_class

    def configure(self, **kwargs: Any) -> None:
        self.configured.append(kwargs)


class FakeRoot:
    def __init__(self, client_ids: list[int], active: int | None) -> None:
        self.client_ids = client_ids
        self.active = active
        self.events: list[Any] = []

    def get_full_property(self, atom: str, kind: Any) -> FakeProperty | None:
        if atom == "_NET_CLIENT_LIST":
            return FakeProperty(list(self.client_ids))
        if atom == "_NET_ACTIVE_WINDOW":
            return FakeProperty([self.active]) if self.active is not None else None
        return None

    def send_event(self, event: Any, event_mask: Any = 0) -> None:
        self.events.append(event)


class FakeClientMessage:
    def __init__(self, window: Any, client_type: Any, data: Any) -> None:
        self.window = window
        self.client_type = client_type
        self.data = data


FAKE_XLIB = SimpleNamespace(
    X=SimpleNamespace(
        CurrentTime=0, SubstructureRedirectMask=1, SubstructureNotifyMask=2, Above=0
    ),
    protocol=SimpleNamespace(event=SimpleNamespace(ClientMessage=FakeClientMessage)),
)


class FakeDisplay:
    """Minimal stand-in for ``Xlib.display.Display``."""

    def __init__(self, windows: dict[int, FakeWindow], active: int | None = None) -> None:
        self.windows = windows
        self.root = FakeRoot(list(windows), active)
        self.closed = False
        self.synced = 0

    def screen(self) -> Any:
        return type("Screen", (), {"root": self.root})()

    def intern_atom(self, name: str) -> str:
        return name

    def create_resource_object(self, kind: str, window_id: int) -> FakeWindow:
        return self.windows[window_id]

    def sync(self) -> None:
        self.synced += 1

    def close(self) -> None:
        self.closed = True


class BrokenDisplay:
    def screen(self) -> Any:
        raise RuntimeError("X connection lost")

    def intern_atom(self, name: str) -> str:
        return name

    def create_resource_object(self, kind: str, window_id: int) -> Any:
        raise RuntimeError("X connection lost")

    def close(self) -> None:
        raise RuntimeError("X connection lost")


def host(
    *,
    enumerate_state: CapabilityState = CapabilityState.AVAILABLE,
    activate_state: CapabilityState = CapabilityState.AVAILABLE,
    verify_state: CapabilityState = CapabilityState.AVAILABLE,
    display_server: DisplayServer = DisplayServer.X11,
) -> PlatformReport:
    matrix = CapabilityMatrix.from_capabilities(
        [
            Capability(CapabilityName.WINDOW_ENUMERATION, enumerate_state),
            Capability(CapabilityName.WINDOW_ACTIVATION, activate_state),
            Capability(CapabilityName.FOCUS_VERIFICATION, verify_state),
            Capability(CapabilityName.KEYBOARD_INPUT, CapabilityState.AVAILABLE),
        ]
    )
    return PlatformReport(
        platform=PlatformName.LINUX,
        display_server=display_server,
        capabilities=WindowCapabilities.from_matrix(matrix),
        matrix=matrix,
    )


def display_with_two_windows() -> FakeDisplay:
    return FakeDisplay(
        {
            0x01800004: FakeWindow("Editor - project", 7446, ("code", "code")),
            0x01800024: FakeWindow("Terminal", 8123, ("gnome-terminal", "Gnome-terminal")),
        },
        active=0x01800004,
    )


# -- discovery ------------------------------------------------------------
def test_windows_are_enumerated_with_handle_pid_and_class() -> None:
    adapter = X11Windows(host(), display_with_two_windows(), FAKE_XLIB)
    targets = adapter.list_windows()
    assert [t.handle for t in targets] == ["0x01800004", "0x01800024"]
    assert targets[0].title == "Editor - project"
    assert targets[0].process_id == 7446
    assert targets[0].process_name == "code"
    assert targets[0].platform is PlatformName.LINUX


def test_untitled_windows_are_skipped() -> None:
    display = FakeDisplay({1: FakeWindow("", 10, ("x", "x")), 2: FakeWindow("Real", 11, None)})
    targets = X11Windows(host(), display, FAKE_XLIB).list_windows()
    assert [t.title for t in targets] == ["Real"]


def test_enumeration_is_refused_when_the_capability_says_so() -> None:
    adapter = X11Windows(
        host(enumerate_state=CapabilityState.UNAVAILABLE), display_with_two_windows(), FAKE_XLIB
    )
    assert adapter.list_windows() == ()


def test_a_broken_x_connection_yields_no_windows_instead_of_raising() -> None:
    adapter = X11Windows(host(), BrokenDisplay(), FAKE_XLIB)
    assert list(adapter.list_windows()) == []
    assert adapter.find("0x1") is None
    assert adapter.active_handle() is None


def test_find_resolves_by_handle_not_by_title() -> None:
    display = display_with_two_windows()
    adapter = X11Windows(host(), display, FAKE_XLIB)
    display.windows[0x01800004].title = "Editor - renamed"
    found = adapter.find("0x01800004")
    assert found is not None and found.title == "Editor - renamed"


def test_a_closed_window_can_no_longer_be_found() -> None:
    display = display_with_two_windows()
    adapter = X11Windows(host(), display, FAKE_XLIB)
    del display.windows[0x01800024]
    display.root.client_ids = [0x01800004]
    assert adapter.find("0x01800024") is None


def test_handles_are_formatted_consistently() -> None:
    assert format_handle(0x1800004) == "0x01800004"


# -- activation -----------------------------------------------------------
def test_activation_sends_an_ewmh_client_message() -> None:
    display = display_with_two_windows()
    adapter = X11Windows(host(), display, FAKE_XLIB)
    target = adapter.find("0x01800004")
    assert target is not None
    assert adapter.activate(target) is True
    assert display.root.events, "an _NET_ACTIVE_WINDOW message should be sent"
    assert display.synced == 1


def test_activation_is_refused_when_the_platform_does_not_allow_it() -> None:
    """A Wayland session: no activation is attempted at all."""
    display = display_with_two_windows()
    adapter = X11Windows(
        host(activate_state=CapabilityState.UNAVAILABLE, display_server=DisplayServer.WAYLAND),
        display,
        FAKE_XLIB,
    )
    target = adapter.find("0x01800004")
    assert target is not None
    assert adapter.activate(target) is False
    assert display.root.events == []


def test_activation_fails_when_the_window_has_gone() -> None:
    display = display_with_two_windows()
    adapter = X11Windows(host(), display, FAKE_XLIB)
    target = adapter.find("0x01800024")
    assert target is not None
    display.root.client_ids = [0x01800004]
    assert adapter.activate(target) is False


def test_a_recycled_window_id_belonging_to_another_process_is_refused() -> None:
    """The id survived but the process behind it changed: never type into it."""
    display = display_with_two_windows()
    adapter = X11Windows(host(), display, FAKE_XLIB)
    target = adapter.find("0x01800004")
    assert target is not None
    display.windows[0x01800004].pid = 9999
    assert adapter.activate(target) is False
    assert display.root.events == []


def test_activation_reports_failure_when_focus_lands_elsewhere() -> None:
    display = display_with_two_windows()
    display.root.active = 0x01800024
    adapter = X11Windows(host(), display, FAKE_XLIB)
    target = adapter.find("0x01800004")
    assert target is not None
    assert adapter.activate(target) is False


# -- focus ----------------------------------------------------------------
def test_focus_verification_reads_net_active_window() -> None:
    adapter = X11Windows(host(), display_with_two_windows(), FAKE_XLIB)
    assert adapter.active_handle() == "0x01800004"
    assert adapter.is_active(TargetWindow(handle="0x01800004")) is True
    assert adapter.is_active(TargetWindow(handle="0x01800024")) is False


def test_focus_is_unknown_when_the_platform_cannot_verify_it() -> None:
    adapter = X11Windows(
        host(verify_state=CapabilityState.UNAVAILABLE), display_with_two_windows(), FAKE_XLIB
    )
    assert adapter.is_active(TargetWindow(handle="0x01800004")) is None


def test_focus_is_unknown_when_no_active_window_is_reported() -> None:
    adapter = X11Windows(host(), FakeDisplay({1: FakeWindow("W", 1, None)}, active=None), FAKE_XLIB)
    assert adapter.is_active(TargetWindow(handle="0x00000001")) is None


def test_close_is_safe_even_when_the_display_errors() -> None:
    adapter = X11Windows(host(), BrokenDisplay(), FAKE_XLIB)
    adapter.close()  # must not raise


# -- activation is asynchronous -------------------------------------------
class SlowRoot(FakeRoot):
    """A root window whose focus property lags behind the activation request.

    Real window managers are asynchronous: activation is a message they handle
    on their own schedule, so `_NET_ACTIVE_WINDOW` read immediately afterwards
    can still report the previous focus.
    """

    def __init__(self, client_ids: list[int], active: int, lag: int) -> None:
        super().__init__(client_ids, active)
        self.lag = lag
        self.requested: int | None = None

    def send_event(self, event: Any, event_mask: Any = 0) -> None:
        self.events.append(event)
        self.requested = getattr(event.window, "id", None)

    def get_full_property(self, atom: str, kind: Any) -> FakeProperty | None:
        if atom == "_NET_ACTIVE_WINDOW" and self.requested is not None:
            if self.lag > 0:
                self.lag -= 1
            else:
                self.active = self.requested
                self.requested = None
        return super().get_full_property(atom, kind)


class SlowDisplay(FakeDisplay):
    def __init__(self, windows: dict[int, FakeWindow], active: int, lag: int) -> None:
        super().__init__(windows, active=active)
        self.root = SlowRoot(list(windows), active, lag)


def test_activation_waits_for_the_window_manager_to_act() -> None:
    """Regression: an immediate focus check reported false activation failures.

    Found on a real X server during Phase 6 verification - the activation had
    worked, but the check ran before the window manager had processed it.
    """
    display = SlowDisplay(
        {
            0x01: FakeWindow("Target", 100, ("app", "app"), window_id=0x01),
            0x02: FakeWindow("Other", 200, ("other", "other"), window_id=0x02),
        },
        active=0x02,
        lag=3,
    )
    adapter = X11Windows(host(), display, FAKE_XLIB, activation_timeout=2.0)
    target = adapter.find("0x00000001")
    assert target is not None
    assert adapter.activate(target) is True
    assert display.root.active == 0x01


def test_activation_gives_up_when_focus_never_arrives() -> None:
    """A window manager that ignores the request must not be called a success."""
    display = FakeDisplay(
        {0x01: FakeWindow("Target", 100, ("app", "app"), window_id=0x01)}, active=0x99
    )
    adapter = X11Windows(host(), display, FAKE_XLIB, activation_timeout=0.05)
    target = adapter.find("0x00000001")
    assert target is not None
    assert adapter.activate(target) is False


def test_activation_succeeds_when_focus_cannot_be_verified() -> None:
    """Unknown is not failure: the engine applies its own policy for that."""
    display = FakeDisplay({0x01: FakeWindow("Target", 100, ("app", "app"))}, active=None)
    adapter = X11Windows(
        host(verify_state=CapabilityState.UNAVAILABLE),
        display,
        FAKE_XLIB,
        activation_timeout=0.05,
    )
    target = adapter.find("0x00000001")
    assert target is not None
    assert adapter.activate(target) is True
