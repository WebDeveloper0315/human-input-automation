"""Checking a script as a whole: names, routines, tables, terminals, screenshots."""

from __future__ import annotations

import textwrap

from human_input_automation.core.autoscript import check_script
from human_input_automation.core.errors import ValidationIssue


def issues(body: str, *, platform: bool = True) -> tuple[ValidationIssue, ...]:
    head = "# Task\n\n" + ("Platform: macOS\n\n" if platform else "")
    return check_script(head + textwrap.dedent(body)).issues


def errors(body: str) -> list[tuple[str, str]]:
    """(code, location) for every error."""
    return [(i.code, i.location) for i in issues(body) if i.severity.value == "error"]


def codes(body: str) -> list[str]:
    return [code for code, _ in errors(body)]


def warnings(body: str) -> list[str]:
    return [i.code for i in issues(body) if i.severity.value == "warning"]


# ---------------------------------------------------------------------------
# Stale screenshots (§5.6) - the silent failure this validator exists for
# ---------------------------------------------------------------------------


def test_a_find_straight_after_a_screenshot_is_fine() -> None:
    assert errors('## S\n- screenshot\n- find "Save" as s\n') == []


def test_a_find_after_input_without_a_new_screenshot_is_an_error() -> None:
    found = issues('## S\n- screenshot\n- left-click\n- find "Save" as s\n')
    stale = [i for i in found if i.code == "script.stale_screenshot"]
    assert len(stale) == 1
    assert stale[0].location == "line 8"
    assert "the input on line 7" in stale[0].message


def test_the_first_look_at_the_screen_needs_a_screenshot_too() -> None:
    assert codes('## S\n- find "Save" as s\n') == ["script.stale_screenshot"]


def test_wait_for_takes_its_own_screenshot() -> None:
    body = '## S\n- left-click\n- wait for button "Save"\n- find button "Save" as s\n'
    assert errors(body) == []


def test_every_way_of_looking_at_the_screen_is_checked() -> None:
    body = """
    ## S
    - screenshot
    - find "a" as a
    - left-click
    - read "b" as b
    - expect "c" exists
    - move to "d"
    """
    assert codes(body) == ["script.stale_screenshot"] * 3


def test_reading_the_terminal_does_not_need_a_screenshot() -> None:
    body = """
    ## S
    App: Terminal
    - run `ls`
    - read output as listing
    - expect output contains "x"
    """
    assert errors(body) == []


def test_moving_to_a_position_already_found_does_not_look_again() -> None:
    body = '## S\n- screenshot\n- find "a" as a\n- left-click\n- move to {{a}}\n'
    assert errors(body) == []


def test_switching_application_counts_as_input() -> None:
    body = '## S\n- screenshot\n- App: Finder\n- find "a" as a\n'
    assert codes(body) == ["script.stale_screenshot"]


def test_a_loop_is_checked_on_its_second_time_round() -> None:
    """Safe the first time, because the screenshot came before the loop -
    stale every later time, because the body's own click came after it."""
    body = """
    Table: T
    | n |
    |---|
    | 1 |
    | 2 |

    ## S
    - screenshot
    - for each row in "T":
      - find "Item {{n}}" as item
      - move to {{item}}
      - left-click
    """
    found = errors(body)
    assert found == [("script.stale_screenshot", "line 15")]
    assert "line 17" in next(i.message for i in issues(body) if i.code == "script.stale_screenshot")


def test_a_loop_that_ends_with_a_screenshot_is_safe_every_time() -> None:
    body = """
    Table: T
    | n |
    |---|
    | 1 |

    ## S
    - screenshot
    - for each row in "T":
      - find "Item {{n}}" as item
      - move to {{item}}
      - left-click
      - screenshot
    """
    assert errors(body) == []


def test_after_a_loop_the_screen_is_as_stale_as_either_way_out() -> None:
    body = """
    ## S
    - screenshot
    - repeat 2 times:
      - left-click
    - find "x" as x
    """
    assert codes(body) == ["script.stale_screenshot"]


