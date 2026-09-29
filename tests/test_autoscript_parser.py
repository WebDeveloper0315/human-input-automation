"""Reading AutoScript: every line's shape, and every step's grammar."""

from __future__ import annotations

import textwrap

import pytest

from human_input_automation.core.autoscript import parse_script
from human_input_automation.core.autoscript.model import (
    Button,
    Call,
    Click,
    Comparison,
    Expect,
    Find,
    ForEach,
    KeyClick,
    KeyDown,
    Locator,
    MoveTo,
    Point,
    PositionVariable,
    PressButton,
    Read,
    Record,
    Repeat,
    Role,
    Run,
    Screenshot,
    Scroll,
    Template,
    TypeBlock,
    TypeTable,
    TypeText,
    UseApp,
    Wait,
    WaitFor,
    WaitForWindow,
)
from human_input_automation.core.autoscript.parser import StepSyntaxError, Unparsed, parse_step
from human_input_automation.core.keys import Key


def doc(body: str) -> str:
    return "# Task\n\nPlatform: macOS\n\n## Stage\n\n" + textwrap.dedent(body)


def steps_of(body: str) -> tuple[object, ...]:
    result = parse_script(doc(body))
    assert result.ok, result.errors
    return result.script.stages[0].steps


def codes(text: str) -> list[str]:
    return [issue.code for issue in parse_script(text).errors]


# ---------------------------------------------------------------------------
# The two worked examples from the request, exactly as written in §3
# ---------------------------------------------------------------------------


def test_deleting_a_file_reads_as_eight_steps() -> None:
    steps = steps_of(
        """
        App: Finder

        - screenshot
        - find "quarterly_report.pdf" as file
        - move to {{file}}
        - right-click
        - screenshot
        - find "Move to Trash" as menu_item
        - move to {{menu_item}}
        - left-click
        """
    )
    assert steps == (
        UseApp(8, "Finder"),
        Screenshot(10),
        Find(11, Locator(Template("quarterly_report.pdf")), "file"),
        MoveTo(12, PositionVariable("file")),
        Click(13, Button.RIGHT),
        Screenshot(14),
        Find(15, Locator(Template("Move to Trash")), "menu_item"),
        MoveTo(16, PositionVariable("menu_item")),
        Click(17, Button.LEFT),
    )


def test_opening_terminal_from_spotlight() -> None:
    steps = steps_of(
        """
        - key-click cmd+space
        - wait 300 ms
        - type "terminal"
        - key-click enter
        - wait for window "Terminal"
        """
    )
    assert steps == (
        KeyClick(8, (Key.META, Key.SPACE), "cmd+space"),
        Wait(9, 300.0),
        TypeText(10, Template("terminal")),
        KeyClick(11, (Key.ENTER,), "enter"),
        WaitForWindow(12, Template("Terminal")),
    )


