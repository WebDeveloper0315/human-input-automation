"""Typing that is uneven and occasionally wrong, and still ends up right."""

from __future__ import annotations

import random

import pytest

from human_input_automation.core.actions import TypeText
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.errors import ValidationError
from human_input_automation.core.events import RunStatus
from human_input_automation.core.plan import AutomationPlan, RunOptions
from human_input_automation.core.timing import TimingProfile, TimingService
from human_input_automation.core.typing_style import (
    NEIGHBOURS,
    Hesitate,
    TypeChars,
    TypingStep,
    TypingStyle,
    Undo,
    plan_typing,
    replay,
)

from .fakes import FakeClock, FakeKeyboard, FakeMouse, FakeWindows, make_target

SAMPLE = "the quick brown fox\njumps over the lazy dog"


def plan(text: str, seed: int = 0, **style: float) -> tuple[TypingStep, ...]:
    return plan_typing(text, TypingStyle.natural(**style), random.Random(seed))


# ---------------------------------------------------------------------------
# The guarantee
# ---------------------------------------------------------------------------


def test_the_text_that_survives_is_always_the_text_that_was_asked_for() -> None:
    for seed in range(200):
        steps = plan(SAMPLE, seed, typo_rate=0.35, hesitation_rate=0.1)
        assert replay(steps) == SAMPLE, f"seed {seed}"


def test_a_correction_never_reaches_back_past_a_newline() -> None:
    """Backspacing over a newline would join two of the user's lines together."""
    for seed in range(200):
        typed: list[str] = []
        for step in plan(SAMPLE, seed, typo_rate=0.5):
            if isinstance(step, TypeChars):
                typed.extend(step.text)
            elif isinstance(step, Undo):
                removed = typed[len(typed) - step.count :]
                assert "\n" not in removed, f"seed {seed}"
                del typed[len(typed) - step.count :]


def test_a_slip_only_ever_types_characters_it_can_take_back() -> None:
    """No brackets or quotes: an editor answers those with a partner."""
    for seed in range(200):
        for step in plan(SAMPLE + ' f("x") [1] {2}', seed, typo_rate=0.6):
            if isinstance(step, TypeChars) and not step.intended:
                assert not set(step.text) & set("()[]{}\"'`\n")


def test_only_letters_are_mistyped() -> None:
    steps = plan("12 34 +-=.,;", 0, typo_rate=1.0)
    assert steps == (TypeChars("12 34 +-=.,;"),)


def test_a_substitution_lands_on_a_neighbouring_key() -> None:
    """Not a random letter: a finger one key off, which is what people do."""
    slips = {
        step.text[0]
        for seed in range(60)
        for step in plan("a", seed, typo_rate=1.0)
        if isinstance(step, TypeChars) and not step.intended
    }
    assert slips
    assert slips <= set(NEIGHBOURS["a"] + "a")  # a neighbour, or "a" doubled


def test_case_is_preserved_when_a_letter_is_substituted() -> None:
    slips = {
        step.text[0]
        for seed in range(60)
        for step in plan("A", seed, typo_rate=1.0)
        if isinstance(step, TypeChars) and not step.intended
    }
    assert slips
    assert all(char.isupper() for char in slips)


# ---------------------------------------------------------------------------
# Shape of the plan
# ---------------------------------------------------------------------------


def test_typing_exactly_is_one_step_and_no_decisions() -> None:
    assert plan_typing("hello", TypingStyle()) == (TypeChars("hello"),)
    assert plan_typing("", TypingStyle()) == ()


def test_a_mistake_is_noticed_and_then_undone() -> None:
    steps = plan("abcdef", 3, typo_rate=1.0, hesitation_rate=0.0)
    kinds = [type(step).__name__ for step in steps]
    assert "Undo" in kinds
    # Every slip is followed by a pause and then exactly enough backspaces.
    for index, step in enumerate(steps):
        if isinstance(step, TypeChars) and not step.intended:
            assert isinstance(steps[index + 1], Hesitate)
            undo = steps[index + 2]
            assert isinstance(undo, Undo)
            assert undo.count == len(step.text)


def test_the_same_seed_gives_the_same_keystrokes() -> None:
    style = TypingStyle.natural(typo_rate=0.3, hesitation_rate=0.2)
    first = plan_typing(SAMPLE, style, random.Random(99))
    second = plan_typing(SAMPLE, style, random.Random(99))
    assert first == second
    assert plan_typing(SAMPLE, style, random.Random(100)) != first


