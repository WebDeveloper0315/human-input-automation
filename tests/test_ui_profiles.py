"""Profile management in the desktop UI, on the offscreen Qt platform."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI extra not installed")

from human_input_automation.adapters.hotkeys import HotkeySupport
from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.profiles import (
    ProfileRepository,
    ProfileService,
    ProfileState,
)
from human_input_automation.application.service import AutomationService
from human_input_automation.core.actions import KeyPress, TypeText, Wait
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)
from human_input_automation.ui.main_window import MainWindow
from human_input_automation.ui.models import UiState, UnsavedChoice

from .fakes import FakeHotkey, FakeKeyboard, FakeMouse, FakeWindows, make_target

pytestmark = pytest.mark.usefixtures("qt_app")

INSTANT_TIMING = {
    "char_delay_ms": 0.0,
    "char_jitter_ms": 0.0,
    "min_delay_ms": 0.0,
    "max_delay_ms": 0.0,
    "action_delay_ms": 0.0,
    "action_jitter_ms": 0.0,
}


class Harness:
    def __init__(self, tmp_path: Path, windows: FakeWindows | None = None) -> None:
        self.keyboard = FakeKeyboard()
        self.windows = windows or FakeWindows(windows=[make_target()])
        adapters = AdapterSet(
            keyboard=self.keyboard,
            mouse=FakeMouse(),
            windows=self.windows,
            discovery=self.windows,
            clock=SystemClock(),
            host=PlatformReport(
                platform=PlatformName.LINUX,
                display_server=DisplayServer.X11,
                capabilities=WindowCapabilities.full(),
            ),
            hotkey=FakeHotkey(),
            hotkey_support=HotkeySupport(True, "ok"),
        )
        self.profiles = ProfileService(ProfileRepository(tmp_path / "profiles"))
        self.service = AutomationService(
            adapters, countdown_tick_seconds=0.02, profiles=self.profiles
        )
        self.window = MainWindow(self.service, show_dialogs=False)
        self.window.timing_panel.set_values(INSTANT_TIMING)
        self.window.controls.countdown_spin.setValue(0)
        self.window._set_dirty(False)

    def compose(self, *actions: Any) -> None:
        self.window.target_panel.table.selectRow(0)
        self.window.action_editor.set_actions(list(actions) or [TypeText(text="hi")])

    def close(self) -> None:
        self.window.unsaved_prompt = lambda: UnsavedChoice.DISCARD
        self.window.close()

    @property
    def log(self) -> str:
        return "\n".join(self.window.run_log.lines)


@pytest.fixture
def harness(tmp_path: Path) -> Any:
    built: list[Harness] = []

    def _make(**kwargs: Any) -> Harness:
        instance = Harness(tmp_path, **kwargs)
        built.append(instance)
        return instance

    yield _make
    for instance in built:
        instance.close()


# -- save / load ----------------------------------------------------------
def test_save_as_creates_a_profile_from_the_current_editors(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="hello"), KeyPress(key="enter"))
    app.window.save_profile_as("Greeting")

    assert app.window.profile is not None
    assert app.window.profile.name == "Greeting"
    assert not app.window.is_dirty

    stored = app.profiles.list()
    assert [summary.name for summary in stored] == ["Greeting"]
    reloaded = app.profiles.load(stored[0].id)
    assert reloaded.plan is not None
    assert [type(action) for action in reloaded.plan.actions] == [TypeText, KeyPress]


def test_saving_persists_timing_and_seed(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.timing_panel.set_values({"char_delay_ms": 66.0, "word_pause_ms": 111.0})
    app.window.timing_panel.seed_check.setChecked(True)
    app.window.timing_panel.seed_spin.setValue(4242)
    app.window.save_profile_as("Timed")

    stored = app.profiles.load(app.window.profile.id)
    assert stored.plan is not None
    assert stored.plan.timing.char_delay_ms == 66
    assert stored.plan.timing.word_pause_ms == 111
    assert stored.plan.options.seed == 4242


def test_saving_persists_the_typing_style(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.timing_panel.mistakes_check.setChecked(True)
    app.window.timing_panel.mistakes_spin.setValue(6.0)
    app.window.save_profile_as("Human")

    stored = app.profiles.load(app.window.profile.id)
    assert stored.plan is not None
    assert stored.plan.typing.typo_rate == pytest.approx(0.06)

    app.window.new_profile()
    assert app.window.timing_panel.typing_style().is_exact

    app.window.load_profile(stored.id)
    assert app.window.timing_panel.mistakes_check.isChecked()
    assert app.window.timing_panel.typing_style().typo_rate == pytest.approx(0.06)


def test_loading_restores_actions_timing_and_seed(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="restored"), Wait(duration_ms=250))
    app.window.timing_panel.seed_check.setChecked(True)
    app.window.timing_panel.seed_spin.setValue(77)
    app.window.save_profile_as("Restorable")
    profile_id = app.window.profile.id

    app.window.new_profile()
    assert app.window.action_editor.plan_actions == ()

    app.window.load_profile(profile_id)
    actions = app.window.action_editor.plan_actions
    assert [type(action) for action in actions] == [TypeText, Wait]
    assert app.window.timing_panel.seed == 77
    assert not app.window.is_dirty
    assert "Profile loaded: Restorable" in app.log


def test_save_updates_the_existing_profile_rather_than_adding_one(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Once")
    app.window.action_editor.add_action(Wait(duration_ms=5))
    app.window.save_profile()

    assert len(app.profiles.list()) == 1
    stored = app.profiles.load(app.window.profile.id)
    assert stored.plan is not None and len(stored.plan.actions) == 2


def test_save_without_a_profile_creates_one(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile()  # no current profile: behaves as Save As
    assert app.window.profile is not None
    assert len(app.profiles.list()) == 1


def test_a_failed_save_keeps_the_unsaved_flag_and_reports_it(harness: Any) -> None:
    app = harness()
    app.compose()

    def explode(profile: Any) -> Any:
        from human_input_automation.application.profiles import ProfileStorageError

        raise ProfileStorageError("disk full")

    app.profiles.save = explode
    app.window.save_profile_as("Doomed")

    assert app.window.is_dirty, "a failed save must not claim success"
    assert app.window.last_message is not None
    assert "disk full" in app.window.last_message[1]


# -- duplicate / delete ---------------------------------------------------
def test_duplicate_creates_a_second_profile(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Original")
    original_id = app.window.profile.id

    app.window.duplicate_profile()
    names = sorted(summary.name for summary in app.profiles.list())
    assert names == ["Original", "Original (copy)"]
    assert app.window.profile.id != original_id


def test_delete_removes_the_profile_and_clears_the_editor_state(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Doomed")
    app.window.delete_profile()

    assert app.profiles.list() == ()
    assert app.window.profile is None
    assert not app.window.is_dirty


def test_deleting_without_a_saved_profile_explains_itself(harness: Any) -> None:
    app = harness()
    app.window.delete_profile()
    assert app.window.last_message is not None
    assert app.window.last_message[0] == "Nothing to delete"


# -- unsaved changes ------------------------------------------------------
def test_editing_marks_the_profile_unsaved(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Clean")
    assert not app.window.is_dirty

    app.window.action_editor.add_action(Wait(duration_ms=1))
    assert app.window.is_dirty
    assert app.window.profile_panel.name_label.text().endswith("*")


def test_timing_and_target_changes_also_mark_unsaved(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Clean")

    app.window.timing_panel.set_values({"char_delay_ms": 90.0})
    assert app.window.is_dirty

    app.window.save_profile()
    app.window.target_panel.clear_selection()
    assert app.window.is_dirty


def test_cancelling_the_prompt_keeps_the_current_profile(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="first"))
    app.window.save_profile_as("First")
    first_id = app.window.profile.id

    app.compose(TypeText(text="second"))
    app.window.save_profile_as("Second")
    app.window.action_editor.add_action(Wait(duration_ms=1))

    app.window.unsaved_prompt = lambda: UnsavedChoice.CANCEL
    app.window.load_profile(first_id)

    assert app.window.profile.name == "Second"
    assert app.window.is_dirty, "cancelling must not discard the changes"


def test_discarding_loads_the_other_profile(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="first"))
    app.window.save_profile_as("First")
    first_id = app.window.profile.id
    app.window.action_editor.add_action(Wait(duration_ms=1))

    app.window.unsaved_prompt = lambda: UnsavedChoice.DISCARD
    app.window.load_profile(first_id)
    assert not app.window.is_dirty
    assert len(app.window.action_editor.plan_actions) == 1


def test_choosing_save_stores_before_switching(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="one"))
    app.window.save_profile_as("One")
    first_id = app.window.profile.id
    app.window.action_editor.add_action(Wait(duration_ms=3))

    app.window.unsaved_prompt = lambda: UnsavedChoice.SAVE
    app.window.load_profile(first_id)

    stored = app.profiles.load(first_id)
    assert stored.plan is not None and len(stored.plan.actions) == 2


def test_without_a_prompt_hook_headless_cancels_rather_than_losing_work(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Kept")
    profile_id = app.window.profile.id
    app.window.action_editor.add_action(Wait(duration_ms=1))

    app.window.unsaved_prompt = None
    app.window.load_profile(profile_id)
    assert app.window.is_dirty


def test_new_profile_clears_the_editors(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="x"))
    app.window.save_profile_as("Something")
    app.window.new_profile()

    assert app.window.profile is None
    assert app.window.action_editor.plan_actions == ()
    assert not app.window.is_dirty


# -- target resolution ----------------------------------------------------
def test_a_resolved_profile_selects_its_window_and_can_run(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Resolvable")
    app.window.resolve_profile_target()

    loaded = app.window.loaded_profile
    assert loaded is not None and loaded.state is ProfileState.TARGET_RESOLVED
    assert app.window.target_panel.selected_target is not None
    assert app.window.controls.start_button.isEnabled()
    assert "OK Target resolved" in app.window.profile_panel.status_label.text()


def test_an_unresolved_profile_loads_but_cannot_start(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Gone")
    app.windows.windows = []  # the application closed

    app.window.resolve_profile_target()
    loaded = app.window.loaded_profile
    assert loaded is not None and loaded.state is ProfileState.TARGET_UNRESOLVED
    assert app.window.target_panel.selected_target is None
    assert not app.window.controls.start_button.isEnabled()
    assert "Target not found" in app.window.profile_panel.status_label.text()


def test_an_ambiguous_profile_refuses_to_choose(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Ambiguous")
    app.windows.windows = [make_target("a", "One"), make_target("b", "Two")]

    app.window.resolve_profile_target()
    loaded = app.window.loaded_profile
    assert loaded is not None and loaded.state is ProfileState.TARGET_AMBIGUOUS
    assert app.window.target_panel.selected_target is None
    assert not app.window.controls.start_button.isEnabled()
    assert "Multiple matching windows" in app.window.profile_panel.status_label.text()


def test_a_capability_blocked_target_cannot_run(harness: Any) -> None:
    blocked = make_target(capabilities=WindowCapabilities(can_enumerate=True, can_activate=True))
    app = harness(windows=FakeWindows(windows=[blocked]))
    app.window.target_panel.table.selectRow(0)
    app.window.action_editor.set_actions([TypeText(text="hi")])
    app.window.save_profile_as("Blocked")

    app.window.resolve_profile_target()
    loaded = app.window.loaded_profile
    assert loaded is not None and loaded.state is ProfileState.TARGET_CAPABILITY_BLOCKED
    assert not app.window.controls.start_button.isEnabled()


def test_loading_a_profile_never_starts_a_run(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Inert")
    profile_id = app.window.profile.id
    app.window.new_profile()

    app.window.load_profile(profile_id)
    assert app.keyboard.calls == [], "loading a profile must not send input"
    assert app.window.state is UiState.IDLE
    assert not app.service.is_running


# -- import / export ------------------------------------------------------
def test_export_then_import_through_the_window(harness: Any, tmp_path: Path) -> None:
    app = harness()
    app.compose(TypeText(text="exported"))
    app.window.save_profile_as("Exportable")

    destination = tmp_path / "exported.json"
    app.window.export_profile(str(destination))
    assert destination.is_file()

    app.window.new_profile()
    app.window.import_profile(str(destination))

    assert app.window.profile is not None and app.window.profile.name == "Exportable"
    assert app.keyboard.calls == [], "importing must not send input"
    assert len(app.profiles.list()) == 2


def test_importing_a_malformed_file_reports_a_readable_error(
    harness: Any, tmp_path: Path
) -> None:
    app = harness()
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema": 99}', encoding="utf-8")

    app.window.import_profile(str(broken))
    assert app.window.last_message is not None
    assert app.window.last_message[0] == "Could not import the profile"
    assert "Unsupported profile schema version: 99" in app.window.last_message[1]
    assert app.profiles.list() == ()


def test_exporting_without_a_saved_profile_explains_itself(harness: Any) -> None:
    app = harness()
    app.window.export_profile("/tmp/never-written.json")
    assert app.window.last_message is not None
    assert app.window.last_message[0] == "Nothing to export"


# -- run integration ------------------------------------------------------
def test_a_loaded_profile_can_be_dry_run_without_touching_the_adapters(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="preview"))
    app.window.save_profile_as("Previewable")
    profile_id = app.window.profile.id
    app.window.new_profile()
    app.window.load_profile(profile_id)

    app.window.dry_run()
    assert app.keyboard.calls == []
    assert "NO INPUT WILL BE SENT" in app.window.dry_run_panel.header_label.text()
    assert app.window.dry_run_panel.action_lines


def test_a_loaded_profile_runs_through_the_normal_start_path(harness: Any, pump: Any) -> None:
    app = harness()
    app.compose(TypeText(text="typed"))
    app.window.save_profile_as("Runnable")
    profile_id = app.window.profile.id
    app.window.new_profile()
    app.window.load_profile(profile_id)

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.COMPLETED)
    assert app.keyboard.typed == "typed"


def test_profiles_are_locked_while_a_run_is_in_flight(harness: Any, pump: Any) -> None:
    app = harness()
    app.compose(Wait(duration_ms=5_000))
    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.RUNNING)
    assert not app.window.profile_panel.save_button.isEnabled()
    assert not app.window.profile_panel.combo.isEnabled()

    app.window.emergency_stop()
    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert app.window.profile_panel.save_button.isEnabled()


# -- picker ---------------------------------------------------------------
def test_the_picker_lists_saved_profiles(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Alpha")
    app.window.new_profile()
    app.compose()
    app.window.save_profile_as("Beta")

    combo = app.window.profile_panel.combo
    labels = [combo.itemText(index) for index in range(combo.count())]
    assert labels[0] == "(unsaved profile)"
    assert "Alpha" in labels and "Beta" in labels


def test_selecting_a_profile_in_the_picker_loads_it(harness: Any) -> None:
    app = harness()
    app.compose(TypeText(text="picked"))
    app.window.save_profile_as("Pickable")
    app.window.new_profile()

    panel = app.window.profile_panel
    index = next(
        i for i in range(panel.combo.count()) if panel.combo.itemText(i) == "Pickable"
    )
    panel.combo.setCurrentIndex(index)

    assert app.window.profile is not None and app.window.profile.name == "Pickable"
    assert len(app.window.action_editor.plan_actions) == 1


def test_the_window_title_shows_the_profile_and_unsaved_state(harness: Any) -> None:
    app = harness()
    app.compose()
    app.window.save_profile_as("Titled")
    assert app.window.windowTitle().endswith("Titled")

    app.window.action_editor.add_action(Wait(duration_ms=1))
    assert app.window.windowTitle().endswith("Titled *")