# ---------------------------------------------------------------------------
# Every verb
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("move to 1204,640", MoveTo(1, Point(1204, 640))),
        ("move to -200,30", MoveTo(1, Point(-200, 30))),
        ("move to {{x}}", MoveTo(1, PositionVariable("x"))),
        ('move to button "Save"', MoveTo(1, Locator(Template("Save"), Role.BUTTON))),
        ("left-click", Click(1, Button.LEFT)),
        ("left-click twice", Click(1, Button.LEFT, 2)),
        ("right-click", Click(1, Button.RIGHT)),
        ("middle-click", Click(1, Button.MIDDLE)),
        ("press-button left", PressButton(1, Button.LEFT)),
        ("scroll down 3", Scroll(1, "down", 3)),
        ('type "a {{b}} c"', TypeText(1, Template("a {{b}} c"))),
        ("type `ls -la`", TypeText(1, Template("ls -la"))),
        ('type block "csv"', TypeBlock(1, "csv")),
        ('type table "Log"', TypeTable(1, "Log")),
        ("key-click cmd+option+l", KeyClick(1, (Key.META, Key.ALT, "l"), "cmd+option+l")),
        ("key-click ctrl++", KeyClick(1, (Key.CTRL, "+"), "ctrl++")),
        ("key-down shift", KeyDown(1, Key.SHIFT)),
        ("run `psql -l`", Run(1, Template("psql -l"))),
        ("wait 2 s", Wait(1, 2000.0)),
        ('wait for "Save" up to 30 s', WaitFor(1, Locator(Template("Save")), 30.0)),
        ('wait for field "Name"', WaitFor(1, Locator(Template("Name"), Role.FIELD))),
        ('wait for window "Desktop" up to 5 s', WaitForWindow(1, Template("Desktop"), 5.0)),
        ("screenshot", Screenshot(1)),
        (
            'find item "{{f}}" in window "Downloads" as icon',
            Find(1, Locator(Template("{{f}}"), Role.ITEM, Template("Downloads")), "icon"),
        ),
        (
            'find text containing "My Playlist #" as p',
            Find(1, Locator(Template("My Playlist #"), Role.TEXT, containing=True), "p"),
        ),
        ("read output as result", Read(1, None, "result")),
        ('read "Image size" as size', Read(1, Locator(Template("Image size")), "size")),
        (
            'record file={{f}}, size="x" into "Sizes"',
            Record(1, (("file", Template("{{f}}")), ("size", Template("x"))), "Sizes"),
        ),
        (
            'do "save as" with name="a.txt", folder={{dir}}',
            Call(1, "save as", (("name", Template("a.txt")), ("folder", Template("{{dir}}")))),
        ),
        ('do "reset" ', Call(1, "reset")),
        ('for each row in "Zones":', ForEach(1, "Zones")),
        ("repeat 4 times:", Repeat(1, 4)),
    ],
)
def test_every_verb(text: str, expected: object) -> None:
    assert parse_step(text, 1) == expected


@pytest.mark.parametrize(
    ("text", "subject", "comparison", "value"),
    [
        ('expect output contains "COPY 30"', "output", Comparison.CONTAINS, Template("COPY 30")),
        (
            'expect output does not contain "MISMATCH"',
            "output",
            Comparison.NOT_CONTAINS,
            Template("MISMATCH"),
        ),
        (r'expect output matches "\d+"', "output", Comparison.MATCHES, Template(r"\d+")),
        ('expect {{v}} contains "t"', "v", Comparison.CONTAINS, Template("t")),
        ('expect {{v}} == "text"', "v", Comparison.EQUAL, Template("text")),
        ("expect {{v}} == 6", "v", Comparison.EQUAL, 6.0),
        ("expect {{v}} >= 128", "v", Comparison.GREATER_EQUAL, 128.0),
        ("expect {{v}} != 0", "v", Comparison.NOT_EQUAL, 0.0),
    ],
)
def test_every_form_of_expect(
    text: str, subject: str, comparison: Comparison, value: object
) -> None:
    step = parse_step(text, 1)
    assert isinstance(step, Expect)
    assert (step.subject, step.comparison, step.value) == (subject, comparison, value)


def test_expect_something_on_screen() -> None:
    exists = parse_step('expect button "Save" exists', 1)
    gone = parse_step('expect "To Do" does not exist', 1)
    assert isinstance(exists, Expect) and exists.comparison is Comparison.EXISTS
    assert isinstance(gone, Expect) and gone.comparison is Comparison.NOT_EXISTS


def test_app_as_a_step_and_a_declared_terminal() -> None:
    assert parse_step("App: GeoGebra Classic", 1) == UseApp(1, "GeoGebra Classic")
    assert parse_step("App: Warp (terminal)", 1) == UseApp(1, "Warp", declared_terminal=True)


# ---------------------------------------------------------------------------
# Quoting and escaping (§5.3)
# ---------------------------------------------------------------------------


def test_only_quote_and_backslash_are_escapes_so_patterns_read_as_written() -> None:
    step = parse_step(r'expect {{v}} matches "\d+ × \d+ \"px\" \\s"', 1)  # noqa: RUF001 - the sign Preview shows
    assert isinstance(step, Expect)
    assert step.value == Template(r'\d+ × \d+ "px" \s')  # noqa: RUF001 - the sign Preview shows


def test_double_backticks_fence_a_command_containing_one() -> None:
    step = parse_step("run `` echo `date` ``", 1)
    assert step == Run(1, Template("echo `date`"))


def test_shell_and_awk_braces_are_not_substitutions() -> None:
    step = parse_step("run `mkdir -p x/{raw,exports} && awk '{n++}'`", 1)
    assert isinstance(step, Run) and step.command.names == ()