def test_a_routine_starts_knowing_nothing_about_the_screen() -> None:
    body = """
    ## S
    - screenshot
    - do "r"

    ## Routine: r ()
    - find "x" as x
    """
    found = [i for i in issues(body) if i.code == "script.stale_screenshot"]
    assert len(found) == 1 and "start of routine 'r'" in found[0].message


def test_a_call_leaves_the_screen_as_the_routine_left_it() -> None:
    """Script 5's 'open card' ends with 'wait for', so the find after it is fine."""
    fresh = """
    ## S
    - do "open"
    - find "Description" as d

    ## Routine: open ()
    - left-click
    - wait for "Description"
    """
    stale = fresh.replace('- wait for "Description"', "- key-click esc")
    assert errors(fresh) == []
    assert codes(stale) == ["script.stale_screenshot"]


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_a_name_must_be_set_before_it_is_used() -> None:
    body = """
    ## S
    - type "{{later}}"
    - screenshot
    - read "x" as later
    - type "{{later}}"
    """
    assert errors(body) == [("script.unknown_variable", "line 7")]


def test_names_carry_on_from_one_stage_to_the_next() -> None:
    body = '## A\n- screenshot\n- read "x" as x\n\n## B\n- type "{{x}}"\n'
    assert errors(body) == []


def test_a_routine_sees_its_parameters_and_nothing_of_its_callers() -> None:
    body = """
    ## S
    - screenshot
    - read "x" as secret
    - do "r" with shown="1"

    ## Routine: r (shown)
    - type "{{shown}}"
    - type "{{secret}}"
    """
    found = [i for i in issues(body) if i.code == "script.unknown_variable"]
    assert len(found) == 1 and "sees only its parameters (shown)" in found[0].message


def test_table_columns_exist_only_inside_the_loop_over_that_table() -> None:
    body = """
    Table: T
    | name |
    |---|
    | a |

    ## S
    - for each row in "T":
      - type "{{name}}"
    - type "{{name}}"
    """
    assert codes(body) == ["script.unknown_variable"]


def test_nested_loops_see_both_tables_columns() -> None:
    body = """
    Table: A
    | a |
    |---|
    | 1 |

    Table: B
    | b |
    |---|
    | 2 |

    ## S
    - for each row in "A":
      - for each row in "B":
        - type "{{a}}{{b}}"
    """
    assert errors(body) == []


def test_a_name_set_inside_a_loop_is_there_after_it() -> None:
    body = """
    ## S
    - repeat 2 times:
      - screenshot
      - read "x" as last
    - type "{{last}}"
    """
    assert errors(body) == []


def test_positions_and_text_are_not_interchangeable() -> None:
    assert codes('## S\n- screenshot\n- find "a" as spot\n- type "{{spot}}"\n') == [
        "script.position_as_text"
    ]
    assert codes('## S\n- screenshot\n- read "a" as words\n- move to {{words}}\n') == [
        "script.text_as_position"
    ]


def test_names_inside_a_block_are_checked_where_it_is_typed() -> None:
    body = """
    Block: body
    ```
    {"id": "{{missing}}"}
    ```

    ## S
    - type block "body"
    """
    assert codes(body) == ["script.unknown_variable"]


# ---------------------------------------------------------------------------
# Routines
# ---------------------------------------------------------------------------


def test_calls_must_match_the_routine() -> None:
    body = """
    ## S
    - do "nope"
    - do "r" with a="1"
    - do "r" with a="1", b="2", c="3"

    ## Routine: r (a, b)
    - type "{{a}}{{b}}"
    """
    assert codes(body) == [
        "script.unknown_routine",
        "script.missing_argument",
        "script.unknown_argument",
    ]


def test_routines_may_not_call_each_other_in_a_loop() -> None:
    body = """
    ## S
    - do "ping"

    ## Routine: ping ()
    - do "pong"

    ## Routine: pong ()
    - do "ping"
    """
    assert "script.recursion" in codes(body)


def test_an_unused_routine_is_a_warning() -> None:
    assert "script.unused_routine" in warnings(
        "## S\n- screenshot\n\n## Routine: idle ()\n- screenshot\n"
    )


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def test_looping_over_a_table_that_does_not_exist() -> None:
    assert codes('## S\n- for each row in "Ghost":\n  - screenshot\n') == ["script.unknown_table"]


