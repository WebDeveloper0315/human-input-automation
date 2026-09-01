"""Main-window integration: the real service and engine, fake adapters."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI extra not installed")

from human_input_automation.adapters.hotkeys import HotkeySupport
from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.adapters.system_clock import SystemClock
from human_input_automation.application.service import AutomationService
from human_input_automation.core.actions import KeyDown, TypeText, Wait
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    WindowCapabilities,
)
from human_input_automation.ui.main_window import MainWindow
from human_input_automation.ui.models import UiState

from .fakes import FakeHotkey, FakeKeyboard, FakeMouse, FakeWindows, make_target

pytestmark = pytest.mark.usefixtures("qt_app")

INSTANT_TIMING: dict[str, float] = {
    "char_delay_ms": 0,
    "char_jitter_ms": 0,
    "min_delay_ms": 0,
    "max_delay_ms": 0,
    "action_delay_ms": 0,
    "action_jitter_ms": 0,
    "mouse_move_duration_ms": 0,
    "mouse_move_jitter_ms": 0,
}


class Harness:
    """A main window wired to fake adapters, ready to drive from a test."""

    def __init__(
        self,
        *,
        windows: FakeWindows | None = None,
        host: PlatformReport | None = None,
        hotkey: FakeHotkey | None = None,
        hotkey_support: HotkeySupport | None = None,
    ) -> None:
        self.keyboard = FakeKeyboard()
        self.mouse = FakeMouse()
        self.windows = windows or FakeWindows(windows=[make_target()])
        self.hotkey = hotkey or FakeHotkey()
        adapters = AdapterSet(
            keyboard=self.keyboard,
            mouse=self.mouse,
            windows=self.windows,
            discovery=self.windows,
            clock=SystemClock(),
            host=host
            or PlatformReport(
                platform=PlatformName.LINUX,
                display_server=DisplayServer.X11,
                capabilities=WindowCapabilities.full(),
            ),
            hotkey=self.hotkey,
            hotkey_support=hotkey_support or HotkeySupport(True, "Global hotkey supported."),
        )
        self.service = AutomationService(adapters, countdown_tick_seconds=0.02)
        self.window = MainWindow(self.service, show_dialogs=False)
        self.window.timing_panel.set_values(INSTANT_TIMING)
        self.window.controls.countdown_spin.setValue(0)

    def select_first_target(self) -> None:
        self.window.target_panel.table.selectRow(0)

    def with_actions(self, *actions: Any) -> None:
        self.window.action_editor.set_actions(list(actions))

    def close(self) -> None:
        self.window.close()

    @property
    def log(self) -> str:
        return "\n".join(self.window.run_log.lines)


@pytest.fixture
def harness() -> Any:
    built: list[Harness] = []

    def _make(**kwargs: Any) -> Harness:
        harness = Harness(**kwargs)
        built.append(harness)
        return harness

    yield _make
    for harness in built:
        harness.close()


# -- readiness ------------------------------------------------------------
def test_start_is_disabled_until_a_target_and_actions_exist(harness: Any) -> None:
    app = harness()
    assert not app.window.controls.start_button.isEnabled()

    app.select_first_target()
    assert not app.window.controls.start_button.isEnabled()

    app.with_actions(TypeText(text="hi"))
    assert app.window.controls.start_button.isEnabled()


def test_the_active_target_is_shown_and_logged(harness: Any) -> None:
    app = harness()
    app.select_first_target()
    assert "Test Window" in app.window.target_panel.active_label.text()
    assert "Target selected" in app.log


def test_refresh_reports_why_no_windows_are_listed(harness: Any) -> None:
    app = harness(
        host=PlatformReport(
            platform=PlatformName.LINUX,
            display_server=DisplayServer.WAYLAND,
            capabilities=WindowCapabilities(can_send_synthetic_input=True),
        )
    )
    app.window.refresh_targets()
    assert "Wayland" in app.window.target_panel.reason_label.text()
    assert not app.window.controls.start_button.isEnabled()


# -- run lifecycle --------------------------------------------------------
def test_a_full_run_types_through_the_worker_and_returns_to_an_idle_like_state(
    harness: Any, pump: Any
) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="hi"))

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.COMPLETED)

    assert app.keyboard.typed == "hi"
    assert app.windows.calls[0] == "activate:win-1"
    assert "Run started" in app.log and "Run completed" in app.log
    assert app.window.controls.start_button.isEnabled()
    assert app.window.action_editor.list.isEnabled()


def test_editing_is_locked_while_a_run_is_in_flight(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(Wait(duration_ms=5_000))

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.RUNNING)
    assert not app.window.action_editor.list.isEnabled()
    assert not app.window.target_panel.table.isEnabled()
    assert not app.window.controls.start_button.isEnabled()
    assert app.window.controls.emergency_button.isEnabled()

    app.window.emergency_stop()
    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert app.window.action_editor.list.isEnabled()


def test_pause_and_resume_round_trip(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(Wait(duration_ms=300), TypeText(text="done"))

    app.window.start_run()
    app.window.pause_run()
    assert pump(lambda: app.window.state is UiState.PAUSED)
    assert app.keyboard.typed == ""
    assert app.window.controls.resume_button.isEnabled()
    assert not app.window.controls.pause_button.isEnabled()

    app.window.resume_run()
    assert pump(lambda: app.window.state is UiState.COMPLETED)
    assert app.keyboard.typed == "done"
    assert "Paused before action" in app.log and "Resumed at action" in app.log


def test_stop_ends_a_run_early(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(Wait(duration_ms=10_000), TypeText(text="unreachable"))

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.RUNNING)
    app.window.stop_run()
    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert app.keyboard.typed == ""
    assert "Automation stopped by user." in app.log


# -- countdown ------------------------------------------------------------
def test_countdown_runs_before_the_target_is_touched(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="hi"))
    app.window.controls.countdown_spin.setValue(1)

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.COUNTDOWN)
    assert app.windows.calls == [], "the target must not be activated during the countdown"
    assert "Starting in" in app.window.controls.countdown_label.text()

    assert pump(lambda: app.window.state is UiState.COMPLETED, timeout=10.0)
    assert app.keyboard.typed == "hi"
    assert "Countdown started" in app.log


def test_stop_during_the_countdown_sends_no_input(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="never"))
    app.window.controls.countdown_spin.setValue(2)

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.COUNTDOWN)
    app.window.stop_run()

    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert app.keyboard.calls == []
    assert app.windows.calls == []
    assert "Countdown cancelled" in app.log


def test_emergency_stop_during_the_countdown(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="never"))
    app.window.controls.countdown_spin.setValue(2)

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.COUNTDOWN)
    app.window.controls.emergency_button.click()

    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert app.keyboard.calls == []
    assert "EMERGENCY STOP requested" in app.log


# -- emergency stop -------------------------------------------------------
def test_emergency_stop_during_a_long_wait_releases_held_keys(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(KeyDown(key="shift"), Wait(duration_ms=60_000), TypeText(text="never"))

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.RUNNING)
    app.window.controls.emergency_button.click()

    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert app.keyboard.calls == [("key_down", "shift"), ("key_up", "shift")]


def test_emergency_stop_while_paused(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(Wait(duration_ms=200), TypeText(text="never"))

    app.window.start_run()
    app.window.pause_run()
    assert pump(lambda: app.window.state is UiState.PAUSED)

    app.window.controls.emergency_button.click()
    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert app.keyboard.typed == ""


def test_the_emergency_button_updates_the_ui_without_waiting_for_the_worker(
    harness: Any, pump: Any
) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(Wait(duration_ms=30_000))

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.RUNNING)
    app.window.controls.emergency_button.click()
    # The state flips immediately, before the worker has reported anything.
    assert app.window.state in (UiState.STOPPING, UiState.STOPPED)
    assert pump(lambda: app.window.state is UiState.STOPPED)


# -- global hotkey --------------------------------------------------------
def test_the_global_hotkey_is_registered_and_only_stops(harness: Any, pump: Any) -> None:
    app = harness()
    assert app.hotkey.is_active
    assert "Global emergency-stop hotkey active" in app.log

    app.select_first_target()
    app.with_actions(Wait(duration_ms=30_000))
    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.RUNNING)

    app.hotkey.trigger()  # fires on the listener thread, like the real one
    assert pump(lambda: app.window.state is UiState.STOPPED)
    assert "global hotkey" in app.log


def test_an_unsupported_hotkey_is_reported_not_pretended(harness: Any) -> None:
    app = harness(
        hotkey=FakeHotkey(can_register=False),
        hotkey_support=HotkeySupport(False, "Wayland does not allow it"),
    )
    assert not app.hotkey.is_active
    assert "Global emergency hotkey unavailable" in app.log
    assert "Wayland does not allow it" in app.window.statusBar().currentMessage()
    assert app.window.controls.emergency_button.isEnabled()


# -- dry run --------------------------------------------------------------
def test_dry_run_shows_a_preview_and_sends_nothing(harness: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="hi"), Wait(duration_ms=250))

    app.window.dry_run()

    assert app.keyboard.calls == [] and app.mouse.calls == [] and app.windows.calls == []
    assert "NO INPUT WILL BE SENT" in app.window.dry_run_panel.header_label.text()
    assert app.window.dry_run_panel.action_lines[0].startswith("1. type 'hi'")
    assert "Estimated duration" in app.window.dry_run_panel.duration_label.text()
    assert "Test Window" in app.window.dry_run_panel.target_label.text()
    assert "no input was sent" in app.log


def test_dry_run_uses_the_same_plan_and_timing_as_a_real_run(harness: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="abc"))
    app.window.timing_panel.set_values({"char_delay_ms": 100, "char_jitter_ms": 0,
                                        "min_delay_ms": 0, "max_delay_ms": 200,
                                        "action_delay_ms": 0, "action_jitter_ms": 0})
    app.window.dry_run()
    # 3 characters at 100 ms each: the estimate comes from the real timing service.
    assert "0.3 s" in app.window.dry_run_panel.duration_label.text()


# -- error handling -------------------------------------------------------
def test_starting_without_a_target_explains_itself(harness: Any) -> None:
    app = harness()
    app.with_actions(TypeText(text="hi"))
    app.window.start_run()
    assert app.window.last_message is not None
    assert app.window.last_message[0] == "Target unavailable"
    assert app.keyboard.calls == []


def test_invalid_timing_blocks_the_run_with_a_readable_message(harness: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="hi"))
    app.window.timing_panel.set_values({"min_delay_ms": 500, "max_delay_ms": 100})

    app.window.start_run()
    assert app.window.last_message is not None
    assert app.window.last_message[0] == "Invalid timing"
    assert "min_delay_ms" in app.window.last_message[1]
    assert app.keyboard.calls == []


def test_a_vanished_target_is_reported_before_starting(harness: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(TypeText(text="hi"))
    app.windows.windows = []  # the window closed since the last refresh

    app.window.start_run()
    assert app.window.last_message is not None
    assert app.window.last_message[0] == "Target unavailable"
    assert "UNAVAILABLE" in app.window.target_panel.active_label.text()
    assert app.keyboard.calls == []


def test_a_failed_activation_is_reported_in_plain_language(harness: Any, pump: Any) -> None:
    app = harness(windows=FakeWindows(windows=[make_target()], activate_result=False))
    app.select_first_target()
    app.with_actions(TypeText(text="hi"))

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.FAILED)
    assert "Unable to activate the selected window." in app.log
    assert "Traceback" not in app.log
    assert app.keyboard.calls == []


def test_starting_twice_is_refused_without_crashing(harness: Any, pump: Any) -> None:
    app = harness()
    app.select_first_target()
    app.with_actions(Wait(duration_ms=5_000))

    app.window.start_run()
    assert pump(lambda: app.window.state is UiState.RUNNING)
    app.window.start_run()  # ignored: a run is already active
    app.window.emergency_stop()
    assert pump(lambda: app.window.state is UiState.STOPPED)