def test_a_substitution_can_sit_right_against_a_closing_brace() -> None:
    """Script 4 put a space before its final '}' to avoid '}}}'. It needn't."""
    template = Template('{"score":{{score}}}')
    assert template.names == ("score",)
    assert template.render({"score": "4.5"}) == '{"score":4.5}'


def test_an_escaped_opening_brace_pair_stays_literal() -> None:
    template = Template(r"\{{not_a_name}} but {{name}}")
    assert template.names == ("name",)
    assert template.render({"name": "x"}) == "{{not_a_name}} but x"


# ---------------------------------------------------------------------------
# Errors a step can make, with messages for its author
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("click", "Did you mean 'left-click'"),
        ("moev to 1,2", "Did you mean 'move'"),
        ("This line is a note", "write it without the leading '-'"),
        ('type "unfinished', "never closed"),
        ("run `unfinished", "never closed"),
        ('find "x"', "expected 'as'"),
        ('find "x" as 9lives', "letters, digits and underscores"),
        ("key-click cmd+nosuchkey", "unknown key"),
        ("wait 3 minutes", "expected 'ms' or 's'"),
        ("wait 700 s", "between 0 ms and 600 s"),
        ('wait for "x" up to 900 s', "up to 600 s"),
        ("scroll sideways 2", "expected 'up'"),
        ("repeat 2.5 times:", "whole number"),
        ('for each row in "T"', "ends with ':'"),
        ('expect "Save" contains "x"', "only be checked with 'exists'"),
        ("expect {{v}} exists", "only something on screen can exist"),
        ('expect output == "x"', "read output as"),
        ("expect {{v}} > big", "expected a number"),
        ('expect {{v}} matches "(unclosed"', "not a valid regular expression"),
        ('record a=1, a=2 into "T"', "given more than once"),
        ("move to 1.5,2", "whole pixels"),
        ("left-click thrice", "unexpected 'thrice'"),
        ("App:", "needs the name"),
    ],
)
def test_a_step_that_does_not_parse_says_why(text: str, fragment: str) -> None:
    with pytest.raises(StepSyntaxError) as excinfo:
        parse_step(text, 1)
    assert fragment in str(excinfo.value)


# ---------------------------------------------------------------------------
# The shape of a document (§5.1, §5.2)
# ---------------------------------------------------------------------------


def test_numbered_lines_are_the_guides_prose_not_steps() -> None:
    """Every conversion kept the guide's '1. Click New' text; only '-' is a step."""
    steps = steps_of(
        """
        1. Click **New → HTTP Request**. Set the method to **POST**.

        - screenshot

        2. Go to **Body → raw → JSON**.
        """
    )
    assert steps == (Screenshot(10),)


def test_notes_quotes_and_deeper_headings_are_prose_and_notes_are_kept() -> None:
    result = parse_script(
        doc(
            """
            - screenshot
            > CHECK: Save - may read "Save…"
              > UNSUPPORTED: no verb judges colour
            ### If something goes wrong
            Expected: 31 lines. Tip: press Up.
            **Bold**, *italic*, and a horizontal rule:
            ---
            - left-click
            """
        )
    )
    assert result.ok, result.errors
    assert [type(s).__name__ for s in result.script.stages[0].steps] == ["Screenshot", "Click"]
    assert [(n.kind, n.text) for n in result.script.notes] == [
        ("CHECK", 'Save - may read "Save…"'),
        ("UNSUPPORTED", "no verb judges colour"),
    ]


def test_loops_nest_and_prose_inside_them_does_not_end_them() -> None:
    steps = steps_of(
        """
        Table: T

        | a |
        |---|
        | 1 |

        - for each row in "T":
          - type "{{a}}"
          > CHECK: in the middle of the body
          - repeat 2 times:
            - key-click enter
          - screenshot
        - left-click
        """
    )
    loop, click = steps
    assert isinstance(loop, ForEach) and isinstance(click, Click)
    assert [type(s).__name__ for s in loop.body] == ["TypeText", "Repeat", "Screenshot"]
    inner = loop.body[1]
    assert isinstance(inner, Repeat) and [type(s).__name__ for s in inner.body] == ["KeyClick"]


def test_an_indented_step_with_nothing_to_nest_under_is_an_error() -> None:
    assert "script.indented" in codes(doc("- screenshot\n  - left-click\n"))


