"""Fake adapters used by the test suite.

Every test in this suite runs against these fakes, so the whole core is
exercised without a real desktop, without pynput and without a display server.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from human_input_automation.core.actions import AUTO_CLOSED_PAIRS as _CLOSERS
from human_input_automation.core.keys import Key, KeyLike, MouseButton, format_key
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    TargetWindow,
    WindowCapabilities,
)
from human_input_automation.ports.clock import CancelToken


class FakeClock:
    """Virtual clock: records sleeps and advances instantly.

    ``on_sleep`` runs after each sleep is recorded, which lets a test request a
    stop at an exact point in the run without threads or real waiting.
    """

    def __init__(self, on_sleep: Callable[[FakeClock], None] | None = None) -> None:
        self.now = 0.0
        self.sleeps_ms: list[float] = []
        self.on_sleep = on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep_ms(self, milliseconds: float, cancel: CancelToken | None = None) -> bool:
        self.sleeps_ms.append(milliseconds)
        if cancel is not None and cancel.is_stop_requested():
            return True
        self.now += milliseconds / 1000.0
        if self.on_sleep is not None:
            self.on_sleep(self)
        return bool(cancel is not None and cancel.is_stop_requested())

    @property
    def total_ms(self) -> float:
        return sum(self.sleeps_ms)


@dataclass
class FakeKeyboard:
    """Keyboard port that records every call."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    fail_on: str | None = None

    def type_text(self, text: str) -> None:
        self._record("type_text", text)

    def key_down(self, key: KeyLike) -> None:
        self._record("key_down", format_key(key))

    def key_up(self, key: KeyLike) -> None:
        self._record("key_up", format_key(key))

    def _record(self, name: str, value: str) -> None:
        if self.fail_on == name:
            raise RuntimeError(f"fake keyboard failure in {name}")
        self.calls.append((name, value))

    @property
    def typed(self) -> str:
        return "".join(value for name, value in self.calls if name == "type_text")

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@dataclass
class FakeMouse:
    """Mouse port that records every call."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    durations_ms: list[float] = field(default_factory=list)
    _position: tuple[int, int] = (0, 0)

    def position(self) -> tuple[int, int]:
        return self._position

    def move_to(
        self, x: int, y: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        self._position = (x, y)
        self.calls.append(("move_to", f"{x},{y}"))
        self.durations_ms.append(duration_ms)

    def move_by(
        self, dx: int, dy: int, duration_ms: float, cancel: CancelToken | None = None
    ) -> None:
        self._position = (self._position[0] + dx, self._position[1] + dy)
        self.calls.append(("move_by", f"{dx},{dy}"))
        self.durations_ms.append(duration_ms)

    def button_down(self, button: MouseButton) -> None:
        self.calls.append(("button_down", button.value))

    def button_up(self, button: MouseButton) -> None:
        self.calls.append(("button_up", button.value))

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@dataclass
class FakeWindows:
    """Window discovery/control with configurable outcomes."""

    windows: list[TargetWindow] = field(default_factory=list)
    activate_result: bool = True
    active_result: bool | None = True
    calls: list[str] = field(default_factory=list)

    def list_windows(self) -> Sequence[TargetWindow]:
        return list(self.windows)

    def find(self, handle: str) -> TargetWindow | None:
        return next((w for w in self.windows if w.handle == handle), None)

    def activate(self, target: TargetWindow, cancel: object = None) -> bool:
        self.calls.append(f"activate:{target.handle}")
        return self.activate_result

    def is_active(self, target: TargetWindow) -> bool | None:
        self.calls.append(f"is_active:{target.handle}")
        return self.active_result


def make_target(
    handle: str = "win-1",
    title: str = "Test Window",
    capabilities: WindowCapabilities | None = None,
) -> TargetWindow:
    """A fully capable target on a fictional fully capable platform."""
    return TargetWindow(
        handle=handle,
        title=title,
        platform=PlatformName.LINUX,
        display_server=DisplayServer.X11,
        process_name="test-app",
        process_id=4242,
        capabilities=capabilities or WindowCapabilities.full(),
    )


@dataclass
class FakeHotkey:
    """Hotkey port that records registration and can be fired by a test."""

    description_text: str = "Ctrl+Shift+F9"
    can_register: bool = True
    callback: Callable[[], None] | None = None
    stopped: bool = False

    @property
    def description(self) -> str:
        return self.description_text

    @property
    def is_active(self) -> bool:
        return self.callback is not None and not self.stopped

    def start(self, on_trigger: Callable[[], None]) -> bool:
        if not self.can_register:
            return False
        self.callback = on_trigger
        self.stopped = False
        return True

    def stop(self) -> None:
        self.stopped = True

    def trigger(self) -> None:
        """Simulate the hotkey firing from the listener's own thread."""
        if self.callback is not None:
            self.callback()


