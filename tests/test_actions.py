"""Action model: construction rules and invalid-state rejection."""

from __future__ import annotations

import pytest

from human_input_automation.core.actions import (
    KeyPress,
    MouseClick,
    MouseMove,
    Shortcut,
    TypeText,
    Wait,
)
from human_input_automation.core.errors import ValidationError
from human_input_automation.core.keys import Key, MouseButton


def test_type_text_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        TypeText(text="")


def test_key_press_normalises_key_and_rejects_zero_count() -> None:
    assert KeyPress(key="enter").key is Key.ENTER
    with pytest.raises(ValidationError):
        KeyPress(key="a", count=0)


def test_shortcut_parses_and_splits_modifiers_from_main_key() -> None:
    shortcut = Shortcut.parse("ctrl+shift+p")
    assert shortcut.modifiers == (Key.CTRL, Key.SHIFT)
    assert shortcut.main_key == "p"


def test_shortcut_rejects_empty_and_oversized_chords() -> None:
    with pytest.raises(ValidationError):
        Shortcut(keys=())
    with pytest.raises(ValidationError):
        Shortcut(keys=tuple("abcdefg"))


def test_mouse_move_rejects_negative_absolute_coordinates() -> None:
    with pytest.raises(ValidationError):
        MouseMove(x=-1, y=10)
    assert MouseMove(x=-5, y=-5, relative=True).relative


def test_mouse_click_requires_both_coordinates_or_neither() -> None:
    with pytest.raises(ValidationError):
        MouseClick(button=MouseButton.LEFT, x=10)
    assert MouseClick(button=MouseButton.RIGHT).position is None
    assert MouseClick(x=3, y=4).position == (3, 4)


def test_wait_and_delay_overrides_reject_negative_durations() -> None:
    with pytest.raises(ValidationError):
        Wait(duration_ms=-1)
    with pytest.raises(ValidationError):
        Wait(duration_ms=10, delay_after_ms=-5)


def test_actions_describe_themselves_for_logs_and_dry_runs() -> None:
    assert "hello" in TypeText(text="hello").describe()
    assert Shortcut.parse("ctrl+s").describe() == "shortcut ctrl+s"
    assert MouseClick(button=MouseButton.MIDDLE, x=1, y=2).describe() == "middle click at (1, 2)"
    assert Wait(duration_ms=250).describe() == "wait 250 ms"


def test_actions_are_immutable() -> None:
    action = TypeText(text="hello")
    with pytest.raises(Exception):
        action.text = "other"  # type: ignore[misc]
