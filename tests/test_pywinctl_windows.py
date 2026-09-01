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
    adapter = PyWinCtlWindows(host(), module(window))
    target = adapter.find("0x42")
    assert target is not None
    assert adapter.activate(target) is True
    assert adapter.is_active(target) is True
    assert window.activated == 1


def test_activation_of_a_closed_window_fails_without_raising() -> None:
    adapter = PyWinCtlWindows(host(), module(FakeWindow("0x42", "Notepad")))
    target = adapter.find("0x42")
    assert target is not None
    gone = PyWinCtlWindows(host(), module())
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
    adapter = PyWinCtlWindows(host(), module(window))
    target = adapter.find("0x42")
    assert target is not None
    assert adapter.activate(target) is False


def test_activation_is_refused_when_the_platform_forbids_it() -> None:
    window = FakeWindow("0x42", "Notepad")
    adapter = PyWinCtlWindows(host(state=CapabilityState.UNAVAILABLE), module(window))
    from human_input_automation.core.target import TargetWindow

    assert adapter.activate(TargetWindow(handle="0x42")) is False
    assert window.activated == 0


def test_focus_is_unknown_when_verification_is_unavailable() -> None:
    from human_input_automation.core.target import TargetWindow

    adapter = PyWinCtlWindows(
        host(state=CapabilityState.UNKNOWN), module(FakeWindow("0x42", "Notepad"))
    )
    assert adapter.is_active(TargetWindow(handle="0x42")) is None


def test_unsupported_reason_explains_wayland() -> None:
    reason = unsupported_reason(
        host(PlatformName.LINUX, DisplayServer.WAYLAND, CapabilityState.UNAVAILABLE)
    )
    assert reason is not None and "Wayland" in reason
    assert unsupported_reason(host()) is None
