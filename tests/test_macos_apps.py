"""Running applications on macOS, through fake AppKit and Quartz modules."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from human_input_automation.adapters.macos_apps import MacApplications, front_process_id
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    RunningApplication,
    WindowCapabilities,
)

HOST = PlatformReport(
    platform=PlatformName.MACOS,
    display_server=DisplayServer.QUARTZ,
    capabilities=WindowCapabilities.full(),
)


class Desktop:
    """Which windows are on screen, front first; what is running."""

    def __init__(self) -> None:
        self.windows: list[dict[str, Any]] = []
        self.running: dict[int, tuple[str, int]] = {}  # pid -> (name, policy)
        self.polite_works = True
        self.opened: list[list[str]] = []

    def put_in_front(self, pid: int) -> None:
        mine = [w for w in self.windows if w["kCGWindowOwnerPID"] == pid]
        others = [w for w in self.windows if w["kCGWindowOwnerPID"] != pid]
        layer0 = [w for w in others if w["kCGWindowLayer"] == 0]
        above = [w for w in others if w["kCGWindowLayer"] != 0]
        self.windows = above + mine + layer0

    @property
    def quartz(self) -> SimpleNamespace:
        return SimpleNamespace(
            kCGWindowListOptionOnScreenOnly=1,
            kCGWindowListExcludeDesktopElements=16,
            kCGNullWindowID=0,
            CGWindowListCopyWindowInfo=lambda options, relative: list(self.windows),
        )

    @property
    def appkit(self) -> SimpleNamespace:
        desktop = self

        class App:
            def __init__(self, pid: int) -> None:
                self.pid = pid

            def activationPolicy(self) -> int:
                return desktop.running[self.pid][1]

            def processIdentifier(self) -> int:
                return self.pid

            def localizedName(self) -> str:
                return desktop.running[self.pid][0]

            def activateWithOptions_(self, options: int) -> bool:
                if desktop.polite_works:
                    desktop.put_in_front(self.pid)
                return True

            def bundleURL(self) -> Any:
                name = desktop.running[self.pid][0]
                return SimpleNamespace(path=lambda: f"/Applications/{name}.app")

        return SimpleNamespace(
            NSWorkspace=SimpleNamespace(
                sharedWorkspace=lambda: SimpleNamespace(
                    runningApplications=lambda: [App(pid) for pid in desktop.running]
                )
            ),
            NSRunningApplication=SimpleNamespace(
                runningApplicationWithProcessIdentifier_=lambda pid: (
                    App(pid) if pid in desktop.running else None
                )
            ),
        )

    def run(self, command: list[str], **kwargs: Any) -> SimpleNamespace:
        self.opened.append(command)
        path = command[-1]
        pid = next(p for p, (name, _) in self.running.items() if path.endswith(f"{name}.app"))
        self.put_in_front(pid)
        return SimpleNamespace(returncode=0)


def window(pid: int, owner: str, layer: int = 0) -> dict[str, Any]:
    return {"kCGWindowOwnerPID": pid, "kCGWindowOwnerName": owner, "kCGWindowLayer": layer}


def desktop() -> Desktop:
    d = Desktop()
    d.running = {100: ("Finder", 0), 412: ("Terminal", 0), 900: ("iTerm2", 0), 50: ("Dock", 2)}
    d.windows = [
        window(50, "Dock", 20),
        window(900, "iTerm2"),
        window(412, "Terminal"),
        window(100, "Finder"),
        window(100, "Finder"),
    ]
    return d


def apps(d: Desktop) -> MacApplications:
    return MacApplications(HOST, appkit=d.appkit, quartz=d.quartz, run=d.run, sleep=lambda s: None)


def by_name(d: Desktop) -> dict[str, RunningApplication]:
    return {app.name: app for app in apps(d).applications()}


def test_applications_are_named_with_their_window_counts() -> None:
    found = by_name(desktop())
    assert found["Finder"].windows == 2 and found["Terminal"].windows == 1
    assert found["Terminal"].target.process_id == 412
    assert "Dock" not in found, "background agents are not applications to drive"


def test_the_front_window_owner_skips_panels_above_the_normal_layer() -> None:
    assert front_process_id(desktop().quartz) == 900


def test_activation_confirms_the_application_came_forward() -> None:
    d = desktop()
    assert apps(d).activate_application(by_name(d)["Terminal"])
    assert front_process_id(d.quartz) == 412 and d.opened == []


def test_when_macos_declines_the_request_launchservices_is_asked() -> None:
    """macOS 14+ may ignore activateWithOptions from a program not in front."""
    d = desktop()
    d.polite_works = False
    assert apps(d).activate_application(by_name(d)["Terminal"])
    assert d.opened == [["open", "-a", "/Applications/Terminal.app"]]


def test_an_application_that_has_quit_is_not_activated() -> None:
    d = desktop()
    terminal = by_name(d)["Terminal"]
    del d.running[412]
    assert not apps(d).activate_application(terminal)


def test_a_stop_ends_the_wait_for_activation() -> None:
    d = desktop()
    d.polite_works = False
    stop = SimpleNamespace(wait_for_stop=lambda s: True, is_stop_requested=lambda: True)
    assert not apps(d).activate_application(by_name(d)["Terminal"], stop)
    assert d.opened == []


def test_a_broken_pyobjc_gives_an_empty_list_not_an_error() -> None:
    broken = SimpleNamespace()
    assert MacApplications(HOST, appkit=broken, quartz=broken).applications() == []
