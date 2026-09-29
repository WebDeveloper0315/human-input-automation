"""The converted guides in examples/autoscript/ are the conformance corpus.

They were written by an assistant from real work guides, not by whoever wrote
the parser, which is what makes them worth testing against: every one must
read with no errors, and every step in it must be read as exactly one step.
If one of them is edited and breaks, this says which line.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from human_input_automation.app import run_check_script
from human_input_automation.application.autoscript import check_script_file
from human_input_automation.core.autoscript import check_script

EXAMPLES = sorted((Path(__file__).parent.parent / "examples" / "autoscript").glob("*.md"))


def test_there_is_a_corpus_to_check() -> None:
    assert len(EXAMPLES) >= 5


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_every_converted_guide_is_valid(path: Path) -> None:
    report = check_script(path.read_text(encoding="utf-8"))
    assert report.errors == (), "\n".join(f"{i.location}: {i.message}" for i in report.errors)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_every_step_written_is_read_as_exactly_one_step(path: Path) -> None:
    """Nothing silently dropped, nothing silently doubled."""
    text = path.read_text(encoding="utf-8")
    written, fenced = 0, False
    for line in text.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        elif not fenced and (re.match(r"^\s*[-*]\s+\S", line) or line.startswith("App:")):
            written += 1
    assert check_script(text).script.step_count == written


# ---------------------------------------------------------------------------
# --check-script
# ---------------------------------------------------------------------------


def test_the_command_reports_each_problem_where_an_editor_can_find_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "broken.md"
    script.write_text("# T\n\nPlatform: macOS\n\n## S\n- screenshot\n- click\n", encoding="utf-8")

    assert run_check_script([str(script)]) == 1
    output = capsys.readouterr().out
    assert f"{script}:7: error: script.step: unknown verb 'click'" in output
    assert "Nothing was run and no input was generated." in output


def test_the_command_passes_a_clean_script_and_lists_what_was_left_to_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "clean.md"
    script.write_text(
        "# T\n\nPlatform: macOS\n\n## S\n- screenshot\n> CHECK: Save - may read Save…\n"
        "> UNSUPPORTED: no verb judges colour\n",
        encoding="utf-8",
    )

    assert run_check_script([str(script)]) == 0
    output = capsys.readouterr().out
    assert f"{script}: OK - 1 stage(s), 0 routine(s), 1 step(s)" in output
    assert f"{script}:8: unsupported: no verb judges colour" in output
    assert "1 CHECK note(s)" in output


def test_one_bad_file_fails_the_whole_batch(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text("# T\n\nPlatform: macOS\n\n## S\n- screenshot\n", encoding="utf-8")
    assert run_check_script([str(good), str(tmp_path / "missing.md")]) == 1


def test_a_file_that_cannot_be_read_is_reported_not_raised(tmp_path: Path) -> None:
    assert check_script_file(tmp_path / "nope.md").errors[0].message == "no such file"
    assert "folder" in check_script_file(tmp_path).errors[0].message
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00bad")
    assert "UTF-8" in check_script_file(binary).errors[0].message
