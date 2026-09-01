"""Key vocabulary: normalisation, aliases and shortcut parsing."""

from __future__ import annotations

import pytest

from human_input_automation.core.errors import ValidationError
from human_input_automation.core.keys import (
    Key,
    format_key,
    is_modifier,
    normalize_key,
    parse_shortcut,
)


def test_named_keys_are_normalised_case_insensitively() -> None:
    assert normalize_key("ENTER") is Key.ENTER
    assert normalize_key("Page Up") is Key.PAGE_UP
    assert normalize_key("page-down") is Key.PAGE_DOWN


@pytest.mark.parametrize("alias", ["cmd", "command", "super", "win", "windows"])
def test_platform_command_modifier_aliases_map_to_meta(alias: str) -> None:
    assert normalize_key(alias) is Key.META


def test_single_characters_are_kept_as_characters() -> None:
    assert normalize_key("a") == "a"
    assert normalize_key("$") == "$"


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        normalize_key("frobnicate")
    assert excinfo.value.issues[0].code == "key.unknown"


def test_parse_shortcut_splits_and_normalises() -> None:
    assert parse_shortcut("ctrl+shift+p") == (Key.CTRL, Key.SHIFT, "p")


def test_parse_shortcut_supports_literal_plus() -> None:
    assert parse_shortcut("ctrl++") == (Key.CTRL, "+")


def test_parse_shortcut_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        parse_shortcut("+")


def test_modifier_detection_and_formatting() -> None:
    assert is_modifier(Key.CTRL)
    assert not is_modifier("a")
    assert format_key(Key.ENTER) == "enter"
    assert format_key("a") == "a"