def test_a_loop_with_nothing_under_it_is_an_error() -> None:
    assert "script.empty_loop" in codes(doc("- repeat 2 times:\n- left-click\n"))


def test_routines_may_be_defined_after_the_stages_that_call_them() -> None:
    result = parse_script(
        doc(
            """
            - do "later" with x="1"

            ## Routine: later (x)

            - type "{{x}}"

            ## Routine: none ()

            - screenshot
            """
        )
    )
    assert result.ok, result.errors
    assert set(result.script.routines) == {"later", "none"}
    assert result.script.routines["later"].parameters == ("x",)
    assert result.script.routines["none"].parameters == ()


@pytest.mark.parametrize(
    ("heading", "code"),
    [
        ("## Routine: no parentheses", "script.routine_heading"),
        ("## Routine: bad (a b)", "script.parameter_name"),
        ("## Routine: twice (a, a)", "script.parameter_twice"),
    ],
)
def test_a_malformed_routine_heading_is_named(heading: str, code: str) -> None:
    assert code in codes("# T\n\n" + heading + "\n\n- screenshot\n")


def test_tables_and_blocks_may_follow_their_directive_directly() -> None:
    result = parse_script(
        doc(
            """
            Table: Attorneys
            | attorney | slug |
            |---|---|
            | Priya Shah | shah |
            | A \\| B | x |

            Block: csv
            ```
            a,b
            1,2
            ```

            - type block "csv"
            - for each row in "Attorneys":
              - type "{{slug}}"
            """
        )
    )
    assert result.ok, result.errors
    table = result.script.tables["Attorneys"]
    assert table.columns == ("attorney", "slug")
    assert table.rows == (("Priya Shah", "shah"), ("A | B", "x"))
    assert result.script.blocks["csv"].text == "a,b\n1,2"


def test_a_fenced_block_that_is_not_a_block_is_skipped_whole() -> None:
    """A '- ' line inside an example fence must not become a step."""
    steps = steps_of(
        """
        ```
        - not a step
        ```
        - screenshot
        """
    )
    assert steps == (Screenshot(11),)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("## Stage\n\n- screenshot\n", "script.no_title"),
        ("# T\n\n- screenshot\n", "script.step_before_stage"),
        ("# T\n# U\n\n## S\n", "script.second_title"),
        ("# T\nPlatform: BeOS\n## S\n", "script.platform"),
        ("# T\n## S\nPlatform: macOS\n", "script.late_platform"),
        ("# T\n## S\nTable: X\n\nnot a table\n", "script.table_missing"),
        ("# T\n## S\nTable: X\n| a | b |\n|---|---|\n| 1 |\n", "script.table_row"),
        ("# T\n## S\nTable: X\n| a | a |\n|---|---|\n| 1 | 2 |\n", "script.table_column_twice"),
        ("# T\n## S\nBlock: B\n\nno fence\n", "script.block_missing"),
        ("# T\n## S\nBlock: B\n```\nnever closed\n", "script.fence_open"),
        (
            "# T\n## S\nTable: X\n| a |\n|---|\n| 1 |\nTable: X\n| a |\n|---|\n| 1 |\n",
            "script.defined_twice",
        ),
        ("# T\n## S\n-\n", "script.empty_step"),
    ],
)
def test_document_level_errors(text: str, code: str) -> None:
    assert code in codes(text)


def test_every_problem_is_reported_not_just_the_first() -> None:
    result = parse_script(doc("- click\n- screenshot\n- moev to 1,2\n- wait forever\n"))
    assert [issue.location for issue in result.errors] == ["line 7", "line 9", "line 10"]


def test_a_broken_step_still_counts_as_assigning_its_name() -> None:
    """So one typo does not become a cascade of 'unknown variable' errors."""
    result = parse_script(doc('- find item "x" wibble as target\n- move to {{target}}\n'))
    broken = result.script.stages[0].steps[0]
    assert isinstance(broken, Unparsed) and broken.assigns == "target"


def test_a_column_name_that_cannot_be_substituted_is_a_warning() -> None:
    result = parse_script(doc("Table: X\n| Branch colour |\n|---|\n| blue |\n"))
    assert [i.code for i in result.issues] == ["script.table_column_name"]
