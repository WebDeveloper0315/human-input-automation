"""Key and button translation - the one place platform key knowledge lives."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from human_input_automation.adapters.keymap import (
    is_key_supported,
    pynput_key_name,
    resolve_button,
    resolve_key,
    unsupported_buttons,
    unsupported_keys,
)
from human_input_automation.core.errors import AdapterUnavailableError
from human_input_automation.core.keys import Key, MouseButton
from human_input_automation.core.target import PlatformName


class FakePynputKey:
    """Stands in for ``pynput.keyboard.Key`` with a chosen set of members."""

    def __init__(self, names: set[str]) -> None:
        for name in names:
            setattr(self, name, f"<Key.{name}>")


class FakeKeyCode:
    @staticmethod
    def from_char(char: str) -> str:
        return f"<KeyCode {char}>"


def keyboard_module(names: set[str] | None = None) -> SimpleNamespace:
    default = {key.value for key in Key} - {"meta"} | {"cmd"}
    return SimpleNamespace(Key=FakePynputKey(names or default), KeyCode=FakeKeyCode)


def test_our_names_match_pynput_except_the_command_modifier() -> None:
    for key in Key:
        expected = "cmd" if key is Key.META else key.value
        assert pynput_key_name(key) == expected


def test_meta_is_never_translated_to_control() -> None:
    """Command/Win/Super must not silently become Ctrl."""
    assert pynput_key_name(Key.META) == "cmd"
    assert pynput_key_name(Key.CTRL) == "ctrl"
    assert pynput_key_name(Key.META) != pynput_key_name(Key.CTRL)


def test_named_keys_resolve_to_backend_key_objects() -> None:
    module = keyboard_module()
    assert resolve_key(module, Key.ENTER) == "<Key.enter>"
    assert resolve_key(module, Key.META) == "<Key.cmd>"
    assert resolve_key(module, Key.PAGE_UP) == "<Key.page_up>"


def test_single_characters_become_key_codes() -> None:
    module = keyboard_module()
    assert resolve_key(module, "a") == "<KeyCode a>"
    assert resolve_key(module, "$") == "<KeyCode $>"


def test_multi_character_strings_are_refused_before_reaching_pynput() -> None:
    """pynput itself raises ValueError for these; we fail with a clear message."""
    with pytest.raises(AdapterUnavailableError) as excinfo:
        resolve_key(keyboard_module(), "enter")
    assert "single character" in str(excinfo.value)


def test_a_key_the_backend_lacks_raises_a_named_adapter_error() -> None:
    module = keyboard_module(names={"enter"})
    with pytest.raises(AdapterUnavailableError) as excinfo:
        resolve_key(module, Key.INSERT)
    assert "insert" in str(excinfo.value)


def test_macos_is_the_only_platform_missing_insert() -> None:
    """Verified against pynput's per-backend Key enums (see the Phase 3 report)."""
    assert unsupported_keys(PlatformName.MACOS) == frozenset({Key.INSERT})
    assert unsupported_keys(PlatformName.WINDOWS) == frozenset()
    assert unsupported_keys(PlatformName.LINUX) == frozenset()


@pytest.mark.parametrize("platform", list(PlatformName))
def test_key_support_is_answered_for_every_platform(platform: PlatformName) -> None:
    assert is_key_supported(Key.ENTER, platform)
    assert is_key_supported("a", platform)
    assert is_key_supported(Key.INSERT, platform) is (platform is not PlatformName.MACOS)


@pytest.mark.parametrize("platform", list(PlatformName))
def test_all_three_buttons_are_available_everywhere(platform: PlatformName) -> None:
    assert unsupported_buttons(platform) == frozenset()


def test_buttons_resolve_and_missing_ones_raise() -> None:
    module = SimpleNamespace(Button=SimpleNamespace(left="L", right="R", middle="M"))
    assert resolve_button(module, MouseButton.LEFT) == "L"
    assert resolve_button(module, MouseButton.MIDDLE) == "M"

    poor = SimpleNamespace(Button=SimpleNamespace(left="L"))
    with pytest.raises(AdapterUnavailableError):
        resolve_button(poor, MouseButton.RIGHT)
