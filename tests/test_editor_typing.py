"""Typing code into an editor that edits while you type.

Every test here runs the real engine and the real handlers against
:class:`~tests.fakes.FakeEditor`, a model of an editor that auto-indents, closes
brackets and offers completions. The model is not VS Code; it is close enough to
prove that each compensation does what it claims, which is what the equivalent
manual check in a real editor is for.
"""

from __future__ import annotations

import itertools

import pytest

from human_input_automation.core.actions import IndentMode, TypeCode, TypeText
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.events import RunStatus
from human_input_automation.core.handlers import unclosed_pairs
from human_input_automation.core.plan import AutomationPlan, RunOptions
from human_input_automation.core.timing import TimingProfile
from human_input_automation.core.typing_style import TypingStyle

from .fakes import FakeClock, FakeEditor, FakeMouse, FakeWindows, make_target

#: The example from the bug report: nested braces, a string, and a call.
SOURCE = '''function test() {
    if (typeof window !== "undefined") {
        console.log("Test function called");
        return true;
    }
    return false;
}'''


def type_into(
    editor: FakeEditor,
    action: TypeText | TypeCode,
    *,
    typing: TypingStyle | None = None,
    seed: int | None = 11,
) -> FakeEditor:
    """Run one typing action against ``editor`` through the real engine."""
    engine = AutomationEngine(
        keyboard=editor, mouse=FakeMouse(), windows=FakeWindows(), clock=FakeClock()
    )
    plan = AutomationPlan(
        make_target(),
        [action],
        timing=TimingProfile.instant(),
        typing=typing,
        options=RunOptions(seed=seed),
    )
    report = engine.run(plan)
    assert report.status is RunStatus.COMPLETED, report.error
    return editor


# ---------------------------------------------------------------------------
# The problem
# ---------------------------------------------------------------------------


def test_plain_typing_into_a_code_editor_comes_out_mangled() -> None:
    """The behaviour that TypeCode exists to fix, pinned so it stays visible."""
    editor = type_into(FakeEditor(), TypeText(text=SOURCE))

    assert editor.text != SOURCE
    # Indentation accumulates: our four spaces land on top of the editor's, and
    # the block below that gets both again - the staircase from the report.
    assert "\n        if (" in editor.text
    assert "\n                    console.log(" in editor.text
    # Every brace the editor closed for us is still there, plus the one we typed.
    assert editor.text.count("}") > SOURCE.count("}")


# ---------------------------------------------------------------------------
# The fix
# ---------------------------------------------------------------------------


def test_typing_code_reproduces_the_source_exactly() -> None:
    editor = type_into(FakeEditor(), TypeCode(text=SOURCE))
    assert editor.text == SOURCE


@pytest.mark.parametrize(
    ("auto_indent", "auto_close", "auto_complete"),
    list(itertools.product([True, False], repeat=3)),
)
def test_it_survives_every_combination_of_editor_helpfulness(
    auto_indent: bool, auto_close: bool, auto_complete: bool
) -> None:
    """Including an editor that does nothing helpful at all."""
    editor = FakeEditor(
        auto_indent=auto_indent, auto_close=auto_close, auto_complete=auto_complete
    )
    type_into(editor, TypeCode(text=SOURCE))
    assert editor.text == SOURCE


def test_it_still_reproduces_the_source_when_typing_mistakes_are_enabled() -> None:
    """A mistake is only ever a detour: the text that stays behind is the text."""
    style = TypingStyle.natural(typo_rate=0.25, hesitation_rate=0.1)
    for seed in range(12):
        editor = type_into(FakeEditor(), TypeCode(text=SOURCE), typing=style, seed=seed)
        assert editor.text == SOURCE, f"seed {seed}"


def test_a_single_line_needs_no_compensation_at_all() -> None:
    editor = type_into(FakeEditor(), TypeCode(text="print(1)"))
    assert editor.text == "print(1)"


def test_text_is_typed_into_an_editor_that_already_has_content() -> None:
    editor = FakeEditor(text="header\n")
    editor.row, editor.col = 1, 0
    type_into(editor, TypeCode(text="def f():\n    return 1"))
    assert editor.text == "header\ndef f():\n    return 1"


# ---------------------------------------------------------------------------
# The individual compensations
# ---------------------------------------------------------------------------


def test_leaving_the_indentation_to_the_editor_keeps_the_lines_themselves() -> None:
    """``IndentMode.EDITOR`` gives up on our layout, never on our text."""
    editor = type_into(FakeEditor(), TypeCode(text=SOURCE, indent=IndentMode.EDITOR))

    assert [line.strip() for line in editor.text.split("\n")] == [
        line.strip() for line in SOURCE.split("\n")
    ]
    assert "\t" not in editor.text


