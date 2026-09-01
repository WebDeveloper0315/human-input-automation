"""The profile service: prepare, import/export, and the no-execution guarantee."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.profiles import (
    Profile,
    ProfileFormatError,
    ProfileRepository,
    ProfileService,
    ProfileState,
    ProfileStorageError,
)
from human_input_automation.application.service import AutomationService
from human_input_automation.core.actions import MouseMove, TypeText
from human_input_automation.core.events import RunStatus
from human_input_automation.core.plan import AutomationPlan, ExecutionLimits
from human_input_automation.core.screen import CoordinateSpace, MonitorInfo, ScreenGeometry
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile

from .fakes import FakeKeyboard, FakeMouse, FakeWindows, make_target


@pytest.fixture
def service(tmp_path: Path) -> ProfileService:
    return ProfileService(ProfileRepository(tmp_path / "profiles"))


def host(platform: PlatformName = PlatformName.LINUX) -> PlatformReport:
    return PlatformReport(
        platform=platform,
        display_server=DisplayServer.X11,
        capabilities=WindowCapabilities.full(),
    )


def make_plan(*actions: Any) -> AutomationPlan:
    return AutomationPlan(
        make_target(), list(actions) or [TypeText(text="hi")], timing=TimingProfile.instant()
    )


# -- building and saving --------------------------------------------------
def test_build_keeps_only_persistent_target_identity(service: ProfileService) -> None:
    profile = service.build("Editor macro", make_plan(), make_target())
    assert profile.target.process_name == "test-app"
    assert profile.target.handle_hint == "win-1"
    # No live state: capabilities and pid are runtime facts, not identity.
    assert not hasattr(profile.target, "capabilities")
    assert not hasattr(profile.target, "process_id")


def test_build_accepts_a_title_pattern(service: ProfileService) -> None:
    profile = service.build("P", make_plan(), make_target(), title_pattern=r".*Firefox.*")
    assert profile.target.title_pattern == r".*Firefox.*"


def test_duplicate_gets_a_new_id_and_is_not_saved(service: ProfileService) -> None:
    original = service.save(service.build("Original", make_plan(), make_target()))
    copy = service.duplicate(original)
    assert copy.id != original.id
    assert copy.name == "Original (copy)"
    assert copy.created_at is None
    assert len(service.list()) == 1, "duplicate must not write until saved"

    service.save(copy)
    assert len(service.list()) == 2


# -- prepare --------------------------------------------------------------
def test_prepare_resolves_and_validates(service: ProfileService) -> None:
    profile = service.build("Editor macro", make_plan(), make_target())
    loaded = service.prepare(profile, [make_target()], host())
    assert loaded.state is ProfileState.TARGET_RESOLVED
    assert loaded.is_runnable
    assert loaded.plan is not None
    assert loaded.plan.target.handle == "win-1"
    assert loaded.plan.name == "Editor macro"


def test_prepare_reports_an_unresolved_target_without_a_plan(service: ProfileService) -> None:
    profile = service.build("Editor macro", make_plan(), make_target())
    loaded = service.prepare(profile, [], host())
    assert loaded.state is ProfileState.TARGET_UNRESOLVED
    assert not loaded.is_runnable
    assert loaded.plan is None, "an unresolved profile must not produce a runnable plan"


def test_prepare_reports_ambiguity(service: ProfileService) -> None:
    profile = service.build("Editor macro", make_plan(), make_target())
    windows = [make_target("a", "One"), make_target("b", "Two")]
    loaded = service.prepare(profile, windows, host())
    assert loaded.state is ProfileState.TARGET_AMBIGUOUS
    assert not loaded.is_runnable


def test_prepare_reports_a_platform_mismatch(service: ProfileService) -> None:
    profile = service.build("Editor macro", make_plan(), make_target())
    loaded = service.prepare(profile, [make_target()], host(PlatformName.WINDOWS))
    assert loaded.state is ProfileState.TARGET_UNRESOLVED
    assert "saved on linux" in loaded.message


def test_prepare_reuses_existing_domain_validation(service: ProfileService) -> None:
    """Limits and coordinates are checked by validate_plan, not re-implemented."""
    plan = AutomationPlan(
        make_target(), [TypeText(text="x" * 50)], limits=ExecutionLimits(max_text_length=10)
    )
    profile = service.build("Too much text", plan, make_target())
    loaded = service.prepare(profile, [make_target()], host())
    assert loaded.state is ProfileState.PROFILE_INVALID
    assert any(issue.code == "action.text_too_long" for issue in loaded.errors)
    assert not loaded.is_runnable


def test_prepare_validates_coordinates_against_the_screen(service: ProfileService) -> None:
    profile = service.build("Off screen", make_plan(MouseMove(x=9000, y=9000)), make_target())
    screen = ScreenGeometry(
        monitors=(MonitorInfo("primary", 0, 0, 1920, 1080, is_primary=True),),
        coordinate_space=CoordinateSpace.PHYSICAL,
    )
    loaded = service.prepare(profile, [make_target()], host(), screen)
    assert loaded.state is ProfileState.PROFILE_INVALID
    assert any(issue.code == "action.coordinates_off_screen" for issue in loaded.errors)


def test_prepare_keeps_warnings_for_a_runnable_profile(service: ProfileService) -> None:
    limited = make_target(
        capabilities=WindowCapabilities(can_enumerate=True, can_send_synthetic_input=True)
    )
    profile = service.build("Warned", make_plan(), limited)
    loaded = service.prepare(profile, [limited], host())
    assert loaded.is_runnable
    assert loaded.warnings


def test_a_profile_without_a_plan_is_invalid(service: ProfileService) -> None:
    loaded = service.prepare(Profile(name="Empty"), [make_target()], host())
    assert loaded.state is ProfileState.PROFILE_INVALID


# -- import / export ------------------------------------------------------
def test_export_then_import_round_trips(service: ProfileService, tmp_path: Path) -> None:
    profile = service.save(service.build("Exported", make_plan(), make_target()))
    path = service.export(profile, tmp_path / "exported.json")
    assert path.is_file()

    imported = service.import_file(path)
    assert imported.name == "Exported"
    assert imported.id != profile.id, "an import must not overwrite an existing profile"
    assert len(service.list()) == 2


def test_import_keeps_the_id_when_it_is_free(service: ProfileService, tmp_path: Path) -> None:
    profile = service.build("Fresh", make_plan(), make_target())
    path = service.export(profile, tmp_path / "fresh.json")
    imported = service.import_file(path)
    assert imported.id == profile.id


def test_importing_a_malformed_file_fails_cleanly(
    service: ProfileService, tmp_path: Path
) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ProfileFormatError):
        service.import_file(path)
    assert service.list() == ()


def test_importing_an_unknown_action_is_refused(service: ProfileService, tmp_path: Path) -> None:
    path = tmp_path / "hostile.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "name": "Hostile",
                "target": {},
                "plan": {"actions": [{"type": "shell", "command": "rm -rf /"}]},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProfileFormatError) as excinfo:
        service.import_file(path)
    assert "Unknown action type: shell" in str(excinfo.value)
    assert service.list() == ()


def test_importing_a_missing_file_reports_storage_failure(service: ProfileService) -> None:
    with pytest.raises(ProfileStorageError):
        service.import_file("/nonexistent/profile.json")


def test_validate_file_does_not_store_anything(service: ProfileService, tmp_path: Path) -> None:
    profile = service.build("Checked", make_plan(), make_target())
    path = service.export(profile, tmp_path / "check.json")
    assert service.validate_file(path).name == "Checked"
    assert service.list() == ()


def test_export_to_an_unwritable_path_is_reported(service: ProfileService) -> None:
    profile = service.build("X", make_plan(), make_target())
    with pytest.raises(ProfileStorageError):
        service.export(profile, "/nonexistent-directory/profile.json")


# -- the safety guarantee -------------------------------------------------
class ExplodingKeyboard(FakeKeyboard):
    def type_text(self, text: str) -> None:
        raise AssertionError("a profile operation must never send input")

    def key_down(self, key: object) -> None:
        raise AssertionError("a profile operation must never send input")


def automation_service(tmp_path: Path) -> tuple[AutomationService, FakeKeyboard, FakeWindows]:
    keyboard = ExplodingKeyboard()
    windows = FakeWindows(windows=[make_target()])
    adapters = AdapterSet(
        keyboard=keyboard,
        mouse=FakeMouse(),
        windows=windows,
        discovery=windows,
        clock=SystemClock(),
        host=host(),
    )
    service = AutomationService(
        adapters, profiles=ProfileService(ProfileRepository(tmp_path / "profiles"))
    )
    return service, keyboard, windows


def test_no_profile_operation_sends_input(tmp_path: Path) -> None:
    """save, load, list, import, export, validate, resolve, prepare - all inert."""
    service, keyboard, _ = automation_service(tmp_path)
    profiles = service.profiles

    profile = profiles.save(profiles.build("Inert", make_plan(), make_target()))
    profiles.list()
    profiles.load(profile.id)
    exported = profiles.export(profile, tmp_path / "out.json")
    profiles.import_file(exported)
    profiles.validate_file(exported)
    profiles.resolve(profile, [make_target()], PlatformName.LINUX)
    loaded = service.prepare_profile(profile)

    assert loaded.is_runnable, "the profile is runnable, but nothing has run"
    assert keyboard.calls == []
    assert not service.is_running


def test_a_prepared_profile_can_be_dry_run_without_touching_the_adapters(
    tmp_path: Path,
) -> None:
    service, keyboard, windows = automation_service(tmp_path)
    profile = service.profiles.build("Dry", make_plan(), make_target())
    loaded = service.prepare_profile(profile)
    assert loaded.plan is not None

    report = service.dry_run(loaded.plan)
    assert report.status is RunStatus.COMPLETED and report.dry_run
    assert keyboard.calls == [] and windows.calls == []


def test_prepare_profile_uses_the_live_window_list(tmp_path: Path) -> None:
    service, _, windows = automation_service(tmp_path)
    profile = service.profiles.build("Live", make_plan(), make_target())
    assert service.prepare_profile(profile).is_runnable

    windows.windows = []  # the application closed
    assert service.prepare_profile(profile).state is ProfileState.TARGET_UNRESOLVED


def test_the_service_exposes_its_profile_directory(tmp_path: Path) -> None:
    service, _, _ = automation_service(tmp_path)
    assert service.profiles.directory == tmp_path / "profiles"
