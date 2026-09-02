"""The pywinctl window adapter, driven by a fake pywinctl module.

pywinctl is the Windows/macOS window backend. It is wrapped defensively because
its Linux path raises ``KeyError: 'id'`` on Ubuntu 26.04 GNOME - reproduced on
this machine and recorded in docs/PHASE3-PLATFORM-REPORT.md.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from human_input_automation.adapters.pywinctl_windows import PyWinCtlWindows, unsupported_reason
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
    WindowCapabilities,
)


class FakeWindow:
    def __init__(
        self,
        handle: str,
        title: str,
        pid: int | None = 100,
        app: str | None = "App",
        *,
        active: bool = False,
        activate_ok: bool = True,
        raises: str | None = None,
    ) -> None:
        self._handle = handle
        self.title = title
        self._pid = pid
        self._app = app
        self.isActive = active
        self._activate_ok = activate_ok
        self._raises = raises
        self.activated = 0

    def getHandle(self) -> str:
        if self._raises == "handle":
            raise RuntimeError("no handle")
        return self._handle

    def getPID(self) -> int:
        if self._pid is None:
            raise RuntimeError("no pid")
        return self._pid

    def getAppName(self) -> str:
        if self._app is None:
            raise RuntimeError("no app name")
        return self._app

    def activate(self, wait: bool = False) -> bool:
        self.activated += 1
        if self._raises == "activate":
            raise RuntimeError("activation exploded")
        return self._activate_ok


def module(*windows: Any, error: Exception | None = None) -> SimpleNamespace:
    def get_all() -> list[Any]:
        if error is not None:
            raise error
        return list(windows)

    return SimpleNamespace(getAllWindows=get_all)


def host(
    platform: PlatformName = PlatformName.WINDOWS,
    display: DisplayServer = DisplayServer.WINDOWS,
    state: CapabilityState = CapabilityState.AVAILABLE,
) -> PlatformReport:
    matrix = CapabilityMatrix.from_capabilities(
        [
            Capability(name, state)
            for name in (
                CapabilityName.WINDOW_ENUMERATION,
                CapabilityName.WINDOW_ACTIVATION,
                CapabilityName.FOCUS_VERIFICATION,
                CapabilityName.KEYBOARD_INPUT,
            )
        ]
    )
    return PlatformReport(
        platform=platform,
        display_server=display,
        capabilities=WindowCapabilities.from_matrix(matrix),
        matrix=matrix,
    )


def test_windows_are_mapped_with_metadata() -> None:
    adapter = PyWinCtlWindows(host(), module(FakeWindow("0x42", "Notepad", 4321, "notepad.exe")))
    targets = list(adapter.list_windows())
    assert len(targets) == 1
    assert targets[0].handle == "0x42"
    assert targets[0].process_id == 4321
    assert targets[0].process_name == "notepad.exe"
    assert targets[0].platform is PlatformName.WINDOWS


def test_the_gnome_wayland_key_error_becomes_an_empty_list_not_a_crash() -> None:
    """Exactly the failure reproduced on Ubuntu 26.04 GNOME."""
    adapter = PyWinCtlWindows(host(), module(error=KeyError("id")))
    assert list(adapter.list_windows()) == []


def test_untitled_and_unreadable_windows_are_skipped() -> None:
    class NoTitle:
        @property
        def title(self) -> str:
            raise RuntimeError("gone")

    adapter = PyWinCtlWindows(host(), module(NoTitle(), FakeWindow("0x1", "")))
    assert list(adapter.list_windows()) == []


def test_a_window_without_pid_or_app_still_lists() -> None:
    adapter = PyWinCtlWindows(host(), module(FakeWindow("0x7", "Bare", pid=None, app=None)))
    target = next(iter(adapter.list_windows()))
    assert target.process_id is None and target.process_name is None


def test_enumeration_is_skipped_when_the_capability_is_unavailable() -> None:
    adapter = PyWinCtlWindows(
        host(state=CapabilityState.UNAVAILABLE), module(FakeWindow("0x1", "Hidden"))
    )
    assert list(adapter.list_windows()) == []


def test_activation_succeeds_and_is_verified() -> None:
    window = FakeWindow("0x42", "Notepad", active=True)
    adapter = PyWinCtlWindows(host(), module(window), activation_timeout=0.1)
    target = adapter.find("0x42")
    assert target is not None
    assert adapter.activate(target) is True
    assert adapter.is_active(target) is True
    assert window.activated == 1


def test_activation_of_a_closed_window_fails_without_raising() -> None:
    adapter = PyWinCtlWindows(host(), module(FakeWindow("0x42", "Notepad")))
    target = adapter.find("0x42")
    assert target is not None
    gone = PyWinCtlWindows(host(), module(), activation_timeout=0.1)
    assert gone.activate(target) is False
    assert gone.is_active(target) is None


def test_a_recycled_handle_from_another_process_is_refused() -> None:
    original = FakeWindow("0x42", "Notepad", pid=1000)
    adapter = PyWinCtlWindows(host(), module(original))
    target = adapter.find("0x42")
    assert target is not None

    replacement = FakeWindow("0x42", "Something else", pid=2000)
    adapter_after = PyWinCtlWindows(host(), module(replacement))
    assert adapter_after.activate(target) is False
    assert replacement.activated == 0


def test_an_exception_during_activation_is_reported_as_failure() -> None:
    window = FakeWindow("0x42", "Notepad", raises="activate")
    adapter = PyWinCtlWindows(host(), module(window), activation_timeout=0.1)
    target = adapter.find("0x42")
    assert target is not None
    assert adapter.activate(target) is False


def test_activation_is_refused_when_the_platform_forbids_it() -> None:
    window = FakeWindow("0x42", "Notepad")
    adapter = PyWinCtlWindows(host(state=CapabilityState.UNAVAILABLE), module(window))
    from human_input_automation.core.target import TargetWindow

    assert adapter.activate(TargetWindow(handle="0x42")) is False
    assert window.activated == 0


def test_focus_is_unknown_only_when_the_platform_forbids_the_check() -> None:
    """Regression: an *unprobed* permission disabled verification entirely.

    On macOS the Automation permission cannot be preflighted, so the state is
    UNKNOWN. Treating that as "cannot verify" meant focus was never checked and
    input reached a window the user had not selected. Unknown means try.
    """
    from human_input_automation.core.target import TargetWindow

    unknown = PyWinCtlWindows(
        host(state=CapabilityState.UNKNOWN),
        module(FakeWindow("0x42", "Notepad", active=True)),
        activation_timeout=0.05,
    )
    assert unknown.is_active(TargetWindow(handle="0x42")) is True

    forbidden = PyWinCtlWindows(
        host(state=CapabilityState.UNAVAILABLE), module(FakeWindow("0x42", "Notepad"))
    )
    assert forbidden.is_active(TargetWindow(handle="0x42")) is None


def test_activation_is_not_reported_until_focus_is_confirmed() -> None:
    """Regression, observed on macOS: the first run typed into the decoy window.

    pywinctl's activate() returned success while the window server had not yet
    moved keyboard focus, and because verification was disabled nothing caught
    it. Activation now has to observe the focus move.
    """
    from human_input_automation.core.target import TargetWindow

    never_focuses = FakeWindow("0x42", "Notepad", active=False)
    adapter = PyWinCtlWindows(
        host(state=CapabilityState.UNKNOWN), module(never_focuses), activation_timeout=0.1
    )
    assert adapter.activate(TargetWindow(handle="0x42")) is False
    assert never_focuses.activated == 1, "it should have tried exactly once"


def test_activation_stops_promptly_when_the_run_is_cancelled() -> None:
    """macOS activation can take ten seconds; a stop must not wait for it."""
    import time

    from human_input_automation.core.control import RunControl
    from human_input_automation.core.target import TargetWindow

    control = RunControl()
    control.begin()
    control.emergency_stop()

    adapter = PyWinCtlWindows(
        host(state=CapabilityState.UNKNOWN),
        module(FakeWindow("0x42", "Notepad", active=False)),
        activation_timeout=30.0,
    )
    started = time.monotonic()
    assert adapter.activate(TargetWindow(handle="0x42"), control) is False
    assert time.monotonic() - started < 2.0


def test_unsupported_reason_explains_wayland() -> None:
    reason = unsupported_reason(
        host(PlatformName.LINUX, DisplayServer.WAYLAND, CapabilityState.UNAVAILABLE)
    )
    assert reason is not None and "Wayland" in reason
    assert unsupported_reason(host()) is None


# -- handles are not equally stable across platforms ----------------------
def test_a_window_whose_handle_changed_is_matched_by_its_process() -> None:
    """Regression: on macOS pywinctl's handle is ``(application, title)``.

    Source-verified in ``_pywinctl_macos.getHandle``. The handle therefore
    changes whenever the title does - a saved document, a switched tab - and a
    strict handle match would fail to activate a window that is plainly still
    there.
    """
    original = FakeWindow("('Editor', 'notes.txt')", "notes.txt", pid=4321, app="Editor")
    adapter = PyWinCtlWindows(host(PlatformName.MACOS, DisplayServer.QUARTZ), module(original))
    target = adapter.find("('Editor', 'notes.txt')")
    assert target is not None

    renamed = FakeWindow(
        "('Editor', 'notes.txt *')", "notes.txt *", pid=4321, app="Editor", active=True
    )
    after = PyWinCtlWindows(
        host(PlatformName.MACOS, DisplayServer.QUARTZ), module(renamed), activation_timeout=0.1
    )
    assert after.activate(target) is True
    assert renamed.activated == 1


def test_a_changed_handle_with_several_candidates_refuses_to_guess() -> None:
    """Two windows of the same application: ambiguity must never be resolved."""
    original = FakeWindow("('Editor', 'a.txt')", "a.txt", pid=4321, app="Editor")
    adapter = PyWinCtlWindows(host(PlatformName.MACOS, DisplayServer.QUARTZ), module(original))
    target = adapter.find("('Editor', 'a.txt')")
    assert target is not None

    first = FakeWindow("('Editor', 'b.txt')", "b.txt", pid=4321, app="Editor")
    second = FakeWindow("('Editor', 'c.txt')", "c.txt", pid=4321, app="Editor")
    after = PyWinCtlWindows(
        host(PlatformName.MACOS, DisplayServer.QUARTZ),
        module(first, second),
        activation_timeout=0.1,
    )
    assert after.activate(target) is False
    assert first.activated == 0 and second.activated == 0


def test_a_changed_handle_never_matches_a_different_process() -> None:
    original = FakeWindow("('Editor', 'a.txt')", "a.txt", pid=4321, app="Editor")
    adapter = PyWinCtlWindows(host(PlatformName.MACOS, DisplayServer.QUARTZ), module(original))
    target = adapter.find("('Editor', 'a.txt')")
    assert target is not None

    stranger = FakeWindow("('Bank', 'Account')", "Account", pid=9999, app="Bank")
    after = PyWinCtlWindows(
        host(PlatformName.MACOS, DisplayServer.QUARTZ), module(stranger), activation_timeout=0.1
    )
    assert after.activate(target) is False
    assert stranger.activated == 0


def test_a_stable_windows_handle_still_takes_the_direct_path() -> None:
    """On Windows the handle is an HWND and does not move."""
    window = FakeWindow("0x42", "Notepad", pid=100, app="notepad.exe", active=True)
    adapter = PyWinCtlWindows(host(), module(window))
    target = adapter.find("0x42")
    assert target is not None
    assert adapter.activate(target) is True
    assert adapter.is_active(target) is True


def counting_module(*windows: Any) -> SimpleNamespace:
    """A module that records how often the desktop is enumerated."""
    calls: list[int] = []

    def get_all() -> list[Any]:
        calls.append(1)
        return list(windows)

    return SimpleNamespace(getAllWindows=get_all, calls=calls)


class SlowlyFocusingWindow(FakeWindow):
    """Focus arrives only after several probes, as it does on a real desktop."""

    def __init__(self, handle: str, title: str, probes_until_active: int) -> None:
        super().__init__(handle, title)
        self._remaining = probes_until_active

    @property
    def isActive(self) -> bool:
        if self._remaining > 0:
            self._remaining -= 1
            return False
        return True

    @isActive.setter
    def isActive(self, value: bool) -> None:  # pragma: no cover - set by the base class
        pass


def test_focus_probes_do_not_re_enumerate_the_desktop() -> None:
    """Every probe used to enumerate every window, which cost seconds on macOS.

    Measured on a real Mac: one typing action took 26 s and an emergency stop
    took 10.8 s, because each focus check walked the whole desktop over the
    Accessibility API.
    """
    window = SlowlyFocusingWindow("0x42", "Notepad", probes_until_active=5)
    fake = counting_module(window)
    adapter = PyWinCtlWindows(host(), fake)
    target = adapter.list_windows()[0]
    fake.calls.clear()

    assert adapter.activate(target) is True
    assert fake.calls == []


def test_a_remembered_window_is_revalidated_before_it_is_used() -> None:
    """The cache says where to look, never what the answer is."""
    window = FakeWindow("0x42", "Notepad", pid=100)
    adapter = PyWinCtlWindows(host(), module(window), activation_timeout=0.1)
    target = adapter.list_windows()[0]

    # The handle now belongs to a different process: a reused window id.
    window._pid = 999

    assert adapter.activate(target) is False
    assert window.activated == 0


def test_macos_activation_gets_a_longer_budget_than_other_platforms() -> None:
    """AppleScript activation is slow; the wait is cancellable, so it can be."""
    mac = PyWinCtlWindows(host(PlatformName.MACOS, DisplayServer.QUARTZ), module())
    other = PyWinCtlWindows(host(), module())
    assert mac._activation_timeout > other._activation_timeout
