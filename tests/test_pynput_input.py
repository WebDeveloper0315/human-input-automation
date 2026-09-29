"""The pynput input adapter, driven by a fake pynput module.

These tests exercise the adapter's own logic - key translation, movement
interpolation, duration accuracy, cancellation - without pynput and without a
desktop. Whether the resulting events actually reach an application is a
platform question, recorded in docs/PHASE3-PLATFORM-REPORT.md.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from human_input_automation.adapters.pynput_input import MOVE_STEP_MS, PynputKeyboard, PynputMouse
from human_input_automation.adapters.x11_typing import XTestTyper, keysym_for
from human_input_automation.core.errors import AdapterUnavailableError
from human_input_automation.core.keys import Key, MouseButton


class FakeKeyboardController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def type(self, text: str) -> None:
        self.calls.append(("type", text))

    def press(self, key: Any) -> None:
        self.calls.append(("press", key))

    def release(self, key: Any) -> None:
        self.calls.append(("release", key))


class FakeMouseController:
    def __init__(self) -> None:
        self.positions: list[tuple[int, int]] = []
        self.calls: list[tuple[str, Any]] = []
        self._position = (0, 0)

    @property
    def position(self) -> tuple[int, int]:
        return self._position

    @position.setter
    def position(self, value: tuple[int, int]) -> None:
        self._position = value
        self.positions.append(value)

    def press(self, button: Any) -> None:
        self.calls.append(("press", button))

    def release(self, button: Any) -> None:
        self.calls.append(("release", button))


def keyboard_module() -> SimpleNamespace:
    names = {key.value for key in Key} - {"meta"} | {"cmd"}
    controller = FakeKeyboardController()
    return SimpleNamespace(
        Key=SimpleNamespace(**{name: f"<Key.{name}>" for name in names}),
        KeyCode=SimpleNamespace(from_char=lambda char: f"<KeyCode {char}>"),
        Controller=lambda: controller,
        _controller=controller,
    )


def mouse_module() -> SimpleNamespace:
    controller = FakeMouseController()
    return SimpleNamespace(
        Button=SimpleNamespace(left="<left>", right="<right>", middle="<middle>"),
        Controller=lambda: controller,
        _controller=controller,
    )


class StopAfter:
    """CancelToken that reports a stop after ``count`` checks."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.checks = 0

    def is_stop_requested(self) -> bool:
        self.checks += 1
        return self.checks > self.count

    def wait_for_stop(self, timeout: float) -> bool:
        return self.is_stop_requested()


# -- keyboard -------------------------------------------------------------
def test_text_is_typed_through_the_controller() -> None:
    module = keyboard_module()
    PynputKeyboard(module).type_text("hello")
    assert module._controller.calls == [("type", "hello")]


def test_named_keys_and_characters_are_translated() -> None:
    module = keyboard_module()
    adapter = PynputKeyboard(module)
    adapter.key_down(Key.ENTER)
    adapter.key_up("a")
    assert module._controller.calls == [("press", "<Key.enter>"), ("release", "<KeyCode a>")]


def test_the_command_modifier_is_not_control() -> None:
    module = keyboard_module()
    PynputKeyboard(module).key_down(Key.META)
    assert module._controller.calls == [("press", "<Key.cmd>")]


def test_a_key_missing_from_the_backend_raises_before_pressing_anything() -> None:
    module = keyboard_module()
    del module.Key.insert
    adapter = PynputKeyboard(module)
    with pytest.raises(AdapterUnavailableError):
        adapter.key_down(Key.INSERT)
    assert module._controller.calls == []


def test_backend_name_is_reported_for_diagnostics() -> None:
    module = keyboard_module()
    assert PynputKeyboard(module).backend_name


class FakeDisplay:
    """A US layout: letters and digits plain, capitals and ``!`` with Shift."""

    SHIFT = 50

    def __init__(self) -> None:
        self.synced = 0

    def keysym_to_keycodes(self, keysym: int) -> list[tuple[int, int]]:
        char = chr(keysym) if keysym < 0x100 else ""
        if char.islower() or char.isdigit() or char == " ":
            return [(100 + ord(char.upper()) % 50, 0)]
        if char.isupper():
            return [(100 + ord(char) % 50, 1)]
        if char == "!":
            return [(10, 1)]
        if keysym == 0xFF0D:
            return [(36, 0)]
        return []

    def keysym_to_keycode(self, keysym: int) -> int:
        return self.SHIFT if keysym == 0xFFE1 else 0

    def sync(self) -> None:
        self.synced += 1


class FakeXTest:
    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []

    def fake_input(self, display: Any, kind: int, keycode: int) -> None:
        self.events.append(("down" if kind == 2 else "up", keycode))


def test_xtest_types_a_character_on_its_own_key() -> None:
    xtest = FakeXTest()
    assert XTestTyper(FakeDisplay(), xtest).type_char("a")
    assert xtest.events == [("down", 115), ("up", 115)]