def test_hesitations_stay_inside_their_configured_range() -> None:
    style = TypingStyle(hesitation_rate=1.0, hesitation_ms=400, hesitation_jitter_ms=100)
    pauses = [
        step.duration_ms
        for step in plan_typing("abcdef", style, random.Random(5))
        if isinstance(step, Hesitate)
    ]
    assert len(pauses) == 6
    assert all(300 <= pause <= 500 for pause in pauses)


def test_a_pause_is_never_negative_however_large_the_jitter() -> None:
    style = TypingStyle(hesitation_rate=1.0, hesitation_ms=10, hesitation_jitter_ms=5_000)
    pauses = [
        step.duration_ms
        for step in plan_typing("abcdef" * 20, style, random.Random(1))
        if isinstance(step, Hesitate)
    ]
    assert pauses and min(pauses) >= 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_the_default_style_types_exactly() -> None:
    assert TypingStyle().is_exact
    assert not TypingStyle.natural().is_exact
    assert not TypingStyle(hesitation_rate=0.1).is_exact


@pytest.mark.parametrize(
    "changes",
    [
        {"typo_rate": 1.5},
        {"typo_rate": -0.1},
        {"hesitation_rate": 2.0},
        {"notice_pause_ms": -1.0},
        {"correction_pause_jitter_ms": -5.0},
        {"typo_notice_chars": 9},
        {"typo_notice_chars": -1},
    ],
)
def test_impossible_settings_are_rejected(changes: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        TypingStyle(**changes)  # type: ignore[arg-type]


def test_the_timing_service_carries_the_style_and_shares_its_generator() -> None:
    style = TypingStyle.natural()
    service = TimingService(TimingProfile(), style=style, seed=7)
    assert service.style is style
    assert service.rng is not None
    # One seed, one generator: delays and mistakes are reproducible together.
    other = TimingService(TimingProfile(), style=style, seed=7)
    assert service.char_delay_ms("a") == other.char_delay_ms("a")


# ---------------------------------------------------------------------------
# Through the engine
# ---------------------------------------------------------------------------


def test_a_run_with_mistakes_types_backspaces_and_ends_on_the_right_text() -> None:
    keyboard = FakeKeyboard()
    engine = AutomationEngine(
        keyboard=keyboard, mouse=FakeMouse(), windows=FakeWindows(), clock=FakeClock()
    )
    report = engine.run(
        AutomationPlan(
            make_target(),
            [TypeText(text="the quick brown fox")],
            timing=TimingProfile.instant(),
            typing=TypingStyle.natural(typo_rate=0.5),
            options=RunOptions(seed=4),
        )
    )

    assert report.status is RunStatus.COMPLETED
    assert "backspace" in [value for name, value in keyboard.calls if name == "key_down"]
    assert _apply(keyboard.calls) == "the quick brown fox"


def test_typing_exactly_still_takes_the_one_call_fast_path() -> None:
    keyboard = FakeKeyboard()
    engine = AutomationEngine(
        keyboard=keyboard, mouse=FakeMouse(), windows=FakeWindows(), clock=FakeClock()
    )
    engine.run(
        AutomationPlan(
            make_target(), [TypeText(text="hello")], timing=TimingProfile.instant()
        )
    )
    assert keyboard.calls == [("type_text", "hello")]


def test_a_plan_with_mistakes_enabled_says_so_before_it_runs() -> None:
    result = AutomationEngine(
        keyboard=FakeKeyboard(), mouse=FakeMouse(), windows=FakeWindows(), clock=FakeClock()
    ).validate(
        AutomationPlan(
            make_target(), [TypeText(text="hi")], typing=TypingStyle.natural(typo_rate=0.1)
        )
    )
    codes = [issue.code for issue in result.warnings]
    assert "plan.typing_mistakes" in codes
    assert result.ok


def _apply(calls: list[tuple[str, str]]) -> str:
    """The text a recorded key sequence leaves behind."""
    buffer: list[str] = []
    for name, value in calls:
        if name == "type_text":
            buffer.extend(value)
        elif name == "key_down" and value == "backspace":
            buffer.pop()
    return "".join(buffer)
