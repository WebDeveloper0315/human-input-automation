"""The application service, wired with null/fake adapters (no desktop needed)."""

from __future__ import annotations

from typing import Any

from human_input_automation.adapters.null import NullKeyboard, NullMouse
from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.application.service import AutomationService
from human_input_automation.core.actions import TypeText
from human_input_automation.core.events import RunStatus
from human_input_automation.core.plan import AutomationPlan
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile
from human_input_automation.ui.models import host_status_text

from .fakes import FakeClock, FakeKeyboard, FakeMouse, FakeWindows, make_target


def build_service(host: PlatformReport | None = None) -> tuple[AutomationService, FakeKeyboard]:
    keyboard = FakeKeyboard()
    windows = FakeWindows(windows=[make_target()])
    adapters = AdapterSet(
        keyboard=keyboard,
        mouse=FakeMouse(),
        windows=windows,
        discovery=windows,
        clock=FakeClock(),
        host=host
        or PlatformReport(
            platform=PlatformName.LINUX,
            display_server=DisplayServer.X11,
            capabilities=WindowCapabilities.full(),
        ),
    )
    return AutomationService(adapters), keyboard


def test_service_lists_targets_from_the_discovery_adapter() -> None:
    service, _ = build_service()
    assert [target.handle for target in service.list_targets()] == ["win-1"]


def test_focused_window_target_inherits_host_capabilities() -> None:
    service, _ = build_service()
    target = service.focused_window_target()
    assert target.is_focused_window
    assert target.platform is PlatformName.LINUX


def test_validation_uses_the_host_report() -> None:
    service, _ = build_service(
        PlatformReport(
            platform=PlatformName.WINDOWS,
            display_server=DisplayServer.WINDOWS,
            capabilities=WindowCapabilities.full(),
        )
    )
    plan = AutomationPlan(make_target(), [TypeText(text="hi")])
    result = service.validate(plan)
    assert "target.platform_mismatch" in {issue.code for issue in result.errors}


def test_dry_run_is_synchronous_and_sends_nothing() -> None:
    service, keyboard = build_service()
    plan = AutomationPlan(
        make_target(), [TypeText(text="hello")], timing=TimingProfile.instant()
    )
    report = service.dry_run(plan)
    assert report.status is RunStatus.COMPLETED and report.dry_run
    assert keyboard.calls == []


def test_status_text_surfaces_platform_limitations() -> None:
    host = PlatformReport(
        platform=PlatformName.LINUX,
        display_server=DisplayServer.WAYLAND,
        capabilities=WindowCapabilities(),
        missing_permissions=("something",),
        warnings=("Wayland restricts input",),
    )
    service, _ = build_service(host)
    text = host_status_text(service.host, service.problems)
    assert "wayland" in text
    assert "Wayland restricts input" in text
    assert "Missing permission: something" in text


def test_null_adapters_report_a_non_functional_host() -> None:
    adapters = AdapterSet(
        keyboard=NullKeyboard(),
        mouse=NullMouse(),
        windows=None,
        discovery=None,
        clock=FakeClock(),
        host=PlatformReport(
            platform=PlatformName.UNKNOWN,
            display_server=DisplayServer.UNKNOWN,
            capabilities=WindowCapabilities.unknown(),
        ),
    )
    assert not adapters.is_functional
    assert not adapters.has_real_pointer
    service = AutomationService(adapters)
    assert service.list_targets() == ()
    # The null mouse answers (0, 0) to keep the engine simple; that is a fine
    # answer for a dry run and a misleading one to offer a user as a position.
    assert service.pointer_position() is None


def service_with_mouse(mouse: Any) -> AutomationService:
    return AutomationService(
        AdapterSet(
            keyboard=FakeKeyboard(),
            mouse=mouse,
            windows=None,
            discovery=None,
            clock=FakeClock(),
            host=PlatformReport(
                platform=PlatformName.LINUX,
                display_server=DisplayServer.X11,
                capabilities=WindowCapabilities.full(),
            ),
        )
    )


def test_the_pointer_is_read_through_the_port_that_will_move_it() -> None:
    """Not from the window system: on a scaled display the two disagree."""
    mouse = FakeMouse()
    mouse.move_to(640, 400, 0)

    assert service_with_mouse(mouse).pointer_position() == (640, 400)


def test_a_pointer_that_raises_is_reported_as_unreadable() -> None:
    class BrokenMouse(FakeMouse):
        def position(self) -> tuple[int, int]:
            raise RuntimeError("the display went away")

    assert service_with_mouse(BrokenMouse()).pointer_position() is None