def test_a_recorded_table_must_have_been_recorded_into_first() -> None:
    before = """
    ## S
    - for each row in "Log":
      - type "{{id}}"
    - screenshot
    - read "x" as v
    - record id={{v}} into "Log"
    """
    after = """
    ## S
    - screenshot
    - read "x" as v
    - record id={{v}} into "Log"
    - for each row in "Log":
      - type "{{id}}"
    - type table "Log"
    """
    assert codes(before) == ["script.table_not_yet_recorded"]
    assert errors(after) == []


def test_recording_inside_a_routine_counts_once_it_has_been_called() -> None:
    """Script 2 records icon files in a routine, then loops over them."""
    body = """
    ## S
    - do "note" with value="a"
    - for each row in "Notes":
      - type "{{value}}"

    ## Routine: note (value)
    - record value="{{value}}" into "Notes"
    """
    assert errors(body) == []


def test_a_recorded_table_keeps_its_columns() -> None:
    body = """
    ## S
    - record a="1" into "Log"
    - record b="2" into "Log"
    """
    assert codes(body) == ["script.record_columns"]


def test_a_declared_table_cannot_be_recorded_into() -> None:
    body = """
    Table: Fixed
    | a |
    |---|
    | 1 |

    ## S
    - record a="2" into "Fixed"
    - for each row in "Fixed":
      - type "{{a}}"
    """
    assert codes(body) == ["script.record_into_declared"]


def test_unused_tables_and_blocks_are_warnings() -> None:
    body = """
    Table: Spare
    | a |
    |---|
    | 1 |

    Block: spare
    ```
    x
    ```

    ## S
    - screenshot
    """
    assert set(warnings(body)) >= {"script.unused_table", "script.unused_block"}


def test_an_unknown_block() -> None:
    assert codes('## S\n- type block "ghost"\n') == ["script.unknown_block"]


# ---------------------------------------------------------------------------
# Terminals (§5.12)
# ---------------------------------------------------------------------------


def test_run_needs_a_terminal() -> None:
    assert codes("## S\n- run `ls`\n") == ["script.not_a_terminal"]
    assert codes("## S\nApp: Finder\n- run `ls`\n") == ["script.not_a_terminal"]
    assert errors("## S\nApp: Terminal\n- run `ls`\n") == []
    assert errors("## S\nApp: iTerm2\n- run `ls`\n") == []


def test_any_application_can_be_declared_a_terminal() -> None:
    body = "## S\nApp: Warp (terminal)\n- run `ls`\n- App: Finder\n- App: Warp\n- run `pwd`\n"
    assert errors(body) == []


def test_output_needs_a_terminal_too() -> None:
    assert codes('## S\nApp: Finder\n- expect output contains "x"\n') == ["script.not_a_terminal"]


def test_a_routine_that_runs_commands_must_name_its_terminal() -> None:
    body = """
    ## S
    App: Terminal
    - do "r"

    ## Routine: r ()
    - run `ls`
    """
    assert codes(body) == ["script.not_a_terminal"]


def test_after_a_call_the_application_is_whatever_the_routine_left() -> None:
    body = """
    ## S
    App: Finder
    - do "to terminal"
    - run `ls`

    ## Routine: to terminal ()
    - App: Terminal
    """
    assert errors(body) == []


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def test_a_key_held_and_never_released_is_a_warning() -> None:
    assert "script.held" in warnings("## S\n- key-down shift\n- left-click\n")
    assert "script.held" not in warnings("## S\n- key-down shift\n- left-click\n- key-up shift\n")
    assert "script.held" in warnings("## S\n- press-button left\n- move to 1,1\n")


def test_a_script_without_a_platform_is_a_warning() -> None:
    found = issues("## S\n- screenshot\n", platform=False)
    assert [i.code for i in found] == ["script.no_platform"]


def test_an_empty_stage_is_a_warning() -> None:
    assert "script.empty_stage" in warnings("## Nothing here\n\n## S\n- screenshot\n")