def test_xtest_holds_shift_only_around_a_shifted_character() -> None:
    xtest = FakeXTest()
    typer = XTestTyper(FakeDisplay(), xtest)
    assert typer.type_char("A") and typer.type_char("!")
    shift = FakeDisplay.SHIFT
    assert xtest.events == [
        ("down", shift), ("down", 115), ("up", 115), ("up", shift),
        ("down", shift), ("down", 10), ("up", 10), ("up", shift),
    ]  # fmt: skip


def test_xtest_leaves_what_the_layout_cannot_type_to_the_fallback() -> None:
    xtest = FakeXTest()
    assert not XTestTyper(FakeDisplay(), xtest).type_char("한")
    assert xtest.events == []


def test_a_newline_is_the_return_key() -> None:
    assert keysym_for("\n") == 0xFF0D and keysym_for("é") == 0xE9
    assert keysym_for("한") == 0x01000000 | ord("한")


def test_on_x11_characters_go_through_xtest_and_the_rest_through_pynput() -> None:
    module = keyboard_module()
    xtest = FakeXTest()
    PynputKeyboard(module, typer=XTestTyper(FakeDisplay(), xtest)).type_text("a한")
    assert xtest.events == [("down", 115), ("up", 115)]
    assert module._controller.calls == [("type", "한")]


def test_on_x11_the_letter_of_a_shortcut_goes_through_xtest_too() -> None:
    """``ctrl+d``: Control is a named key for pynput, ``d`` is pressed through XTEST."""
    module = keyboard_module()
    xtest = FakeXTest()
    adapter = PynputKeyboard(module, typer=XTestTyper(FakeDisplay(), xtest))
    adapter.key_down(Key.CTRL)
    adapter.key_down("d")
    adapter.key_up("d")
    adapter.key_up(Key.CTRL)
    assert xtest.events == [("down", 118), ("up", 118)]
    assert module._controller.calls == [("press", "<Key.ctrl>"), ("release", "<Key.ctrl>")]


# -- mouse ----------------------------------------------------------------
def test_zero_duration_moves_in_one_write() -> None:
    module = mouse_module()
    PynputMouse(module).move_to(100, 200, 0)
    assert module._controller.positions == [(100, 200)]


def test_movement_is_interpolated_and_ends_exactly_on_target() -> None:
    module = mouse_module()
    PynputMouse(module).move_to(80, 40, 40)
    positions = module._controller.positions
    assert len(positions) == int(40 / MOVE_STEP_MS)
    assert positions[-1] == (80, 40)
    assert positions[0] != (80, 40), "movement should be gradual, not a jump"
    assert [p[0] for p in positions] == sorted(p[0] for p in positions)


def test_movement_takes_approximately_the_requested_duration() -> None:
    module = mouse_module()
    started = time.monotonic()
    PynputMouse(module).move_to(300, 300, 120)
    elapsed_ms = (time.monotonic() - started) * 1000
    assert 100 <= elapsed_ms <= 400, f"expected ~120 ms, took {elapsed_ms:.0f} ms"


def test_a_stop_request_abandons_the_movement_immediately() -> None:
    module = mouse_module()
    cancel = StopAfter(2)
    started = time.monotonic()
    PynputMouse(module).move_to(1000, 1000, 5_000, cancel)
    elapsed_ms = (time.monotonic() - started) * 1000
    assert elapsed_ms < 500, "a stop must not wait out a 5 second movement"
    assert module._controller.positions[-1] != (1000, 1000)


def test_relative_movement_starts_from_the_current_position() -> None:
    module = mouse_module()
    adapter = PynputMouse(module)
    adapter.move_to(100, 100, 0)
    adapter.move_by(10, -20, 0)
    assert module._controller.positions[-1] == (110, 80)


def test_position_is_returned_as_integers() -> None:
    module = mouse_module()
    module._controller._position = (10.7, 20.2)
    assert PynputMouse(module).position() == (10, 20)


def test_buttons_are_translated() -> None:
    module = mouse_module()
    adapter = PynputMouse(module)
    adapter.button_down(MouseButton.RIGHT)
    adapter.button_up(MouseButton.MIDDLE)
    assert module._controller.calls == [("press", "<right>"), ("release", "<middle>")]


def test_a_button_missing_from_the_backend_raises_an_adapter_error() -> None:
    module = mouse_module()
    del module.Button.middle
    with pytest.raises(AdapterUnavailableError):
        PynputMouse(module).button_down(MouseButton.MIDDLE)


def test_movement_can_be_cancelled_from_another_thread() -> None:
    module = mouse_module()
    stop = threading.Event()

    class EventToken:
        def is_stop_requested(self) -> bool:
            return stop.is_set()

        def wait_for_stop(self, timeout: float) -> bool:
            return stop.wait(timeout)

    threading.Timer(0.05, stop.set).start()
    started = time.monotonic()
    PynputMouse(module).move_to(2000, 2000, 10_000, EventToken())
    assert (time.monotonic() - started) < 2.0
