"""Saving the run log: only when asked, only where asked, with where it came from."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from human_input_automation.application.run_log import (
    run_log_filename,
    run_log_text,
    save_run_log,
)
from human_input_automation.metadata import METADATA

NOON = datetime(2026, 10, 1, 12, 30, 5)


def test_the_file_says_what_it_is_then_holds_the_log_unchanged() -> None:
    lines = ['12:30:01  Line 22: type "terminal"', "12:30:04  Run failed: line 24: no window"]
    text = run_log_text(lines, platform="macos/quartz", script="/x/1-legal-cases.md", now=NOON)

    assert text.splitlines() == [
        f"{METADATA.name} {METADATA.version} - run log",
        "Saved:    2026-10-01 12:30:05",
        "Platform: macos/quartz",
        "Script:   /x/1-legal-cases.md",
        "",
        *lines,
    ]


def test_without_a_script_there_is_no_script_line() -> None:
    assert "Script:" not in run_log_text(["a"], platform="linux/x11", now=NOON)


def test_file_names_sort_by_time() -> None:
    assert run_log_filename(NOON) == "run-log-20261001-123005.txt"


def test_a_failed_write_is_reported_not_raised(tmp_path: Path) -> None:
    problem = save_run_log(tmp_path / "missing-folder" / "log.txt", "x")
    assert problem is not None


# -- the window --------------------------------------------------------------
pytest.importorskip("PySide6", reason="GUI extra not installed")


@pytest.fixture
def window(qt_app: Any) -> Any:
    from .test_ui_main_window import Harness

    app = Harness()
    yield app.window
    app.close()


def test_the_button_writes_the_whole_log_where_asked(window: Any, tmp_path: Path) -> None:
    window.run_log.append_line("09:00:00  Line 8: run `ls`")
    target = tmp_path / "test-1.txt"

    window.save_log(str(target))

    saved = target.read_text(encoding="utf-8")
    assert "Line 8: run `ls`" in saved and "Platform: linux/x11" in saved
    assert f"Run log saved to {target}" in window.run_log.lines[-1]


def test_nothing_is_written_without_a_chosen_path(window: Any, tmp_path: Path) -> None:
    window.run_log.append_line("x")
    window.save_log()  # no dialog in tests, so no path: nothing happens
    assert list(tmp_path.iterdir()) == []


def test_an_empty_log_is_not_saved(window: Any, tmp_path: Path) -> None:
    window.run_log.clear()
    window.save_log(str(tmp_path / "empty.txt"))
    assert not (tmp_path / "empty.txt").exists()
    assert window.last_message == ("Nothing to save", "The run log is empty.")


def test_the_save_button_is_on_the_run_log(window: Any) -> None:
    assert window.run_log.save_button.text() == "Save log..."