def test_turning_the_compensations_off_types_the_text_unchanged() -> None:
    """``off`` is the old behaviour, which a plain editor still handles fine."""
    action = TypeCode(
        text=SOURCE,
        indent=IndentMode.OFF,
        drop_auto_pairs=False,
        dismiss_suggestions=False,
    )
    editor = FakeEditor(auto_indent=False, auto_close=False, auto_complete=False)
    type_into(editor, action)
    assert editor.text == SOURCE


def test_dismissing_suggestions_is_what_stops_enter_completing_a_word() -> None:
    without = type_into(
        FakeEditor(auto_indent=False, auto_close=False),
        TypeCode(text="value\nvalue", indent=IndentMode.OFF, dismiss_suggestions=False),
    )
    assert without.completions_accepted == 1
    assert without.text == f"value{FakeEditor.COMPLETION}value"

    with_escape = type_into(
        FakeEditor(auto_indent=False, auto_close=False),
        TypeCode(text="value\nvalue", indent=IndentMode.OFF),
    )
    assert with_escape.completions_accepted == 0
    assert with_escape.text == "value\nvalue"


def test_dropping_auto_pairs_deletes_real_text_in_an_editor_that_has_none() -> None:
    """The documented hazard, pinned: Delete is not free when nothing was closed.

    This is why ``drop_auto_pairs`` is a switch and why its help text says what
    it assumes. In an editor that does not close brackets there is nothing to the
    right of the caret to delete, so the Delete takes the line break instead and
    pulls the following line up.
    """
    editor = FakeEditor(auto_indent=False, auto_close=False, auto_complete=False)
    editor.lines = ["", "tail"]
    editor.row, editor.col = 0, 0

    type_into(editor, TypeCode(text="f(", indent=IndentMode.OFF))

    assert editor.text == "f(tail"


def test_a_blank_line_keeps_the_editors_indentation() -> None:
    """Documented: clearing it would need a Delete with nothing selected."""
    editor = type_into(FakeEditor(), TypeCode(text="if (x) {\n\n}"))
    assert editor.text == "if (x) {\n    \n}"


# ---------------------------------------------------------------------------
# The bracket count the Delete presses are derived from
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", 0),
        ("plain text", 0),
        ("foo()", 0),
        ("function test() {", 1),
        ("if (a[0] == {", 2),
        ("foo(bar(", 2),
        ("})", 0),
        ("a) + (b", 1),
        ('console.log("(");', 0),
    ],
)
def test_unclosed_pairs_counts_what_the_editor_left_behind(line: str, expected: int) -> None:
    assert unclosed_pairs(line) == expected


# ---------------------------------------------------------------------------
# Sources that exercise the scanner
# ---------------------------------------------------------------------------

PYTHON_SOURCE = '''def load(path):
    # a dict looks like { "a": 1 } and a call like load(path)
    data = json.loads(path.read_text())
    print("an unmatched paren in a string: )")
    return [item for item in data if item]'''

NESTED_SOURCE = '''const config = {
    paths: ["a", "b"],
    nested: {
        fn: (x) => ({ value: x }),
    },
};'''


@pytest.mark.parametrize("source", [SOURCE, PYTHON_SOURCE, NESTED_SOURCE])
def test_brackets_in_strings_and_comments_do_not_confuse_the_count(source: str) -> None:
    editor = type_into(FakeEditor(), TypeCode(text=source))
    assert editor.text == source


def test_a_line_ending_inside_an_open_string_confuses_the_count() -> None:
    """The scanner's documented blind spot, pinned so it stays a known one.

    An unterminated quote stops the scan, so the editor's own closing quote is
    never counted and one Delete too few is sent. What is left behind is a
    character the editor inserted, not one of the user's - which is the
    direction this is built to fail in.
    """
    editor = type_into(FakeEditor(), TypeCode(text='say("hello\nworld'))
    assert editor.text == 'say("hello\nworld)'


def test_the_keys_it_may_press_are_declared_for_validation() -> None:
    """A platform that lacks one of these must fail before the run, not during."""
    from human_input_automation.core.keys import Key

    action = TypeCode(text="a\nb")
    assert set(action.keys_used) == {Key.ENTER, Key.SHIFT, Key.HOME, Key.DELETE, Key.ESC}

    quiet = TypeCode(
        text="a", indent=IndentMode.OFF, drop_auto_pairs=False, dismiss_suggestions=False
    )
    assert quiet.keys_used == ()


def test_a_line_start_chord_that_cannot_be_sent_is_rejected_in_the_editor() -> None:
    from human_input_automation.core.errors import ValidationError

    with pytest.raises(ValidationError):
        TypeCode(text="a", line_start_chord="shift+nosuchkey")
