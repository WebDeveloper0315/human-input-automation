"""Typing code into an editor that edits while you type.

Every test here runs the real engine and the real handlers against
:class:`~tests.fakes.FakeEditor`, a model of an editor that auto-indents, closes
brackets and offers completions. The model is not VS Code; it is close enough to
prove that the plan does what it claims, which is what the equivalent manual
check in a real editor is for.

The settings on :class:`TypeCode` describe the editor rather than a strategy, so
the matrix below is "tell it the truth about the editor and the source comes out
exactly", not "every combination works whatever you say".
"""

from __future__ import annotations

import itertools

import pytest

from human_input_automation.core.actions import IndentMode, PairMode, TypeCode, TypeText
from human_input_automation.core.editor_typing import (
    Chord,
    Emit,
    Press,
    infer_indent_width,
    keystroke_count,
    plan_code_typing,
    reusable_closer_lines,
    unclosed_pairs,
)
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.events import RunStatus
from human_input_automation.core.keys import Key
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
def test_settings_that_describe_the_editor_reproduce_the_source(
    auto_indent: bool, auto_close: bool, auto_complete: bool
) -> None:
    """Told what the editor does, the plan comes out right for any of them."""
    action = TypeCode(
        text=SOURCE,
        indent=IndentMode.MATCH if auto_indent else IndentMode.OFF,
        pairs=PairMode.REUSE if auto_close else PairMode.OFF,
    )
    editor = FakeEditor(
        auto_indent=auto_indent, auto_close=auto_close, auto_complete=auto_complete
    )
    type_into(editor, action)
    assert editor.text == SOURCE


@pytest.mark.parametrize("pairs", [PairMode.REUSE, PairMode.DELETE])
def test_replacing_the_editors_indentation_still_works(pairs: PairMode) -> None:
    """RECLAIM is the mode for an editor whose indenting cannot be predicted."""
    editor = FakeEditor()
    type_into(editor, TypeCode(text=SOURCE, indent=IndentMode.RECLAIM, pairs=pairs))
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


def test_it_never_types_over_the_line_the_caret_is_already_on() -> None:
    """Found by running the application: a second block ate the first one's end.

    Reconciling indentation is for a line the editor has just indented for us,
    never for the line the user left the caret on - there, a chord to the start
    of the line selects their text and types over it.
    """
    editor = FakeEditor(text="}")
    editor.row, editor.col = 0, 1  # caret at the end of a line with content

    type_into(editor, TypeCode(text="next()\nline"))

    assert editor.text == "}next()\nline"


# ---------------------------------------------------------------------------
# Using what the editor already did, instead of undoing it
# ---------------------------------------------------------------------------


def test_the_editors_own_indentation_is_kept_rather_than_retyped() -> None:
    """The whole point: where the editor already agrees, nothing is typed."""
    steps = plan_code_typing(TypeCode(text=SOURCE))

    assert not [step for step in steps if isinstance(step, Chord)]
    typed = "".join(step.text for step in steps if isinstance(step, Emit))
    assert not [line for line in typed.split("\n") if line.startswith(" ")]
    # Every emitted run is a line's content, with its indentation left to the
    # editor.
    assert all(step.text == step.text.lstrip() for step in steps if isinstance(step, Emit))


def test_a_closing_bracket_the_editor_wrote_is_walked_onto_not_retyped() -> None:
    steps = plan_code_typing(TypeCode(text=SOURCE))
    pressed = [step.key for step in steps if isinstance(step, Press)]

    assert pressed.count(Key.DOWN) == 2  # one per closing brace in the source
    assert pressed.count(Key.END) == 2
    assert Key.DELETE not in pressed
    typed = "".join(step.text for step in steps if isinstance(step, Emit))
    assert "}" not in typed


