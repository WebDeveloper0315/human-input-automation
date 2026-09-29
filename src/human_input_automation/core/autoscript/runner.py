"""Performing a checked script, one step at a time.

A script is not compiled into a plan up front: what `read output` returns, or
which window an `App:` line lands on, is only known when the step is reached.
So this interprets the script, and every step that moves or presses something
becomes an ordinary action handed to the engine's own handlers. Typing style,
the curved pointer path, held-key release and the emergency stop are therefore
exactly the ones a plan gets - there is no second implementation of input here.

Two rules keep a script from sending input where it should not, and both are
checked immediately before **every** step that sends any:

* **Never into the program running the script.** Keystrokes sent to the
  terminal a runner was started from sit in its input buffer and run in the
  user's shell once the run ends. Windows owned by this process or anything
  above it - the shell, the terminal, the editor - are never targets, and focus
  landing on one stops the run.
* **Only into the application the script is in.** After `App: Terminal`, focus
  must still be in Terminal. A dialog, a menu or a sheet of that application is
  fine; another application's window is not, and stops the run. The one
  exception is the operating system's own surfaces - Spotlight, the menu bar -
  which a person types into on the way to somewhere else.

Steps that need to look at the screen (`screenshot`, `find`, reading a label)
are roadmap 8.3. A script that uses one is refused before anything is sent,
naming each line, rather than failing half way through.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ...ports.applications import ApplicationPort
from ...ports.clock import Clock
from ...ports.input import KeyboardPort, MousePort
from ...ports.terminal import TerminalPort
from ...ports.window import WindowControlPort, WindowDiscoveryPort
from ..actions import Action, KeyDown, KeyPress, KeyUp, MouseClick, MouseDown, MouseMove, MouseUp
from ..actions import Shortcut as ShortcutAction
from ..actions import TypeText as TypeTextAction
from ..control import RunControl
from ..dryrun import RecordingKeyboard, RecordingMouse, VirtualClock
from ..engine import ActionRegistry, ExecutionContext
from ..errors import AutomationError, Cancelled
from ..events import RunEvent, RunStatus
from ..keys import Key, MouseButton, format_key
from ..plan import ExecutionLimits
from ..pointer_path import PointerStyle
from ..screen import ScreenGeometry
from ..target import RunningApplication, TargetWindow
from ..timing import TimingProfile, TimingService
from ..typing_style import TypingStyle
from .model import (
    OUTPUT,
    Button,
    Call,
    Click,
    Comparison,
    Expect,
    Find,
    ForEach,
    Locator,
    MoveTo,
    Point,
    PositionVariable,
    PressButton,
    Read,
    Record,
    ReleaseButton,
    Repeat,
    Run,
    Screenshot,
    Script,
    Scroll,
    Step,
    Template,
    TypeBlock,
    TypeTable,
    TypeText,
    UseApp,
    Wait,
    WaitFor,
    WaitForWindow,
)
from .model import KeyClick as KeyClickStep
from .model import KeyDown as KeyDownStep
from .model import KeyUp as KeyUpStep
from .validator import KNOWN_TERMINALS

logger = logging.getLogger(__name__)

#: The operating system's own surfaces. Typing into Spotlight on the way to
#: opening an application is what a person does; these are not someone's
#: document, and focus passing through them does not stop a run.
SYSTEM_SURFACES = frozenset(
    name.casefold()
    for name in (
        "Spotlight",
        "SystemUIServer",
        "Control Center",
        "ControlCenter",
        "Notification Center",
        "NotificationCenter",
        "Dock",
        "Window Server",
        "WindowServer",
    )
)

#: How often a window or the terminal's text is looked at while waiting.
POLL_MS = 250.0
#: With a quick list of applications, how long `wait for window` relies on it
#: alone before also searching window titles, which is slow on macOS.
TITLE_SEARCH_AFTER_S = 2.0
#: How long `expect output …` waits for its output to appear.
OUTPUT_TIMEOUT_S = 10.0
#: How long a `run` waits for the command before it to finish.
COMMAND_TIMEOUT_S = 300.0
#: How long output must stay unchanged to count as finished.
SETTLE_MS = 1000.0
#: How often focus is re-checked while one step is typing or moving: before
#: every keystroke and pointer sample by default. On X11 a check costs about
#: half a millisecond (measured); a slower platform can space them out, at the
#: price of what could reach another window in between.
GUARD_INTERVAL_S = 0.0
#: Steps performed, loops unrolled. A runaway loop stops here.
MAX_STEPS = 50_000


@dataclass(frozen=True)
class OwnProcess:
    """A process that is running this program: never a target."""

    pid: int
    name: str


@dataclass
class RunnerPorts:
    """Everything a run reaches the desktop through."""

    keyboard: KeyboardPort
    mouse: MousePort
    clock: Clock
    discovery: WindowDiscoveryPort | None = None
    windows: WindowControlPort | None = None
    terminal: TerminalPort | None = None
    #: Applications as a whole; where present, `App:` uses it before windows.
    applications: ApplicationPort | None = None
    screen: ScreenGeometry | None = None
    own_processes: tuple[OwnProcess, ...] = ()


# ---------------------------------------------------------------------------
# Events and outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepStarted(RunEvent):
    line: int
    description: str


@dataclass(frozen=True)
class ScriptOutcome:
    status: RunStatus
    steps_done: int
    elapsed_ms: float
    failed_line: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.COMPLETED


class StepFailed(AutomationError):
    """A step could not be performed. Carries its line."""

    def __init__(self, line: int, message: str) -> None:
        self.line = line
        super().__init__(message)


# ---------------------------------------------------------------------------
# Checks made before anything is sent
# ---------------------------------------------------------------------------


def unsupported_steps(script: Script) -> list[tuple[int, str]]:
    """Steps this runner cannot perform yet, with the reason, in line order."""
    found = [(step.line, _unsupported(step)) for step in _script_steps(script)]
    return sorted((line, reason) for line, reason in found if reason is not None)


def _unsupported(step: Step) -> str | None:
    if (
        isinstance(step, (Screenshot, Find, WaitFor))
        or (isinstance(step, Read) and step.source is not None)
        or (isinstance(step, Expect) and isinstance(step.subject, Locator))
        or (isinstance(step, MoveTo) and isinstance(step.target, Locator))
    ):
        return "needs screen reading, which arrives in roadmap 8.3"
    if isinstance(step, Scroll):
        return "scrolling is not implemented yet"
    return None


def host_conflicts(script: Script, own: Sequence[OwnProcess]) -> list[tuple[int, str]]:
    """`App:` lines that name the application running this program.

    Caught before a run, because on macOS every window of an application is one
    process: if the runner was started from Terminal, no Terminal window can be
    told apart from the one running it.
    """
    names = {process.name.casefold().removesuffix(".app") for process in own}
    names.discard("")
    clashes: list[tuple[int, str]] = []
    bodies = [stage.steps for stage in script.stages] + [
        routine.steps for routine in script.routines.values()
    ]
    for steps in bodies:
        for step in _walk(steps):
            if isinstance(step, UseApp) and step.name.casefold() in names:
                clashes.append((step.line, step.name))
    return sorted(clashes)


def _walk(steps: tuple[Step, ...]) -> list[Step]:
    found: list[Step] = []
    for step in steps:
        found.append(step)
        if isinstance(step, (ForEach, Repeat)):
            found.extend(_walk(step.body))
    return found


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class _App:
    name: str
    window: TargetWindow | None
    is_terminal: bool


@dataclass
class _Frame:
    """Names visible to the steps being run: a stage sequence or one routine."""

    text: dict[str, str] = field(default_factory=dict)
    positions: dict[str, tuple[int, int]] = field(default_factory=dict)
    columns: list[dict[str, str]] = field(default_factory=list)

    def values(self) -> dict[str, str]:
        merged = dict(self.text)
        for row in self.columns:
            merged.update(row)
        return merged


class ScriptRunner:
    """Performs scripts through injected ports. Blocks until the run ends."""

    def __init__(
        self,
        ports: RunnerPorts,
        *,
        timing: TimingProfile | None = None,
        typing: TypingStyle | None = None,
        pointer: PointerStyle | None = None,
        seed: int | None = None,
        limits: ExecutionLimits | None = None,
        registry: ActionRegistry | None = None,
        guard_interval_s: float = GUARD_INTERVAL_S,
    ) -> None:
        from ..handlers import default_registry

        self.ports = ports
        self.timing = timing or TimingProfile()
        self.typing = typing or TypingStyle()
        self.pointer = pointer or PointerStyle()
        self.seed = seed
        self.limits = limits or ExecutionLimits()
        self.registry = registry or default_registry()
        self.guard_interval_s = guard_interval_s

    def run(
        self,
        script: Script,
        control: RunControl | None = None,
        listener: Callable[[RunEvent], None] | None = None,
        *,
        dry_run: bool = False,
    ) -> ScriptOutcome:
        run = _Run(self, script, control or RunControl(), listener, dry_run)
        return run.perform()


class _Run:
    def __init__(
        self,
        owner: ScriptRunner,
        script: Script,
        control: RunControl,
        listener: Callable[[RunEvent], None] | None,
        dry_run: bool,
    ) -> None:
        self.owner = owner
        self.script = script
        self.control = control
        self.listener = listener
        self.dry_run = dry_run
        ports = owner.ports
        self.keyboard: KeyboardPort = RecordingKeyboard() if dry_run else ports.keyboard
        self.mouse: MousePort = RecordingMouse() if dry_run else ports.mouse
        self.clock: Clock = VirtualClock() if dry_run else ports.clock
        self.own_pids = {process.pid for process in ports.own_processes}
        #: Processes found to be the system's own surfaces (Spotlight), so the
        #: slow lookup is not repeated for every letter typed into them.
        self.surface_pids: set[int] = set()
        self.terminals = KNOWN_TERMINALS | {
            step.name.casefold()
            for step in _script_steps(script)
            if isinstance(step, UseApp) and step.declared_terminal
        }
        self.ctx = ExecutionContext(
            keyboard=self.keyboard,
            mouse=self.mouse,
            timing=TimingService(
                owner.timing, style=owner.typing, pointer=owner.pointer, seed=owner.seed
            ),
            control=control,
            clock=self.clock,
            emit=self._emit,
            dry_run=dry_run,
            screen=ports.screen,
            guard=self._guard_within_step,
        )
        self.app: _App | None = None
        #: The step sending input now, and when focus was last confirmed.
        self.input_line: int | None = None
        self.guarded_at = 0.0
        self.output_before: str | None = None
        #: The shell prompt, as it stood before the last Enter; it is printed
        #: again when the command finishes and is not part of the output.
        self.prompt: str | None = None
        self.recorded: dict[str, list[dict[str, str]]] = {}
        self.steps_done = 0
        self.started = 0.0

    # -- top level -------------------------------------------------------------
    def perform(self) -> ScriptOutcome:
        self.started = self.clock.monotonic()
        status, failed_line, error = RunStatus.COMPLETED, None, None
        self.control.begin()
        try:
            frame = _Frame()
            for stage in self.script.stages:
                self._steps(stage.steps, frame)
        except Cancelled as stop:
            status = RunStatus.EMERGENCY_STOPPED if stop.emergency else RunStatus.STOPPED
            error = str(stop)
        except StepFailed as failure:
            status, failed_line, error = RunStatus.FAILED, failure.line, str(failure)
        except AutomationError as failure:
            status, error = RunStatus.FAILED, str(failure)
        except Exception as failure:  # an adapter must never crash the caller
            logger.exception("script run failed")
            status, error = RunStatus.FAILED, f"{type(failure).__name__}: {failure}"
        finally:
            self._release_held()
            self.control.finish()
        elapsed = (self.clock.monotonic() - self.started) * 1000
        return ScriptOutcome(status, self.steps_done, elapsed, failed_line, error)

    def _steps(self, steps: tuple[Step, ...], frame: _Frame) -> None:
        for step in steps:
            self._step(step, frame)

    def _step(self, step: Step, frame: _Frame) -> None:
        self.ctx.checkpoint()
        self._limits(step.line)
        self._emit(StepStarted(step.line, _describe(step, frame)))
        self.steps_done += 1

        if self.dry_run and _unsupported(step) is not None:
            # A walk-through still follows the script past what it cannot do yet.
            if isinstance(step, Find):
                frame.positions[step.variable] = (0, 0)
            elif isinstance(step, Read):
                frame.text[step.variable] = f"<read at line {step.line}>"
            return

        if isinstance(step, ForEach):
            for row in self._rows(step.table, step.line):
                frame.columns.append(row)
                try:
                    self._steps(step.body, frame)
                finally:
                    frame.columns.pop()
            return
        if isinstance(step, Repeat):
            for _ in range(step.times):
                self._steps(step.body, frame)
            return
        if isinstance(step, Call):
            self._call(step, frame)
            return
        if isinstance(step, UseApp):
            self._use_app(step)
            return
        if isinstance(step, Wait):
            self.ctx.sleep_ms(step.milliseconds)
            return
        if isinstance(step, WaitForWindow):
            self._wait_for_window(step, frame)
            return
        if isinstance(step, Read) and step.source is None:
            frame.text[step.variable] = self._settled_output(step.line)
            return
        if isinstance(step, Expect):
            self._expect(step, frame)
            return
        if isinstance(step, Record):
            row = {name: _render(value, frame, step.line) for name, value in step.columns}
            self.recorded.setdefault(step.table, []).append(row)
            return
        self._input(step, frame)

    # -- input --------------------------------------------------------------------
    def _input(self, step: Step, frame: _Frame) -> None:
        """Everything that sends input goes through the focus guard first."""
        self._guard(step.line)
        self.input_line, self.guarded_at = step.line, self.clock.monotonic()
        try:
            self._send(step, frame)
        finally:
            self.input_line = None

    def _guard_within_step(self) -> None:
        """The same guard between keystrokes, at most every ``guard_interval_s``."""
        if self.input_line is None:
            return
        now = self.clock.monotonic()
        if self.owner.guard_interval_s > 0 and now - self.guarded_at < self.owner.guard_interval_s:
            return
        self.guarded_at = now
        self._guard(self.input_line)

    def _send(self, step: Step, frame: _Frame) -> None:
        actions: list[Action] = []
        command: str | None = None  # a `run`: Enter is pressed after marking the output
        if isinstance(step, TypeText):
            actions.append(TypeTextAction(text=_render(step.text, frame, step.line)))
        elif isinstance(step, Run):
            self._require_terminal(step.line, "run")
            self._previous_command_done(step.line)
            command = _render(step.command, frame, step.line)
            actions.append(TypeTextAction(text=command))
        elif isinstance(step, TypeBlock):
            block = self.script.blocks[step.block]
            actions.append(TypeTextAction(text=_render(Template(block.text), frame, step.line)))
        elif isinstance(step, TypeTable):
            actions.append(TypeTextAction(text=self._table_csv(step.table, step.line)))
        elif isinstance(step, KeyClickStep):
            if len(step.keys) == 1:
                actions.append(KeyPress(key=step.keys[0]))
                if step.keys[0] == Key.ENTER and self.app is not None and self.app.is_terminal:
                    self._mark_output()
            else:
                actions.append(ShortcutAction(keys=step.keys))
        elif isinstance(step, KeyDownStep):
            actions.append(KeyDown(key=step.key))
        elif isinstance(step, KeyUpStep):
            actions.append(KeyUp(key=step.key))
        elif isinstance(step, Click):
            actions.append(MouseClick(button=_button(step.button), count=step.count))
        elif isinstance(step, PressButton):
            actions.append(MouseDown(button=_button(step.button)))
        elif isinstance(step, ReleaseButton):
            actions.append(MouseUp(button=_button(step.button)))
        elif isinstance(step, MoveTo):
            x, y = self._point(step, frame)
            actions.append(MouseMove(x=x, y=y))
        else:
            name = type(step).__name__
            raise StepFailed(step.line, f"this step cannot be performed yet ({name})")

        for action in actions:
            self.owner.registry.handler_for(action)(action, self.ctx)
        if command is not None:
            self._mark_output(command)
            enter = KeyPress(key=Key.ENTER)
            self.owner.registry.handler_for(enter)(enter, self.ctx)

    def _point(self, step: MoveTo, frame: _Frame) -> tuple[int, int]:
        target = step.target
        if isinstance(target, Point):
            return target.x, target.y
        if isinstance(target, PositionVariable) and target.name in frame.positions:
            return frame.positions[target.name]
        raise StepFailed(step.line, "this position has not been found yet")

    def _guard(self, line: int) -> None:
        """Before any input: not into this program, and not out of the app."""
        if self.dry_run:
            return
        if self.app is None:
            raise StepFailed(
                line, "no App: has been named yet, so there is no window to send this to"
            )
        windows = self.owner.ports.windows
        if windows is None:
            return
        # The cheap question first; it is asked before every keystroke. The
        # full window, slow on macOS, is looked up only once focus has moved.
        pid = windows.active_process_id()
        if pid is None:
            return  # cannot tell - "unknown" is never "no"
        expected = self.app.window
        if pid not in self.own_pids and (
            expected is None or expected.process_id is None or pid == expected.process_id
        ):
            return
        if pid in self.surface_pids:
            return
        active = windows.active_window()
        if active is None:
            return
        if pid in self.own_pids or active.process_id in self.own_pids:
            raise StepFailed(
                line,
                f"focus is on {_window_name(active)}, which is the program running this "
                "script; stopping so nothing is typed into it",
            )
        if expected is None or active.process_id is None:
            return
        if active.process_id == expected.process_id:
            return
        if (active.process_name or active.app_id or "").casefold() in SYSTEM_SURFACES:
            self.surface_pids.add(pid)
            return
        raise StepFailed(
            line,
            f"focus moved to {_window_name(active)}, but the script is working in "
            f"{self.app.name}; stopping so the input does not go there",
        )

    # -- applications and windows ---------------------------------------------
    def _use_app(self, step: UseApp) -> None:
        is_terminal = step.declared_terminal or step.name.casefold() in self.terminals
        if self.dry_run:
            self.app = _App(step.name, None, is_terminal)
            return
        application = self._resolve_application(step.name, step.line)
        if application is not None:
            applications = self.owner.ports.applications
            assert applications is not None
            if not applications.activate_application(application, self.control):
                self.control.raise_if_stopped()
                raise StepFailed(step.line, f"could not bring {application.name} to the front")
            self.app = _App(step.name, application.target, is_terminal)
            self.output_before = self.prompt = None
            return
        discovery, windows = self.owner.ports.discovery, self.owner.ports.windows
        if discovery is None or windows is None:
            raise StepFailed(step.line, "this platform cannot find or focus windows")
        target = self._resolve(step.name, step.line)
        if not windows.activate(target, self.control):
            self.control.raise_if_stopped()
            raise StepFailed(step.line, f"could not bring {_window_name(target)} to the front")
        if windows.is_active(target) is False:
            raise StepFailed(step.line, f"{_window_name(target)} did not take focus")
        self.app = _App(step.name, target, is_terminal)
        self.output_before = self.prompt = None

    def _resolve_application(self, name: str, line: int) -> RunningApplication | None:
        """§5.14 step 1 through the application port, where there is one.

        ``None`` means "not found this way": the window search still runs, and
        is what finds a web application by its window title.
        """
        port = self.owner.ports.applications
        if port is None:
            return None
        named = [app for app in port.applications() if _is_application(app.target, name)]
        allowed = [app for app in named if app.process_id not in self.own_pids]
        if named and not allowed:
            raise StepFailed(
                line,
                f"{name} is the program running this script. Start it from another "
                "application, so it cannot type into itself",
            )
        if not allowed:
            return None
        if len(allowed) > 1:
            raise StepFailed(line, f"{len(allowed)} running applications are called {name!r}")
        application = allowed[0]
        if application.windows > 1:
            windows = self.owner.ports.windows
            front = windows.active_process_id() if windows is not None else None
            if front != application.process_id:
                raise StepFailed(
                    line,
                    f"{name} has {application.windows} windows. Close all but one, or bring "
                    "the one you mean to the front, so the script is not guessing",
                )
        return application

    def _resolve(self, name: str, line: int) -> TargetWindow:
        """§5.14: the application by name, else a window whose title contains it."""
        discovery = self.owner.ports.discovery
        assert discovery is not None
        every = list(discovery.list_windows())
        named = [window for window in every if _is_application(window, name)]
        if named:
            allowed = [w for w in named if w.process_id not in self.own_pids]
            if not allowed:
                raise StepFailed(
                    line,
                    f"every {name} window belongs to the program running this script. Start "
                    f"it from another application, so it cannot type into itself",
                )
            if len(allowed) == 1:
                return allowed[0]
            windows = self.owner.ports.windows
            active = windows.active_window() if windows is not None else None
            chosen = next(
                (w for w in allowed if active is not None and w.handle == active.handle), None
            )
            if chosen is not None:
                return chosen
            titles = "; ".join(repr(w.title) for w in allowed)
            raise StepFailed(
                line,
                f"{name} has {len(allowed)} windows ({titles}). Close all but one, or bring "
                "the one you mean to the front, so the script is not guessing",
            )
        titled = [
            w
            for w in every
            if _normalise(name) in _normalise(w.title) and w.process_id not in self.own_pids
        ]
        if not titled:
            raise StepFailed(line, f"no application or window called {name!r} is open")
        if len(titled) > 1:
            titles = "; ".join(repr(w.title) for w in titled)
            raise StepFailed(line, f"{len(titled)} windows have {name!r} in their title ({titles})")
        return titled[0]

    def _wait_for_window(self, step: WaitForWindow, frame: _Frame) -> None:
        if self.dry_run:
            return
        discovery = self.owner.ports.discovery
        if discovery is None:
            raise StepFailed(step.line, "this platform cannot list windows")
        title = _render(step.title, frame, step.line)
        deadline = self.clock.monotonic() + step.timeout_s
        applications = self.owner.ports.applications
        # Listing windows by title is slow on macOS (13 s measured); the quick
        # list of applications is polled alone first, since an application
        # just launched from Spotlight is the common case.
        titles_from = self.clock.monotonic() + (TITLE_SEARCH_AFTER_S if applications else 0.0)
        while True:
            if applications is not None:
                named = [
                    app
                    for app in applications.applications()
                    if app.process_id not in self.own_pids and _is_application(app.target, title)
                ]
                if any(app.windows > 0 for app in named):
                    return
                if named or self.clock.monotonic() < titles_from:
                    self._wait_or_fail(step, title, deadline)
                    continue
            for window in discovery.list_windows():
                if window.process_id in self.own_pids:
                    continue
                if _is_application(window, title) or _normalise(title) in _normalise(window.title):
                    return
            self._wait_or_fail(step, title, deadline)

    def _wait_or_fail(self, step: WaitForWindow, title: str, deadline: float) -> None:
        if self.clock.monotonic() >= deadline:
            raise StepFailed(
                step.line, f"no window for {title!r} appeared within {step.timeout_s:g} s"
            )
        self.ctx.sleep_ms(POLL_MS)

    # -- terminal output ------------------------------------------------------
    def _require_terminal(self, line: int, what: str) -> None:
        if self.app is None or not self.app.is_terminal:
            where = self.app.name if self.app else "no application"
            raise StepFailed(line, f"'{what}' needs a terminal, and the script is in {where}")

    def _terminal_text(self, line: int) -> str:
        terminal = self.owner.ports.terminal
        window = self.app.window if self.app is not None else None
        if terminal is None or window is None:
            raise StepFailed(line, "this platform cannot read a terminal's text")
        text = terminal.read_text(window)
        if text is None:
            raise StepFailed(
                line,
                f"could not read the text of {self.app.name if self.app else 'the terminal'}. "
                "On macOS, allow this application to control it: System Settings -> "
                "Privacy & Security -> Automation",
            )
        return text.rstrip()

    def _mark_output(self, command: str | None = None) -> None:
        """Remember the terminal as it was just before Enter.

        With the command known, the rest of its line is the prompt, which the
        shell prints again once the command has finished.
        """
        if self.dry_run or self.app is None or self.owner.ports.terminal is None:
            return
        window = self.app.window
        text = self.owner.ports.terminal.read_text(window) if window is not None else None
        self.output_before = text.rstrip() if text is not None else None
        if self.output_before is not None and command:
            last = self.output_before.rpartition("\n")[2]
            if last.endswith(command) and last[: -len(command)].strip():
                self.prompt = last[: -len(command)].rstrip()

    def _previous_command_done(self, line: int) -> None:
        """Before typing a command, wait - as a person does - for the last one to end.

        Ended means the shell's prompt is back on the last line, or, where the
        prompt is not known (a program with its own prompt, like ``psql``), that
        the output has stopped changing. Keys typed into a command that is still
        printing interleave with its output and garble the line.
        """
        if self.dry_run or self.output_before is None:
            return
        deadline = self.clock.monotonic() + COMMAND_TIMEOUT_S
        last = self._terminal_text(line)
        stable_since = self.clock.monotonic()
        while self.clock.monotonic() < deadline:
            prompt_back = last.rpartition("\n")[2].rstrip() == self.prompt
            if prompt_back and last != self.output_before:
                return
            self.ctx.sleep_ms(POLL_MS)
            current = self._terminal_text(line)
            if current != last:
                last, stable_since = current, self.clock.monotonic()
            elif (self.clock.monotonic() - stable_since) * 1000 >= SETTLE_MS:
                return
        raise StepFailed(
            line,
            f"the previous command was still printing after {COMMAND_TIMEOUT_S:g} s; "
            "not typing into it",
        )

    def _output_now(self, line: int) -> str:
        """What the last command printed: not the command line, not the next prompt."""
        now = self._terminal_text(line)
        before = self.output_before
        if before is not None and now.startswith(before):
            now = now[len(before) :]
        now = now.removeprefix("\r").removeprefix("\n")
        if self.prompt is not None:
            head, _, last = now.rpartition("\n")
            if last.rstrip() == self.prompt:
                now = head
        return now

    def _settled_output(self, line: int) -> str:
        """Output once it has stopped changing - for `read` and `does not contain`."""
        if self.dry_run:
            return f"<output at line {line}>"
        self._require_terminal(line, "output")
        deadline = self.clock.monotonic() + OUTPUT_TIMEOUT_S
        last = self._output_now(line)
        stable_since = self.clock.monotonic()
        while self.clock.monotonic() < deadline:
            self.ctx.sleep_ms(POLL_MS)
            current = self._output_now(line)
            if current != last:
                last, stable_since = current, self.clock.monotonic()
            elif (self.clock.monotonic() - stable_since) * 1000 >= SETTLE_MS:
                break
        return last

    # -- checks ---------------------------------------------------------------
    def _expect(self, step: Expect, frame: _Frame) -> None:
        if self.dry_run:
            return
        comparison = step.comparison
        if step.subject == OUTPUT:
            self._require_terminal(step.line, "output")
            if comparison is Comparison.NOT_CONTAINS:
                self._check(step, self._settled_output(step.line), frame)
                return
            deadline = self.clock.monotonic() + OUTPUT_TIMEOUT_S
            while True:
                output = self._output_now(step.line)
                if _holds(step, output, frame):
                    return
                if self.clock.monotonic() >= deadline:
                    self._check(step, output, frame)
                self.ctx.sleep_ms(POLL_MS)
        assert isinstance(step.subject, str)
        self._check(step, frame.values().get(step.subject, ""), frame)

    def _check(self, step: Expect, actual: str, frame: _Frame) -> None:
        if _holds(step, actual, frame):
            return
        if isinstance(step.value, Template):
            expected: object = _render(step.value, frame, step.line)
        else:
            expected = step.value
        tail = "\n".join(actual.strip().splitlines()[-6:]) or "(nothing)"
        raise StepFailed(
            step.line,
            f"expected {comparison_text(step.comparison)} {expected!r}, but it was not so. "
            f"Last lines seen:\n{tail}",
        )

    # -- tables and routines --------------------------------------------------
    def _rows(self, table: str, line: int) -> list[dict[str, str]]:
        declared = self.script.tables.get(table)
        if declared is not None:
            return [declared.row_values(index) for index in range(len(declared.rows))]
        if table in self.recorded:
            return [dict(row) for row in self.recorded[table]]
        if self.dry_run:
            return []
        raise StepFailed(line, f"nothing has been recorded into {table!r}")

    def _table_csv(self, table: str, line: int) -> str:
        rows = self._rows(table, line)
        declared = self.script.tables.get(table)
        columns = list(declared.columns) if declared is not None else list(rows[0]) if rows else []
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(column, "") for column in columns])
        return buffer.getvalue().rstrip("\n")

    def _call(self, step: Call, frame: _Frame) -> None:
        routine = self.script.routines[step.routine]
        arguments = {name: _render(value, frame, step.line) for name, value in step.arguments}
        inner = _Frame(text=arguments)
        self._steps(routine.steps, inner)

    # -- housekeeping ---------------------------------------------------------
    def _limits(self, line: int) -> None:
        if self.steps_done >= MAX_STEPS:
            raise StepFailed(
                line, f"the script has performed {MAX_STEPS} steps; a loop may be running away"
            )
        ceiling = self.owner.limits.max_run_duration_s
        if ceiling is not None and self.clock.monotonic() - self.started > ceiling:
            raise StepFailed(line, f"the run has gone on longer than its {ceiling:g} s limit")

    def _release_held(self) -> None:
        for key in reversed(list(self.ctx.state.keys)):
            try:
                self.keyboard.key_up(key)
            except Exception:  # pragma: no cover - adapter specific
                logger.exception("failed to release key %r", key)
        self.ctx.state.keys.clear()
        for button in reversed(list(self.ctx.state.buttons)):
            try:
                self.mouse.button_up(button)
            except Exception:  # pragma: no cover - adapter specific
                logger.exception("failed to release button %r", button)
        self.ctx.state.buttons.clear()

    def _emit(self, event: RunEvent) -> None:
        if self.listener is None:
            return
        try:
            self.listener(event)
        except Exception:
            logger.exception("script listener raised for %r", event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _script_steps(script: Script) -> list[Step]:
    steps: list[Step] = []
    for stage in script.stages:
        steps.extend(_walk(stage.steps))
    for routine in script.routines.values():
        steps.extend(_walk(routine.steps))
    return steps


def _render(template: Template, frame: _Frame, line: int) -> str:
    try:
        return template.render(frame.values())
    except KeyError as missing:
        raise StepFailed(line, f"{{{{{missing.args[0]}}}}} has no value here") from None


def _holds(step: Expect, actual: str, frame: _Frame) -> bool:
    comparison, value = step.comparison, step.value
    if isinstance(value, float):
        try:
            number = float(actual.strip())
        except ValueError:
            return False
        return {
            Comparison.EQUAL: number == value,
            Comparison.NOT_EQUAL: number != value,
            Comparison.GREATER: number > value,
            Comparison.GREATER_EQUAL: number >= value,
            Comparison.LESS: number < value,
            Comparison.LESS_EQUAL: number <= value,
        }[comparison]
    text = _render(value, frame, step.line) if value is not None else ""
    if comparison is Comparison.CONTAINS:
        return text in actual
    if comparison is Comparison.NOT_CONTAINS:
        return text not in actual
    if comparison is Comparison.MATCHES:
        return re.search(text, actual) is not None
    if comparison is Comparison.EQUAL:
        return actual == text
    if comparison is Comparison.NOT_EQUAL:
        return actual != text
    return False


def comparison_text(comparison: Comparison) -> str:
    return {
        Comparison.CONTAINS: "output containing",
        Comparison.NOT_CONTAINS: "output not containing",
        Comparison.MATCHES: "a match for",
    }.get(comparison, comparison.value)


def _is_application(window: TargetWindow, name: str) -> bool:
    wanted = name.casefold()
    for candidate in (window.process_name, window.app_id):
        folded = candidate.casefold() if candidate else ""
        if folded and (folded == wanted or folded.endswith("." + wanted)):
            return True
    return False


def _normalise(text: str) -> str:
    """§5.7's normalisations: whitespace, ellipses and curly quotes."""
    text = text.replace("…", "...").replace("“", '"').replace("”", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return " ".join(text.split())


def _window_name(window: TargetWindow) -> str:
    application = window.process_name or window.app_id or "an unknown application"
    return f"{application} ({window.title!r})" if window.title else application


def _button(button: Button) -> MouseButton:
    return MouseButton(button.value)


def _describe(step: Step, frame: _Frame) -> str:
    """One line for the run log, with substitutions made where they can be."""

    def shown(template: Template) -> str:
        try:
            return template.render(frame.values())
        except KeyError:
            return str(template)

    if isinstance(step, UseApp):
        return f"App: {step.name}"
    if isinstance(step, Run):
        return f"run `{shown(step.command)}`"
    if isinstance(step, TypeText):
        return f'type "{shown(step.text)}"'
    if isinstance(step, TypeBlock):
        return f'type block "{step.block}"'
    if isinstance(step, TypeTable):
        return f'type table "{step.table}"'
    if isinstance(step, KeyClickStep):
        return f"key-click {step.written}"
    if isinstance(step, Wait):
        return f"wait {step.milliseconds:g} ms"
    if isinstance(step, WaitForWindow):
        return f'wait for window "{shown(step.title)}"'
    if isinstance(step, Expect):
        subject = step.subject if isinstance(step.subject, str) else "screen"
        if isinstance(step.value, float):
            return f"expect {subject} {step.comparison.value} {step.value:g}"
        value = shown(step.value) if isinstance(step.value, Template) else ""
        return f"expect {subject} {step.comparison.value} {value!r}"
    def located(locator: Locator) -> str:
        kind = f"{locator.role.value} " if locator.role is not None else ""
        part = "containing " if locator.containing else ""
        inside = f' in "{shown(locator.window)}"' if locator.window is not None else ""
        return f'{kind}{part}"{shown(locator.label)}"{inside}'

    if isinstance(step, Read):
        source = located(step.source) if step.source is not None else "output"
        return f"read {source} as {step.variable}"
    if isinstance(step, Screenshot):
        return "screenshot"
    if isinstance(step, Find):
        return f"find {located(step.locator)} as {step.variable}"
    if isinstance(step, WaitFor):
        return f"wait for {located(step.locator)}"
    if isinstance(step, MoveTo):
        target = step.target
        if isinstance(target, Point):
            return f"move to {target.x}, {target.y}"
        if isinstance(target, PositionVariable):
            return f"move to {{{{{target.name}}}}}"
        return f"move to {located(target)}"
    if isinstance(step, Click):
        times = {1: "", 2: "double-", 3: "triple-"}.get(step.count, f"{step.count}x ")
        return f"{times}{step.button.value}-click"
    if isinstance(step, (PressButton, ReleaseButton)):
        verb = "press" if isinstance(step, PressButton) else "release"
        return f"{verb} {step.button.value} button"
    if isinstance(step, (KeyDownStep, KeyUpStep)):
        verb = "key-down" if isinstance(step, KeyDownStep) else "key-up"
        return f"{verb} {format_key(step.key)}"
    if isinstance(step, Scroll):
        return f"scroll {step.direction} {step.notches}"
    if isinstance(step, Record):
        return f'record into "{step.table}"'

    if isinstance(step, Call):
        return f'do "{step.routine}"'
    if isinstance(step, ForEach):
        return f'for each row in "{step.table}"'
    if isinstance(step, Repeat):
        return f"repeat {step.times} times"
    return type(step).__name__

