"""Widget tests, run on the offscreen Qt platform (no desktop session)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI extra not installed")

from PySide6.QtWidgets import QDialog

from human_input_automation.application.service import TargetListing
from human_input_automation.core.actions import KeyPress, TypeText, Wait
from human_input_automation.core.keys import Key
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile
from human_input_automation.ui.action_editor import ActionDialog, ActionEditor
from human_input_automation.ui.capability_banner import CapabilityBanner
from human_input_automation.ui.dry_run_panel import DryRunPanel
from human_input_automation.ui.models import (
    DryRunView,
    UiState,
    capability_banner,
    controls_for,
)
from human_input_automation.ui.run_controls import RunControls
from human_input_automation.ui.run_log import RunLog
from human_input_automation.ui.target_panel import TargetPanel
from human_input_automation.ui.timing_panel import TimingPanel

from .fakes import make_target

pytestmark = pytest.mark.usefixtures("qt_app")


# -- capability banner ----------------------------------------------------
def test_banner_renders_the_model_text() -> None:
    banner = CapabilityBanner()
    report = PlatformReport(
        platform=PlatformName.LINUX,
        display_server=DisplayServer.WAYLAND,
        capabilities=WindowCapabilities(can_send_synthetic_input=True),
        warnings=("Wayland restricts window control",),
    )
    banner.show_model(capability_banner(report))
    assert "LIMITED" in banner.headline_label.text()
    assert "Wayland restricts window control" in banner.details_label.text()
    assert banner.details_label.isVisibleTo(banner)


def test_banner_shows_denied_without_colour_only_meaning() -> None:
    banner = CapabilityBanner()
    report = PlatformReport(
        platform=PlatformName.MACOS,
        display_server=DisplayServer.QUARTZ,
        capabilities=WindowCapabilities(requires_permission="Accessibility"),
        missing_permissions=("Accessibility",),
    )
    banner.show_model(capability_banner(report))
    assert "DENIED" in banner.headline_label.text()


# -- target panel ---------------------------------------------------------
def cell(panel: TargetPanel, row: int, column: int) -> str:
    item = panel.table.item(row, column)
    assert item is not None
    return item.text()


def test_target_panel_lists_windows_and_reports_selection() -> None:
    panel = TargetPanel()
    selected: list[Any] = []
    panel.target_changed.connect(selected.append)

    panel.set_listing(TargetListing((make_target("h1", "Alpha"), make_target("h2", "Beta"))))
    assert panel.table.rowCount() == 2
    assert cell(panel, 0, 0) == "Alpha"
    assert cell(panel, 0, 2) == "4242"

    panel.table.selectRow(1)
    assert panel.selected_target is not None
    assert panel.selected_target.handle == "h2"
    assert selected[-1].handle == "h2"
    assert "Beta" in panel.active_label.text()


def test_target_panel_starts_with_no_selection() -> None:
    panel = TargetPanel()
    panel.set_listing(TargetListing((make_target(),)))
    assert panel.selected_target is None
    assert "none selected" in panel.active_label.text()


def test_target_panel_shows_the_reason_when_enumeration_is_unavailable() -> None:
    panel = TargetPanel()
    panel.set_listing(TargetListing((), "Wayland does not let applications enumerate windows"))
    assert panel.table.rowCount() == 0
    assert panel.reason_label.isVisibleTo(panel)
    assert "Wayland" in panel.reason_label.text()


def test_target_panel_keeps_the_selection_across_a_refresh_by_handle() -> None:
    panel = TargetPanel()
    panel.set_listing(TargetListing((make_target("h1", "Alpha"), make_target("h2", "Beta"))))
    panel.table.selectRow(1)
    # The title changed, the handle did not: the selection must survive.
    panel.set_listing(
        TargetListing((make_target("h1", "Alpha"), make_target("h2", "Beta renamed")))
    )
    assert panel.selected_target is not None
    assert panel.selected_target.handle == "h2"
    assert "Beta renamed" in panel.active_label.text()


def test_target_panel_clears_selection_when_the_window_disappears() -> None:
    panel = TargetPanel()
    panel.set_listing(TargetListing((make_target("h1"), make_target("h2"))))
    panel.table.selectRow(1)
    panel.set_listing(TargetListing((make_target("h1"),)))
    assert panel.selected_target is None


def test_target_panel_marks_an_invalid_target() -> None:
    panel = TargetPanel()
    panel.set_listing(TargetListing((make_target(),)))
    panel.table.selectRow(0)
    panel.set_target_available(False)
    assert "UNAVAILABLE" in panel.active_label.text()


def test_target_panel_locks_during_a_run() -> None:
    panel = TargetPanel()
    panel.set_locked(True)
    assert not panel.table.isEnabled() and not panel.refresh_button.isEnabled()
    panel.set_locked(False)
    assert panel.table.isEnabled()


# -- action editor --------------------------------------------------------
def test_action_editor_add_edit_delete_and_reorder() -> None:
    editor = ActionEditor()
    changes: list[int] = []
    editor.actions_changed.connect(lambda: changes.append(1))

    editor.add_action(TypeText(text="one"))
    editor.add_action(KeyPress(key=Key.ENTER))
    assert [type(a) for a in editor.plan_actions] == [TypeText, KeyPress]
    assert editor.list.item(0).text() == "1. type 'one' (3 chars)"

    editor.select(0)
    editor.replace_action(0, TypeText(text="edited"))
    assert editor.plan_actions[0] == TypeText(text="edited")

    editor.select(0)
    editor.move_selected(1)
    assert [type(a) for a in editor.plan_actions] == [KeyPress, TypeText]
    assert editor.selected_index == 1

    editor.select(0)
    editor.delete_selected()
    assert [type(a) for a in editor.plan_actions] == [TypeText]
    assert changes


def test_action_editor_ignores_out_of_range_moves() -> None:
    editor = ActionEditor()
    editor.set_actions([TypeText(text="a"), TypeText(text="b")])
    editor.select(0)
    editor.move_selected(-1)
    assert editor.plan_actions[0] == TypeText(text="a")
    editor.select(1)
    editor.move_selected(1)
    assert editor.plan_actions[1] == TypeText(text="b")


def test_action_editor_delete_without_selection_is_safe() -> None:
    editor = ActionEditor()
    editor.delete_selected()
    assert editor.plan_actions == ()


def test_action_editor_locks_during_a_run() -> None:
    editor = ActionEditor()
    editor.set_locked(True)
    assert not editor.add_button.isEnabled() and not editor.list.isEnabled()


# -- action dialog --------------------------------------------------------
def test_action_dialog_builds_the_selected_action() -> None:
    dialog = ActionDialog(kind="type_text")
    dialog.set_values({"text": "hello"})
    action = dialog.try_build()
    assert action == TypeText(text="hello")


def test_action_dialog_shows_validation_errors_and_refuses_to_close() -> None:
    dialog = ActionDialog(kind="type_text")
    dialog.set_values({"text": ""})
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "must not be empty" in dialog.error_text


def test_action_dialog_reports_unknown_keys_readably() -> None:
    dialog = ActionDialog(kind="key_press")
    dialog.set_values({"key": "not-a-key", "count": 1})
    assert dialog.try_build() is None
    assert "unknown key" in dialog.error_text


def test_action_dialog_prefills_an_existing_action_and_locks_its_type() -> None:
    dialog = ActionDialog(action=Wait(duration_ms=250, delay_after_ms=90))
    assert dialog.kind == "wait"
    assert not dialog.kind_combo.isEnabled()
    assert dialog.delay_after_ms == 90
    assert dialog.try_build() == Wait(duration_ms=250, delay_after_ms=90)


def test_action_dialog_delay_defaults_to_the_timing_profile() -> None:
    dialog = ActionDialog(kind="wait")
    assert dialog.delay_after_ms is None
    action = dialog.try_build()
    assert action is not None and action.delay_after_ms is None


def test_action_dialog_switches_fields_when_the_kind_changes() -> None:
    dialog = ActionDialog(kind="type_text")
    index = dialog.kind_combo.findData("mouse_click")
    dialog.kind_combo.setCurrentIndex(index)
    assert dialog.kind == "mouse_click"
    assert set(dialog.values()) == {"button", "use_position", "x", "y", "count"}


# -- timing panel ---------------------------------------------------------
def test_timing_panel_builds_a_profile_from_its_fields() -> None:
    panel = TimingPanel()
    panel.set_values({"char_delay_ms": 55, "word_pause_ms": 120})
    profile = panel.profile()
    assert profile is not None
    assert profile.char_delay_ms == 55 and profile.word_pause_ms == 120


def test_timing_panel_reports_invalid_bounds_instead_of_clamping() -> None:
    panel = TimingPanel()
    panel.set_values({"min_delay_ms": 400, "max_delay_ms": 100})
    assert panel.profile() is None
    assert "min_delay_ms" in panel.error_text
    assert panel.error_label.isVisibleTo(panel)
    assert "Preview unavailable" in panel.preview_label.text()


def test_timing_panel_preview_uses_the_timing_service_bounds() -> None:
    panel = TimingPanel()
    panel.set_values(
        {"char_delay_ms": 50, "char_jitter_ms": 500, "min_delay_ms": 10, "max_delay_ms": 60}
    )
    panel.refresh_preview()
    text = panel.preview_label.text()
    assert text.startswith("Next delays:")
    values = [int(part.strip()) for part in text.split(":")[1].split("ms") if part.strip()]
    assert all(10 <= value <= 60 for value in values)


def test_timing_panel_seed_is_optional_and_makes_the_preview_stable() -> None:
    panel = TimingPanel()
    seed = panel.seed
    assert seed is None
    panel.seed_check.setChecked(True)
    panel.seed_spin.setValue(99)
    seed = panel.seed
    assert seed == 99
    panel.refresh_preview()
    first = panel.preview_label.text()
    panel.refresh_preview()
    assert panel.preview_label.text() == first


def test_timing_panel_locks_during_a_run() -> None:
    panel = TimingPanel()
    panel.set_locked(True)
    assert not panel.preview_button.isEnabled()
    panel.set_locked(False)
    assert panel.preview_button.isEnabled()


def test_timing_panel_round_trips_a_profile() -> None:
    from human_input_automation.ui.models import timing_to_values

    panel = TimingPanel()
    profile = TimingProfile(char_delay_ms=42, action_delay_ms=99)
    panel.set_values(timing_to_values(profile))
    assert panel.profile() == profile


# -- run controls ---------------------------------------------------------
def test_run_controls_apply_state() -> None:
    controls = RunControls()
    controls.apply_state(controls_for(UiState.RUNNING))
    assert not controls.start_button.isEnabled()
    assert controls.pause_button.isEnabled()
    assert controls.stop_button.isEnabled()
    assert not controls.dry_run_button.isEnabled()
    assert "Running" in controls.status_label.text()


@pytest.mark.parametrize("state", list(UiState))
def test_emergency_button_is_never_disabled(state: UiState) -> None:
    controls = RunControls()
    controls.apply_state(controls_for(state))
    assert controls.emergency_button.isEnabled()


def test_run_controls_emit_signals() -> None:
    controls = RunControls()
    fired: list[str] = []
    controls.start_requested.connect(lambda: fired.append("start"))
    controls.pause_requested.connect(lambda: fired.append("pause"))
    controls.resume_requested.connect(lambda: fired.append("resume"))
    controls.stop_requested.connect(lambda: fired.append("stop"))
    controls.dry_run_requested.connect(lambda: fired.append("dry"))
    controls.emergency_requested.connect(lambda: fired.append("emergency"))
    for button in (
        controls.start_button,
        controls.pause_button,
        controls.resume_button,
        controls.stop_button,
        controls.dry_run_button,
        controls.emergency_button,
    ):
        button.setEnabled(True)
        button.click()
    assert fired == ["start", "pause", "resume", "stop", "dry", "emergency"]


def test_run_controls_countdown_display() -> None:
    controls = RunControls()
    assert controls.countdown_seconds == 3
    controls.show_countdown("Starting in 2...")
    assert controls.countdown_label.text() == "Starting in 2..."
    controls.show_countdown("")
    assert not controls.countdown_label.isVisibleTo(controls)


def test_emergency_button_has_an_accessible_name_and_shortcut() -> None:
    controls = RunControls()
    assert controls.emergency_button.accessibleName() == "Emergency stop"
    assert controls.emergency_button.shortcut().toString() == "Ctrl+."


# -- log and dry-run panels ----------------------------------------------
def test_run_log_appends_and_clears() -> None:
    log = RunLog()
    log.append_line("first")
    log.append_line("second")
    assert log.lines == ["first", "second"]
    log.clear_button.click()
    assert log.lines == []


def test_dry_run_panel_renders_a_view() -> None:
    panel = DryRunPanel()
    panel.show_view(
        DryRunView(
            target_text="Target: Editor",
            estimated_duration="Estimated duration: 1.2 s",
            lines=("1. type 'hi'", "2. press enter"),
            result="Completed 2 action(s).",
            warnings=("focus cannot be verified",),
        )
    )
    assert "NO INPUT WILL BE SENT" in panel.header_label.text()
    assert panel.action_lines == ["1. type 'hi'", "2. press enter"]
    assert "1.2 s" in panel.duration_label.text()
    assert "focus cannot be verified" in panel.result_label.text()