def test_working_with_the_editor_is_cheaper_than_working_against_it() -> None:
    smart = keystroke_count(plan_code_typing(TypeCode(text=SOURCE)))
    against = keystroke_count(
        plan_code_typing(
            TypeCode(text=SOURCE, indent=IndentMode.RECLAIM, pairs=PairMode.DELETE)
        )
    )
    assert smart < against
    # The source itself is the floor: 150 characters have to be typed somehow.
    assert smart < len(SOURCE) * 1.1


def test_a_bracket_the_source_never_closes_is_still_deleted() -> None:
    """Reusing where the source allows it never means leaving one behind."""
    steps = plan_code_typing(TypeCode(text="if (x) {\n    go();"))
    deletes = [step for step in steps if isinstance(step, Press) and step.key is Key.DELETE]

    assert sum(step.count for step in deletes) == 1
    editor = type_into(FakeEditor(), TypeCode(text="if (x) {\n    go();"))
    assert editor.text == "if (x) {\n    go();"


def test_an_empty_block_is_typed_rather_than_walked_onto() -> None:
    """The editor leaves a blank line between the braces; walking would keep it."""
    assert reusable_closer_lines(["if (x) {", "}"]).is_empty
    editor = type_into(FakeEditor(), TypeCode(text="if (x) {\n}"))
    assert editor.text == "if (x) {\n}"


def test_a_closer_line_with_more_on_it_is_walked_onto_and_finished() -> None:
    source = "const f = () => {\n    go();\n};"
    editor = type_into(FakeEditor(), TypeCode(text=source))
    assert editor.text == source

    steps = plan_code_typing(TypeCode(text=source))
    typed = [step.text for step in steps if isinstance(step, Emit)]
    assert typed[-1] == ";"  # only the part the editor had not written


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("a call over several lines", "foo(\n    a,\n    b\n);"),
        ("else on the closing brace", "if (a) {\n    x();\n} else {\n    y();\n}"),
        (
            "a switch that outdents",
            "switch (v) {\n    case 1:\n        a();\n    case 2:\n        b();\n}",
        ),
        ("an array literal", "const xs = [\n    1,\n    2,\n];"),
        ("three levels deep", "a {\n    b {\n        c {\n            d();\n        }\n    }\n}"),
    ],
)
def test_the_shapes_real_code_comes_in(name: str, source: str) -> None:
    editor = type_into(FakeEditor(), TypeCode(text=source))
    assert editor.text == source, name


# ---------------------------------------------------------------------------
# When a prediction is wrong
# ---------------------------------------------------------------------------


def test_an_editor_indenting_in_twos_produces_its_own_layout_not_ours() -> None:
    """The documented failure mode: a different shape, never a lost character.

    ``indent_width`` exists for this; left to guess, the block still arrives
    complete and correctly nested, indented the way the editor indents.
    """
    editor = type_into(FakeEditor(indent_unit="  "), TypeCode(text=SOURCE))

    assert editor.text != SOURCE
    assert [line.strip() for line in editor.text.split("\n")] == [
        line.strip() for line in SOURCE.split("\n")
    ]
    assert "\n  if (typeof" in editor.text
    assert editor.text.count("}") == SOURCE.count("}")


def test_telling_it_the_editors_tab_size_fixes_that() -> None:
    editor = FakeEditor(indent_unit="  ")
    source = "if (x) {\n  go();\n}"
    type_into(editor, TypeCode(text=source, indent_width=2))
    assert editor.text == source


def test_an_editor_that_does_not_indent_after_a_colon_gives_a_flat_block() -> None:
    """The other way a prediction goes wrong, and why *replace* exists.

    Some editors indent after a colon and some do not. Told to expect one that
    does, against one that does not, the text still arrives in full - but flat,
    because the indentation it was counting on never appeared.
    """
    source = "def f():\n    a = 1\n    return a"
    editor = type_into(FakeEditor(indent_after="([{"), TypeCode(text=source))

    assert editor.text == "def f():\na = 1\nreturn a"
    assert [line.strip() for line in editor.text.split("\n")] == [
        line.strip() for line in source.split("\n")
    ]

    # Replacing the indentation asks the editor for nothing, so it is exact.
    exact = type_into(
        FakeEditor(indent_after="([{"), TypeCode(text=source, indent=IndentMode.RECLAIM)
    )
    assert exact.text == source


