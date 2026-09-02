"""First-run briefing and permission onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from human_input_automation.adapters.platform_info import (
    MACOS_ACCESSIBILITY,
    MACOS_AUTOMATION,
    MACOS_INPUT_MONITORING,
    describe_host,
)
from human_input_automation.core.capabilities import CapabilityState
from human_input_automation.core.target import DisplayServer, PlatformName
from human_input_automation.ui.models import (
    first_run_summary,
    outstanding_permissions,
    permission_guidance,
)


def macos(
    accessibility: bool | None,
    input_monitoring: bool | None,
    automation: bool | None = None,
) -> Any:
    return describe_host(
        PlatformName.MACOS,
        DisplayServer.QUARTZ,
        env={},
        accessibility_trusted=accessibility,
        input_monitoring_trusted=input_monitoring,
        automation_trusted=automation if automation is not None else accessibility,
    )


# -- guidance model (no Qt) ----------------------------------------------
def test_macos_permissions_are_reported_separately() -> None:
    """Three different grants, not one prompt: each unlocks something else."""
    guidance = permission_guidance(macos(False, False, automation=False))
    names = [item.permission for item in guidance]
    assert names == sorted([MACOS_ACCESSIBILITY, MACOS_AUTOMATION, MACOS_INPUT_MONITORING])
    assert len(guidance) == 3


def test_macos_window_control_is_attributed_to_automation() -> None:
    """Regression: window control was wrongly attributed to Accessibility.

    pywinctl's macOS backend runs AppleScript against System Events for
    getAllWindows, getActiveWindow and activate, so the blocking permission is
    Automation. Telling the user to grant Accessibility would not have helped.
    """
    guidance = {item.permission: item for item in permission_guidance(macos(False, False, False))}
    automation = guidance[MACOS_AUTOMATION]
    assert "window enumeration" in automation.why()
    assert "window activation" in automation.why()
    assert "Automation" in automation.where

    accessibility = guidance[MACOS_ACCESSIBILITY]
    assert "keyboard input" in accessibility.why()
    assert "window enumeration" not in accessibility.why()


def test_each_permission_says_what_it_blocks_and_where_to_grant_it() -> None:
    guidance = {item.permission: item for item in permission_guidance(macos(False, False))}

    accessibility = guidance[MACOS_ACCESSIBILITY]
    assert accessibility.state is CapabilityState.DENIED
    assert "keyboard input" in accessibility.why()
    assert "Accessibility" in accessibility.where
    assert accessibility.requires_restart
    assert "quit and reopen" in accessibility.instructions()

    monitoring = guidance[MACOS_INPUT_MONITORING]
    assert "global hotkey" in monitoring.why()
    assert "Input Monitoring" in monitoring.where


def test_holding_one_permission_does_not_satisfy_the_others() -> None:
    outstanding = outstanding_permissions(macos(True, False, automation=True))
    assert [item.permission for item in outstanding] == [MACOS_INPUT_MONITORING]

    outstanding = outstanding_permissions(macos(True, True, automation=False))
    assert [item.permission for item in outstanding] == [MACOS_AUTOMATION]


def test_a_granted_permission_is_not_outstanding() -> None:
    assert outstanding_permissions(macos(True, True, automation=True)) == ()


def test_an_unverifiable_permission_says_so_rather_than_denied() -> None:
    guidance = permission_guidance(macos(None, None))
    for item in guidance:
        assert item.state is CapabilityState.UNKNOWN
        assert item.state_word == "could not be checked"
        assert "cannot check the permission automatically" in item.instructions()


def test_platforms_without_permission_gates_have_no_guidance() -> None:
    for report in (
        describe_host(PlatformName.WINDOWS, DisplayServer.WINDOWS, env={}),
        describe_host(PlatformName.LINUX, DisplayServer.X11, env={"DISPLAY": ":0"}),
    ):
        assert permission_guidance(report) == ()


def test_the_first_run_summary_names_the_storage_locations() -> None:
    summary = first_run_summary(
        macos(False, False), profile_directory="/data/profiles", log_directory="/data/logs"
    )
    assert "macos" in summary.platform_line
    assert summary.needs_permissions
    assert summary.profile_directory == "/data/profiles"
    assert summary.log_directory == "/data/logs"


def test_wayland_notes_reach_the_first_run_summary() -> None:
    summary = first_run_summary(describe_host(PlatformName.LINUX, DisplayServer.WAYLAND, env={}))
    assert not summary.needs_permissions, "Wayland restricts by design, not by permission"
    assert any("Wayland" in note for note in summary.notes)


# -- the dialog (Qt) ------------------------------------------------------
pyside = pytest.importorskip("PySide6", reason="GUI extra not installed")

from human_input_automation.ui.onboarding import OnboardingDialog  # noqa: E402


@pytest.mark.usefixtures("qt_app")
def test_the_dialog_lists_each_permission_separately() -> None:
    dialog = OnboardingDialog(first_run_summary(macos(False, False, automation=False)))
    labels = [widget.text() for widget in dialog.findChildren(pyside.QtWidgets.QLabel)]
    joined = "\n".join(labels)
    assert MACOS_ACCESSIBILITY in joined
    assert MACOS_INPUT_MONITORING in joined
    assert "System Settings > Privacy & Security > Accessibility" in joined
    assert "Nothing runs automatically" in joined
    dialog.close()


@pytest.mark.usefixtures("qt_app")
def test_the_dialog_is_fine_with_nothing_outstanding() -> None:
    dialog = OnboardingDialog(first_run_summary(macos(True, True, automation=True)))
    assert dialog.summary.permissions == ()
    dialog.close()


@pytest.mark.usefixtures("qt_app")
def test_first_run_shows_the_briefing_once(tmp_path: Path) -> None:
    """It appears on the first launch and not on the next one."""
    from human_input_automation.paths import ApplicationPaths
    from tests.test_ui_profiles import Harness  # reuse the wired-up window

    paths = ApplicationPaths(
        data=tmp_path / "data", profiles=tmp_path / "data" / "profiles", logs=tmp_path / "logs"
    )
    paths.ensure()

    first = Harness(tmp_path)
    first.window._paths = paths
    first.window._maybe_show_onboarding()
    assert first.window.last_onboarding is not None
    assert not paths.is_first_run, "the first run must be recorded"
    first.close()

    second = Harness(tmp_path)
    second.window._paths = paths
    second.window.last_onboarding = None
    second.window._maybe_show_onboarding()
    assert second.window.last_onboarding is None, "the briefing must not repeat"
    second.close()
