"""Fake adapters used by the test suite.

Every test in this suite runs against these fakes, so the whole core is
exercised without a real desktop, without pynput and without a display server.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from human_input_automation.core.keys import KeyLike, MouseButton, format_key
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

    def activate(self, target: TargetWindow) -> bool:
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