#: What the editor closes for you: brackets, and quotes that close themselves.
_PAIRS = {**_CLOSERS, '"': '"', "'": "'"}


class FakeEditor:
    """A small model of a code editor, used as a keyboard port.

    Real editors edit while you type. This one reproduces the three behaviours
    that make typing code into one different from typing into a text box:

    * **auto-indent** - Enter starts the new line at the previous line's
      indentation, one level deeper after a line that ends with an opening
      bracket, and splits an empty pair across three lines;
    * **auto-closing brackets** - an opening bracket inserts its partner to the
      right of the caret, and typing that partner yourself moves over it instead
      of inserting a second one;
    * **completion** - after a few letters a suggestion is offered, and Enter
      accepts it rather than inserting a newline.

    It is a model, not a copy: it stands in for VS Code closely enough to prove
    the compensations in :func:`~human_input_automation.core.handlers
    .handle_type_code` do what they claim, and no more than that. What a
    particular editor really does still has to be checked in that editor.

    Each behaviour can be switched off, so the same tests also cover a plain
    editor that does none of this.
    """

    #: Appended to the current word when a suggestion is accepted.
    COMPLETION = "_completed"

    def __init__(
        self,
        *,
        auto_indent: bool = True,
        auto_close: bool = True,
        auto_complete: bool = True,
        indent_unit: str = "    ",
        text: str = "",
    ) -> None:
        self.lines = text.split("\n")
        self.row = len(self.lines) - 1
        self.col = len(self.lines[-1])
        self.auto_indent = auto_indent
        self.auto_close = auto_close
        self.auto_complete = auto_complete
        self.indent_unit = indent_unit
        self.anchor: tuple[int, int] | None = None
        self.held: set[KeyLike] = set()
        #: Closers the editor inserted, innermost last, sitting right of the caret.
        self.auto_closed: list[str] = []
        self.suggesting = False
        self.in_comment = False
        self.completions_accepted = 0

    # -- KeyboardPort ------------------------------------------------------
    def type_text(self, text: str) -> None:
        for char in text:
            # A typed newline is the Enter key, which is how pynput sends it and
            # why plain typing meets the auto-indent at all.
            if char == "\n":
                self._enter()
            elif char == "\t":
                self._tab()
            else:
                self._insert(char)

    def key_down(self, key: KeyLike) -> None:
        self.held.add(key)
        if key in (Key.SHIFT, Key.CTRL, Key.ALT, Key.META):
            return
        self._press(key)

    def key_up(self, key: KeyLike) -> None:
        self.held.discard(key)

    # -- inspection --------------------------------------------------------
    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def line(self) -> str:
        return self.lines[self.row]

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return self.text

    # -- editing -----------------------------------------------------------
    def _press(self, key: KeyLike) -> None:
        if key is Key.ENTER:
            self._enter()
        elif key is Key.BACKSPACE:
            self._backspace()
        elif key is Key.DELETE:
            self._delete()
        elif key is Key.HOME:
            self._home()
        elif key is Key.END:
            self._move(self.row, len(self.line))
        elif key is Key.LEFT:
            self._move(self.row, max(0, self.col - 1))
        elif key is Key.RIGHT:
            self._move(self.row, min(len(self.line), self.col + 1))
        elif key is Key.ESC:
            self.anchor = None
            self.suggesting = False
        else:
            raise AssertionError(f"the editor model does not know the {key!r} key")

    def _tab(self) -> None:
        """Tab accepts a suggestion when one is offered, and indents otherwise."""
        if self.suggesting:
            self.type_text(self.COMPLETION)
            self.completions_accepted += 1
            self.suggesting = False
            return
        for char in self.indent_unit:
            self._insert(char)

    def _insert(self, char: str) -> None:
        self._delete_selection()
        # Typing a closer the editor already inserted moves over it.
        if (
            self.auto_close
            and self.auto_closed
            and char == self.auto_closed[-1]
            and self.line[self.col : self.col + 1] == char
        ):
            self.auto_closed.pop()
            self.col += 1
            self.suggesting = False
            return
        starts_comment = char == "#" or (char == "/" and self.line[self.col - 1 : self.col] == "/")
        if starts_comment and not self._in_string:
            self.in_comment = True
        self._write(char)
        self.col += 1
        if self.auto_close and char in _PAIRS and not self._in_string and not self.in_comment:
            self._write(_PAIRS[char])
            self.auto_closed.append(_PAIRS[char])
        self.suggesting = self.auto_complete and char.isalpha() and len(self._word()) >= 2

    @property
    def _in_string(self) -> bool:
        """Inside a quote the editor opened - where it stops closing brackets."""
        return bool(self.auto_closed) and self.auto_closed[-1] in "\"'`"

    def _enter(self) -> None:
        if self.suggesting:
            # The suggestion widget swallows Enter and completes the word.
            self.type_text(self.COMPLETION)
            self.completions_accepted += 1
            self.suggesting = False
            return
        self._delete_selection()
        before, after = self.line[: self.col], self.line[self.col :]
        indent = before[: len(before) - len(before.lstrip())] if self.auto_indent else ""
        opener = before.rstrip()[-1:] if self.auto_indent else ""
        deeper = indent + self.indent_unit if opener in _CLOSERS and opener else indent

        self.lines[self.row] = before
        if opener in _CLOSERS and opener and after[:1] == _CLOSERS[opener]:
            # An empty pair opens out over three lines, closer on its own line.
            self.lines[self.row + 1 : self.row + 1] = [deeper, indent + after]
        else:
            self.lines[self.row + 1 : self.row + 1] = [deeper + after]
        self.row += 1
        self.col = len(deeper)
        self.auto_closed.clear()
        self.suggesting = False
        self.in_comment = False

    def _backspace(self) -> None:
        if self._delete_selection():
            return
        if self.col > 0:
            previous = self.line[self.col - 1]
            partner = _PAIRS.get(previous)
            if (
                self.auto_close
                and partner is not None
                and self.line[self.col : self.col + 1] == partner
                and self.auto_closed[-1:] == [partner]
            ):
                self.lines[self.row] = self.line[: self.col - 1] + self.line[self.col + 1 :]
                self.auto_closed.pop()
            else:
                self.lines[self.row] = self.line[: self.col - 1] + self.line[self.col :]
            self.col -= 1
        elif self.row > 0:
            joined = self.lines.pop(self.row)
            self.row -= 1
            self.col = len(self.line)
            self.lines[self.row] += joined
        self.suggesting = False

    def _delete(self) -> None:
        if self._delete_selection():
            return
        if self.col < len(self.line):
            removed = self.line[self.col]
            self.lines[self.row] = self.line[: self.col] + self.line[self.col + 1 :]
            if self.auto_closed[-1:] == [removed]:
                self.auto_closed.pop()
        elif self.row < len(self.lines) - 1:
            self.lines[self.row] += self.lines.pop(self.row + 1)
        self.suggesting = False

    def _home(self) -> None:
        line = self.line
        first = len(line) - len(line.lstrip())
        self._move(self.row, 0 if self.col == first else first)

    def _move(self, row: int, col: int) -> None:
        if Key.SHIFT in self.held:
            if self.anchor is None:
                self.anchor = (self.row, self.col)
        else:
            self.anchor = None
        self.row, self.col = row, col
        self.auto_closed.clear()
        self.suggesting = False
        self.in_comment = False

    def _delete_selection(self) -> bool:
        if self.anchor is None or self.anchor == (self.row, self.col):
            self.anchor = None
            return False
        (start_row, start_col), (end_row, end_col) = sorted([self.anchor, (self.row, self.col)])
        tail = self.lines[end_row][end_col:]
        self.lines[start_row] = self.lines[start_row][:start_col] + tail
        del self.lines[start_row + 1 : end_row + 1]
        self.row, self.col = start_row, start_col
        self.anchor = None
        self.auto_closed.clear()
        return True

    def _word(self) -> str:
        prefix = self.line[: self.col]
        return prefix[len(prefix.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")) :]

    def _write(self, char: str) -> None:
        self.lines[self.row] = self.line[: self.col] + char + self.line[self.col :]
