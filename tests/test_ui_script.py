"""The AutoScript panel: open, check, preview and run a script from the window.

Real service, runner and engine; fake adapters. The target is the fake
``test-app`` window, so every script here says ``App: test-app``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI extra not installed")

from human_input_automation.ui.models import UiState

from .test_ui_main_window import Harness

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def harness() -> Any:
    built: list[Harness] = []

    def _make(**kwargs: Any) -> Harness:
        built.append(Harness(**kwargs))
        return built[-1]

    yield _make
    for app in built:
        app.close()


def write(tmp_path: Path, body: str, name: str = "task.md") -> str:
    path = tmp_path / name
    path.write_text("# Task\n\nPlatform: Linux\nApp: test-app\n\n## Do it\n\n" + body, "utf-8")
    return str(path)


def finished(app: Any) -> bool:
    return app.window.state in (UiState.COMPLETED, UiState.STOPPED, UiState.FAILED)


def test_nothing_can_be_run_before_a_script_is_open(harness: Any) -> None:
    panel = harness().window.script_panel
    assert panel.open_button.isEnabled()
    assert not panel.run_button.isEnabled() and not panel.dry_run_button.isEnabled()


def test_opening_a_script_checks_it_and_shows_what_it_uses(harness: Any, tmp_path: Path) -> None:
    app = harness()
    app.window.open_script(write(tmp_path, '- type "hello"\n'))

    panel = app.window.script_panel
    assert panel.run_button.isEnabled() and panel.dry_run_button.isEnabled()
    assert "test-app" in panel.summary_label.text()
    assert app.keyboard.calls == [], "opening a script never runs it"


def test_errors_are_listed_with_their_lines_and_nothing_can_run(
    harness: Any, tmp_path: Path
) -> None:
    app = harness()
    app.window.open_script(write(tmp_path, '- tpye "hello"\n'))

    panel = app.window.script_panel
    assert not panel.run_button.isEnabled() and not panel.dry_run_button.isEnabled()
    assert "1 error(s)" in panel.summary_label.text()
    assert "line 8" in app.log and "Did you mean 'type'" in app.log


def test_a_confirmed_script_runs_on_the_worker_and_is_logged_by_line(
    harness: Any, pump: Any, tmp_path: Path
) -> None:
    app = harness()
    app.window.script_run_prompt = lambda question: True
    app.window.controls.minimise_check.setChecked(False)
    app.window.open_script(write(tmp_path, '- type "hello"\n- key-click enter\n'))

    app.window.run_script()
    assert pump(lambda: finished(app))

    assert app.window.state is UiState.COMPLETED, app.log
    assert app.keyboard.typed == "hello"
    assert "Line 8: type \"hello\"" in app.log and "Line 9: key-click enter" in app.log
    assert app.window.script_panel.run_button.isEnabled()


def test_the_question_names_the_applications_and_declining_sends_nothing(
    harness: Any, tmp_path: Path
) -> None:
    app = harness()
    asked: list[str] = []

    def decline(question: str) -> bool:
        asked.append(question)
        return False

    app.window.script_run_prompt = decline
    app.window.open_script(write(tmp_path, '- type "hello"\n'))
    app.window.run_script()

    assert "test-app" in asked[0]
    assert app.window.state is UiState.IDLE and app.keyboard.calls == []


def test_without_a_dialog_a_script_is_never_run_unasked(harness: Any, tmp_path: Path) -> None:
    app = harness()  # show_dialogs=False and no prompt set
    app.window.open_script(write(tmp_path, '- type "hello"\n'))
    app.window.run_script()
    assert app.keyboard.calls == []


def test_screen_steps_block_running_but_not_the_dry_run(harness: Any, tmp_path: Path) -> None:
    app = harness()
    app.window.script_run_prompt = lambda question: True
    app.window.open_script(
        write(tmp_path, '- screenshot\n- find button "Save" as save\n- move to {{save}}\n')
    )
    panel = app.window.script_panel
    assert not panel.run_button.isEnabled() and panel.dry_run_button.isEnabled()
    assert any("roadmap 8.3" in problem for problem in panel.problems)

    app.window.dry_run_script()
    preview = app.window.dry_run_panel.action_lines
    assert 'line 9: find button "Save" as save' in preview
    assert app.keyboard.calls == [] and app.mouse.calls == []


def test_the_file_is_checked_again_when_run(harness: Any, tmp_path: Path) -> None:
    """Edited into something broken after opening: refused, not run from memory."""
    app = harness()
    app.window.script_run_prompt = lambda question: True
    path = write(tmp_path, '- type "hello"\n')
    app.window.open_script(path)
    write(tmp_path, '- tpye "hello"\n')

    app.window.run_script()
    assert app.keyboard.calls == [] and app.window.state is UiState.IDLE
    assert app.window.last_message is not None
    assert app.window.last_message[0] == "Script cannot run"


def test_the_emergency_stop_ends_a_script_run(harness: Any, pump: Any, tmp_path: Path) -> None:
    app = harness()
    app.window.script_run_prompt = lambda question: True
    app.window.controls.minimise_check.setChecked(False)
    app.window.open_script(write(tmp_path, '- wait 30 s\n- type "never"\n'))

    app.window.run_script()
    assert pump(lambda: app.window.state is UiState.RUNNING)
    assert not app.window.script_panel.open_button.isEnabled(), "locked while running"
    app.window.emergency_stop()
    assert pump(lambda: finished(app), timeout=5)

    assert app.window.state is UiState.STOPPED
    assert app.keyboard.typed == ""


def test_a_plan_cannot_start_while_a_script_runs(harness: Any, pump: Any, tmp_path: Path) -> None:
    app = harness()
    app.window.script_run_prompt = lambda question: True
    app.window.controls.minimise_check.setChecked(False)
    app.window.open_script(write(tmp_path, "- wait 30 s\n"))
    app.window.run_script()
    assert pump(lambda: app.window.state is UiState.RUNNING)

    with pytest.raises(RuntimeError):
        app.service.start(object())
    app.window.emergency_stop()
    assert pump(lambda: finished(app))