def test_replacing_the_indentation_is_exact_whatever_the_editor_does() -> None:
    """RECLAIM assumes nothing, which is what it is for."""
    editor = type_into(
        FakeEditor(indent_unit="  "), TypeCode(text=SOURCE, indent=IndentMode.RECLAIM)
    )
    assert editor.text == SOURCE


# ---------------------------------------------------------------------------
# The individual settings
# ---------------------------------------------------------------------------


def test_leaving_the_indentation_to_the_editor_keeps_the_lines_themselves() -> None:
    """``IndentMode.EDITOR`` gives up on our layout, never on our text."""
    editor = type_into(FakeEditor(), TypeCode(text=SOURCE, indent=IndentMode.EDITOR))

    assert [line.strip() for line in editor.text.split("\n")] == [
        line.strip() for line in SOURCE.split("\n")
    ]
    assert "\t" not in editor.text


def test_an_editor_that_does_nothing_for_you_gets_the_text_unchanged() -> None:
    action = TypeCode(
        text=SOURCE,
        indent=IndentMode.OFF,
        pairs=PairMode.OFF,
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


def test_deleting_pairs_in_an_editor_that_has_none_eats_a_character() -> None:
    """The documented hazard, pinned: Delete is not free when nothing was closed.

    This is why ``pairs`` has an *off* value and why its help text says what the
    other two assume. In an editor that does not close brackets there is nothing
    to the right of the caret to delete, so the Delete takes the line break
    instead and pulls the following line up.
    """
    editor = FakeEditor(auto_indent=False, auto_close=False, auto_complete=False)
    editor.lines = ["", "tail"]
    editor.row, editor.col = 0, 0

    type_into(editor, TypeCode(text="f(", indent=IndentMode.OFF, pairs=PairMode.DELETE))

    assert editor.text == "f(tail"


def test_a_blank_line_keeps_the_editors_indentation() -> None:
    """Documented: clearing it would need a Delete with nothing selected."""
    editor = type_into(FakeEditor(), TypeCode(text="if (x) {\n\n}"))
    assert editor.text == "if (x) {\n    \n}"


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


# ---------------------------------------------------------------------------
# Reading the source
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


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["a", "  b", "    c"], 2),
        (["a", "    b", "        c"], 4),
        (["a", "  b", "      c"], 2),  # a skipped level
        (["a", "b"], 4),  # nothing to go on: the default
        (["a", "\tb"], 1),
    ],
)
def test_the_indent_width_is_read_from_the_text(lines: list[str], expected: int) -> None:
    assert infer_indent_width(lines) == expected


def test_reusable_lines_pair_the_way_brackets_nest() -> None:
    plan = reusable_closer_lines(SOURCE.split("\n"))
    assert plan.written == {4: "    }", 6: "}"}
    assert plan.answered == frozenset({0, 1})


def test_the_keys_it_may_press_are_declared_for_validation() -> None:
    """A platform that lacks one of these must fail before the run, not during."""
    action = TypeCode(text="a\nb")
    assert set(action.keys_used) == {
        Key.ENTER,
        Key.SHIFT,
        Key.HOME,
        Key.DELETE,
        Key.DOWN,
        Key.END,
        Key.ESC,
    }

    quiet = TypeCode(
        text="a", indent=IndentMode.OFF, pairs=PairMode.OFF, dismiss_suggestions=False
    )
    assert quiet.keys_used == ()


def test_a_line_start_chord_that_cannot_be_sent_is_rejected_in_the_editor() -> None:
    from human_input_automation.core.errors import ValidationError

    with pytest.raises(ValidationError):
        TypeCode(text="a", line_start_chord="shift+nosuchkey")


def test_an_impossible_indent_width_is_rejected() -> None:
    from human_input_automation.core.errors import ValidationError

    with pytest.raises(ValidationError):
        TypeCode(text="a", indent_width=40)
