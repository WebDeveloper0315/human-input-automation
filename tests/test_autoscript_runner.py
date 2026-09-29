"""Performing a script: steps, terminal output, and where input may go."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from human_input_automation.adapters.registry import AdapterSet
from human_input_automation.app import run_script
from human_input_automation.application.autoscript import ScriptSession
from human_input_automation.core.autoscript import check_script
from human_input_automation.core.autoscript.model import Script
from human_input_automation.core.autoscript.runner import (
    OwnProcess,
    RunnerPorts,
    ScriptOutcome,
    ScriptRunner,
    StepStarted,
    host_conflicts,
    unsupported_steps,
)
from human_input_automation.core.control import RunControl
from human_input_automation.core.events import RunEvent, RunStatus
from human_input_automation.core.keys import Key, KeyLike
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    RunningApplication,
    TargetWindow,
    WindowCapabilities,
)
from human_input_automation.core.timing import TimingProfile
from human_input_automation.core.typing_style import TypingStyle

from .fakes import FakeClock, FakeKeyboard, FakeMouse, FakeWindows

RUNNER_PID = 900
TERMINAL_PID = 100


def window(handle: str, title: str, app: str, pid: int) -> TargetWindow:
    return TargetWindow(
        handle=handle,
        title=title,
        platform=PlatformName.MACOS,
        display_server=DisplayServer.QUARTZ,
        process_name=app,
        process_id=pid,
        app_id=app,
        capabilities=WindowCapabilities.full(),
    )


TERMINAL = window("t1", "user — -zsh — 80x24", "Terminal", TERMINAL_PID)
FINDER = window("f1", "Desktop", "Finder", 200)
HOST = window("h1", "runner — python", "Code", RUNNER_PID)


class FakeShell:
    """A terminal with a shell in it: a keyboard port and a terminal port.

    Typed characters are echoed after the prompt; Backspace removes one; Enter
    runs the line through ``commands`` and prints what it returns.
    """

    def __init__(
        self, commands: dict[str, str] | None = None, slow: dict[str, list[str]] | None = None
    ) -> None:
        self.commands = commands or {}
        #: Commands that print one line per look at the screen, then the prompt.
        self.slow = slow or {}
        self.pending: list[str] = []
        self.screen = "$ "
        self.line = ""
        self.ran: list[str] = []
        self.readable = True

    # KeyboardPort
    def type_text(self, text: str) -> None:
        for char in text:
            if char == "\n":
                self._enter()
            else:
                self.line += char
                self.screen += char

    def key_down(self, key: KeyLike) -> None:
        if key == Key.ENTER:
            self._enter()
        elif key == Key.BACKSPACE and self.line:
            self.line = self.line[:-1]
            self.screen = self.screen[:-1]

    def key_up(self, key: KeyLike) -> None:
        return None

    # TerminalPort
    def read_text(self, target: TargetWindow) -> str | None:
        if self.pending:
            self.screen += self.pending.pop(0)
        return self.screen if self.readable else None

    def _enter(self) -> None:
        command, self.line = self.line, ""
        self.ran.append(command)
        if command in self.slow:
            self.pending = [f"\n{chunk}" for chunk in self.slow[command]] + ["\n$ "]
            return
        output = self.commands.get(command, "")
        self.screen += "\n" + (output + "\n" if output else "") + "$ "


def script_of(body: str) -> Script:
    text = "# Task\n\nPlatform: macOS\n\n" + textwrap.dedent(body)
    report = check_script(text)
    assert report.ok, report.errors
    return report.script


def runner(
    shell: FakeShell,
    windows: FakeWindows | None = None,
    *,
    typing: TypingStyle | None = None,
    clock: FakeClock | None = None,
    timing: TimingProfile | None = None,
) -> tuple[ScriptRunner, FakeWindows]:
    windows = windows or FakeWindows(windows=[TERMINAL, FINDER, HOST])
    ports = RunnerPorts(
        keyboard=shell,
        mouse=FakeMouse(),
        clock=clock or FakeClock(),
        discovery=windows,
        windows=windows,
        terminal=shell,
        own_processes=(OwnProcess(RUNNER_PID, "Code"),),
    )
    timing = timing or TimingProfile.instant()
    return ScriptRunner(ports, timing=timing, typing=typing, seed=3), windows


def perform(
    script: Script, shell: FakeShell, **kwargs: object
) -> tuple[ScriptOutcome, list[RunEvent]]:
    events: list[RunEvent] = []
    run, _ = runner(shell, **kwargs)  # type: ignore[arg-type]
    return run.run(script, listener=events.append), events


# ---------------------------------------------------------------------------
# Running commands and checking what they printed
# ---------------------------------------------------------------------------


def test_a_terminal_script_runs_and_its_output_is_checked() -> None:
    shell = FakeShell({"psql -l": " legal_cases | owner", "wc -l x.csv": "31 x.csv"})
    script = script_of(
        """
        ## Check
        App: Terminal
        - run `psql -l`
        - expect output contains "legal_cases"
        - run `wc -l x.csv`
        - read output as lines
        - expect {{lines}} matches "^\\\\s*31 x.csv"
        """
    )
    outcome, _ = perform(script, shell)

    assert outcome.ok, outcome.error
    assert shell.ran == ["psql -l", "wc -l x.csv"]


def test_output_is_only_what_the_last_command_printed() -> None:
    """The first command's output must not satisfy the second one's check."""
    shell = FakeShell({"first": "COPY 30", "second": "nothing"})
    script = script_of(
        """
        ## S
        App: Terminal
        - run `first`
        - run `second`
        - expect output contains "COPY 30"
        """
    )
    outcome, _ = perform(script, shell)

    assert outcome.status is RunStatus.FAILED
    assert outcome.failed_line == 10
    assert "nothing" in (outcome.error or "")


def test_a_command_is_not_typed_until_the_one_before_it_has_finished() -> None:
    """Typing into a command still printing garbles the line - seen with xterm."""
    shell = FakeShell({"next": "ok"}, slow={"build": ["step 1", "step 2", "step 3", "done"]})
    script = script_of(
        """
        ## S
        App: Terminal
        - run `build`
        - expect output contains "step 1"
        - run `next`
        - expect output contains "ok"
        """
    )
    outcome, _ = perform(script, shell)

    assert outcome.ok, outcome.error
    assert "done\n$ next\nok" in shell.screen


def test_read_output_waits_for_a_slow_command_to_finish() -> None:
    shell = FakeShell(slow={"count": ["1", "2", "3"]})
    script = script_of(
        "## S\nApp: Terminal\n- run `count`\n- read output as n\n- expect {{n}} matches \"3$\"\n"
    )
    outcome, _ = perform(script, shell)
    assert outcome.ok, outcome.error


def test_a_failed_expectation_stops_the_run_at_its_line() -> None:
    shell = FakeShell({"count": "29"})
    script = script_of(
        """
        ## S
        App: Terminal
        - run `count`
        - expect output contains "30"
        - run `never`
        """
    )
    outcome, _ = perform(script, shell)

    assert outcome.status is RunStatus.FAILED and outcome.failed_line == 9
    assert shell.ran == ["count"], "nothing after the failure may run"
    assert "29" in (outcome.error or "")


def test_an_unreadable_terminal_is_said_so_with_what_to_do() -> None:
    shell = FakeShell({"ls": "a"})
    shell.readable = False
    script = script_of('## S\nApp: Terminal\n- run `ls`\n- expect output contains "a"\n')
    outcome, _ = perform(script, shell)

    assert outcome.status is RunStatus.FAILED
    assert "Automation" in (outcome.error or "")


def test_typing_mistakes_are_corrected_in_a_real_command_line() -> None:
    """The robot mistypes in the terminal, backspaces, and runs the right command."""
    shell = FakeShell({"brew services list": "postgresql@16 started"})
    script = script_of(
        '## S\nApp: Terminal\n- run `brew services list`\n- expect output contains "started"\n'
    )
    outcome, _ = perform(script, shell, typing=TypingStyle.natural(typo_rate=0.4))

    assert outcome.ok, outcome.error
    assert shell.ran == ["brew services list"]


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_tables_loops_routines_and_recording() -> None:
    shell = FakeShell({"stat a": "200", "stat b": "404"})
    script = script_of(
        """
        Table: Files
        | name |
        |---|
        | a |
        | b |

        ## S
        App: Terminal
        - for each row in "Files":
          - do "stat" with name="{{name}}"
        - type table "Log"

        ## Routine: stat (name)
        - App: Terminal
        - run `stat {{name}}`
        - read output as code
        - record name="{{name}}", code={{code}} into "Log"
        """
    )
    outcome, _ = perform(script, shell)

    assert outcome.ok, outcome.error
    assert shell.ran[:2] == ["stat a", "stat b"]
    # The table is typed as CSV: every line but the last is ended by Enter.
    assert shell.ran[2:] == ["name,code", "a,200"]
    assert shell.line == "b,404"


def test_read_output_is_the_output_alone() -> None:
    """Not the command line before it, and not the prompt the shell prints after."""
    shell = FakeShell({"date +%Y": "2026"})
    script = script_of(
        """
        ## S
        App: Terminal
        - run `date +%Y`
        - read output as year
        - expect {{year}} == 2026
        """
    )
    outcome, _ = perform(script, shell)
    assert outcome.ok, outcome.error


# ---------------------------------------------------------------------------
# Where input may go
# ---------------------------------------------------------------------------


def test_applications_are_found_by_name_and_activated() -> None:
    shell = FakeShell()
    run, windows = runner(shell)
    outcome = run.run(script_of("## S\nApp: Finder\n- key-click cmd+space\n"))

    assert outcome.ok, outcome.error
    assert "activate:f1" in windows.calls


def test_a_web_application_is_found_by_its_window_title() -> None:
    coggle = window("c1", "Portfolio — Coggle", "Google Chrome", 300)
    shell = FakeShell()
    run, windows = runner(shell, FakeWindows(windows=[coggle, HOST]))
    outcome = run.run(script_of("## S\nApp: Coggle\n- key-click cmd+t\n"))

    assert outcome.ok, outcome.error
    assert "activate:c1" in windows.calls


def test_the_window_running_the_script_is_never_a_target() -> None:
    """Started from Terminal, the runner must not type into that Terminal."""
    own_terminal = window("t9", "runner", "Terminal", RUNNER_PID)
    shell = FakeShell()
    run, _ = runner(shell, FakeWindows(windows=[own_terminal]))
    outcome = run.run(script_of("## S\nApp: Terminal\n- run `ls`\n"))

    assert outcome.status is RunStatus.FAILED
    assert "program running this script" in (outcome.error or "")
    assert shell.ran == [] and shell.screen == "$ "


def test_focus_landing_on_the_runner_stops_before_the_next_keystroke() -> None:
    shell = FakeShell()
    windows = FakeWindows(windows=[TERMINAL, HOST])
    run, _ = runner(shell, windows)
    clock_hook: list[int] = []

    def steal_focus(event: RunEvent) -> None:
        if isinstance(event, StepStarted) and event.description.startswith("run `second"):
            windows.active = HOST
            clock_hook.append(event.line)

    outcome = run.run(
        script_of("## S\nApp: Terminal\n- run `first`\n- run `second`\n"), listener=steal_focus
    )

    assert outcome.status is RunStatus.FAILED
    assert "program running this script" in (outcome.error or "")
    assert shell.ran == ["first"]


def test_focus_moving_to_another_application_stops_the_run() -> None:
    shell = FakeShell()
    windows = FakeWindows(windows=[TERMINAL, FINDER, HOST])
    run, _ = runner(shell, windows)

    def switch(event: RunEvent) -> None:
        if isinstance(event, StepStarted) and "second" in event.description:
            windows.active = FINDER

    script = script_of("## S\nApp: Terminal\n- run `first`\n- run `second`\n")
    outcome = run.run(script, listener=switch)

    assert outcome.status is RunStatus.FAILED
    assert "focus moved to Finder" in (outcome.error or "")
    assert shell.ran == ["first"]


def test_focus_moving_part_way_through_typing_stops_the_rest() -> None:
    """Checked between keystrokes too, so a long block cannot spill elsewhere."""
    shell = FakeShell()
    windows = FakeWindows(windows=[TERMINAL, FINDER, HOST])

    typed_when_switched: list[int] = []

    def switch_after_a_second(clock: FakeClock) -> None:
        if clock.now > 1.0 and not typed_when_switched:
            windows.active = FINDER
            typed_when_switched.append(len(shell.line))

    text = "a long line typed at a person's speed " * 5
    run, _ = runner(shell, windows, clock=FakeClock(switch_after_a_second), timing=TimingProfile())
    outcome = run.run(script_of(f'## S\nApp: Terminal\n- type "{text}"\n'))

    assert outcome.status is RunStatus.FAILED and outcome.failed_line == 7
    assert "focus moved to Finder" in (outcome.error or "")
    assert 0 < typed_when_switched[0] < len(text)
    assert len(shell.line) == typed_when_switched[0], "not one key after focus moved"


def test_typing_does_not_look_up_the_whole_window_for_every_key() -> None:
    """On macOS that lookup costs over a second; seen as 1.5 s per keystroke."""
    shell = FakeShell()
    windows = FakeWindows(windows=[TERMINAL, HOST])
    run, _ = runner(shell, windows)
    outcome = run.run(script_of('## S\nApp: Terminal\n- type "' + "x" * 200 + '"\n'))

    assert outcome.ok, outcome.error
    assert len(shell.line) == 200
    assert windows.window_lookups == 0


def test_spotlight_is_not_another_application() -> None:
    """Typing into Spotlight on the way to opening an application is allowed."""
    spotlight = window("s1", "Spotlight", "Spotlight", 400)
    shell = FakeShell()
    windows = FakeWindows(windows=[FINDER, TERMINAL, HOST])
    run, _ = runner(shell, windows)

    def open_spotlight(event: RunEvent) -> None:
        if isinstance(event, StepStarted) and event.description.startswith("type"):
            windows.active = spotlight

    script = script_of('## S\nApp: Finder\n- key-click cmd+space\n- type "terminal"\n')
    outcome = run.run(script, listener=open_spotlight)

    assert outcome.ok, outcome.error
    assert windows.window_lookups == 1, "found to be Spotlight once, then remembered"


def test_several_windows_of_an_application_use_the_one_in_front() -> None:
    second = window("t2", "other", "Terminal", TERMINAL_PID)
    shell = FakeShell()
    windows = FakeWindows(windows=[TERMINAL, second, HOST], active=second, follow_activation=True)
    run, _ = runner(shell, windows)
    outcome = run.run(script_of("## S\nApp: Terminal\n- run `ls`\n"))

    assert outcome.ok, outcome.error
    assert "activate:t2" in windows.calls


def test_several_windows_and_none_in_front_is_ambiguous_not_a_guess() -> None:
    second = window("t2", "other", "Terminal", TERMINAL_PID)
    shell = FakeShell()
    run, _ = runner(shell, FakeWindows(windows=[TERMINAL, second, HOST], active=HOST))
    outcome = run.run(script_of("## S\nApp: Terminal\n- run `ls`\n"))

    assert outcome.status is RunStatus.FAILED
    assert "2 windows" in (outcome.error or "") and shell.ran == []


def test_an_application_that_is_not_open_fails_the_step() -> None:
    shell = FakeShell()
    run, _ = runner(shell, FakeWindows(windows=[HOST]))
    outcome = run.run(script_of("## S\nApp: Postman\n- key-click cmd+t\n"))
    assert "no application or window called 'Postman'" in (outcome.error or "")


def test_waiting_for_a_window_that_appears() -> None:
    shell = FakeShell()
    windows = FakeWindows(windows=[FINDER, HOST])
    clock = FakeClock()

    def open_terminal_later(clock: FakeClock) -> None:
        if clock.now >= 1.0 and TERMINAL not in windows.windows:
            windows.windows.append(TERMINAL)

    clock.on_sleep = open_terminal_later
    run, _ = runner(shell, windows, clock=clock)
    script = script_of('## S\nApp: Finder\n- key-click cmd+space\n- wait for window "Terminal"\n')
    outcome = run.run(script)
    assert outcome.ok, outcome.error


def test_waiting_for_a_window_that_never_appears_fails_in_time() -> None:
    shell = FakeShell()
    run, _ = runner(shell, FakeWindows(windows=[FINDER, HOST]))
    outcome = run.run(script_of('## S\nApp: Finder\n- wait for window "Terminal" up to 2 s\n'))
    assert outcome.status is RunStatus.FAILED
    assert "within 2 s" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Stopping
# ---------------------------------------------------------------------------


def test_an_emergency_stop_ends_the_run_and_lets_go_of_held_keys() -> None:
    shell = FakeShell()
    released: list[KeyLike] = []
    shell.key_up = released.append  # type: ignore[method-assign,assignment]
    control = RunControl()
    clock = FakeClock(on_sleep=lambda _: control.emergency_stop())
    run, _ = runner(shell, clock=clock)
    outcome = run.run(
        script_of("## S\nApp: Terminal\n- key-down shift\n- wait 5 s\n- run `never`\n"),
        control,
    )

    assert outcome.status is RunStatus.EMERGENCY_STOPPED
    assert Key.SHIFT in released
    assert shell.ran == []


# ---------------------------------------------------------------------------
# Before a run
# ---------------------------------------------------------------------------


def test_a_dry_run_sends_nothing_and_reports_every_step() -> None:
    shell = FakeShell()
    script = script_of(
        """
        Table: T
        | n |
        |---|
        | 1 |
        | 2 |

        ## S
        App: Terminal
        - for each row in "T":
          - run `echo {{n}}`
        - read output as last
        - expect {{last}} contains "never checked"
        """
    )
    events: list[RunEvent] = []
    run, windows = runner(shell)
    outcome = run.run(script, listener=events.append, dry_run=True)

    assert outcome.ok, outcome.error
    assert shell.ran == [] and shell.screen == "$ "
    assert windows.calls == []
    described = [e.description for e in events if isinstance(e, StepStarted)]
    assert "run `echo 1`" in described and "run `echo 2`" in described


def test_steps_that_need_screen_reading_are_named_before_anything_runs() -> None:
    script = script_of(
        """
        ## S
        App: Finder
        - screenshot
        - find "Save" as save
        - move to {{save}}
        - scroll down 3
        """
    )
    lines = [line for line, _ in unsupported_steps(script)]
    assert lines == [8, 9, 11]


def test_a_script_that_drives_the_application_running_it_is_refused() -> None:
    script = script_of("## S\nApp: Terminal\n- run `ls`\n")
    from_terminal = [OwnProcess(1, "zsh"), OwnProcess(2, "Terminal")]
    assert host_conflicts(script, from_terminal) == [(6, "Terminal")]
    assert host_conflicts(script, [OwnProcess(1, "zsh"), OwnProcess(2, "Code")]) == []


def test_the_runner_is_core_and_imports_no_platform_library() -> None:
    from pathlib import Path

    import human_input_automation.core.autoscript.runner as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("pynput", "pywinctl", "PySide6", "subprocess", "Xlib"):
        assert f"import {forbidden}" not in source and f"from {forbidden}" not in source


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def cli_adapters(windows: list[TargetWindow]) -> tuple[AdapterSet, FakeKeyboard]:
    keyboard = FakeKeyboard()
    found = FakeWindows(windows=windows)
    adapters = AdapterSet(
        keyboard=keyboard,
        mouse=FakeMouse(),
        windows=found,
        discovery=found,
        clock=FakeClock(),
        # A host with no terminal reader, so no test ever starts a subprocess.
        host=PlatformReport(
            platform=PlatformName.WINDOWS,
            display_server=DisplayServer.WINDOWS,
            capabilities=WindowCapabilities.full(),
        ),
    )
    return adapters, keyboard


def write(tmp_path: Path, body: str) -> str:
    path = tmp_path / "task.md"
    path.write_text("# Task\n\nPlatform: macOS\n\n" + textwrap.dedent(body), encoding="utf-8")
    return str(path)


def test_the_command_performs_a_confirmed_script(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapters, keyboard = cli_adapters([FINDER])
    file = write(tmp_path, '## S\nApp: Finder\n- key-click cmd+space\n- type "terminal"\n')

    code = run_script(file, assume_yes=True, countdown_s=0, mistakes_percent=0, adapters=adapters)

    assert code == 0, capsys.readouterr().err
    assert keyboard.typed == "terminal"
    assert "Completed: 3 step(s)" in capsys.readouterr().out


def test_the_command_refuses_screen_steps_before_sending_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapters, keyboard = cli_adapters([FINDER])
    file = write(tmp_path, '## S\nApp: Finder\n- type "a"\n- screenshot\n- find "Save" as s\n')

    code = run_script(file, assume_yes=True, countdown_s=0, adapters=adapters)

    err = capsys.readouterr().err
    assert code == 1 and keyboard.calls == []
    assert f"{file}:8: needs screen reading" in err and "nothing was sent" in err


def test_the_command_refuses_a_script_with_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapters, keyboard = cli_adapters([FINDER])
    file = write(tmp_path, "## S\nApp: Finder\n- tpye \"a\"\n")

    assert run_script(file, assume_yes=True, countdown_s=0, adapters=adapters) == 1
    assert keyboard.calls == []
    assert "Did you mean 'type'" in capsys.readouterr().err


def test_the_command_asks_before_taking_over_the_keyboard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    adapters, keyboard = cli_adapters([FINDER])
    file = write(tmp_path, '## S\nApp: Finder\n- type "a"\n')
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")

    assert run_script(file, countdown_s=0, adapters=adapters) == 1
    assert keyboard.calls == []


def test_the_command_never_runs_unconfirmed_without_a_terminal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    adapters, keyboard = cli_adapters([FINDER])
    file = write(tmp_path, '## S\nApp: Finder\n- type "a"\n')
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert run_script(file, countdown_s=0, adapters=adapters) == 1
    assert keyboard.calls == [] and "--yes" in capsys.readouterr().err


def test_a_dry_run_walks_screen_steps_and_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapters, keyboard = cli_adapters([])
    file = write(
        tmp_path,
        '## S\nApp: Finder\n- screenshot\n- find button "Save" as save\n- move to {{save}}\n'
        "- left-click\n",
    )

    assert run_script(file, dry_run=True, adapters=adapters) == 0
    out = capsys.readouterr().out
    assert 'find button "Save" as save' in out and "no input was sent" in out
    assert keyboard.calls == [] and adapters.mouse.calls == []  # type: ignore[attr-defined]


def test_a_countdown_can_be_cancelled_before_any_input() -> None:
    shell = FakeShell()
    run, _ = runner(shell)
    session = ScriptSession(run, script_of("## S\nApp: Terminal\n- run `ls`\n"), countdown_s=30)
    session.emergency_stop()
    session.start()
    outcome = session.join(5)

    assert outcome is not None and outcome.status is RunStatus.EMERGENCY_STOPPED
    assert shell.ran == [] and "no input was sent" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Applications as a whole (macOS: milliseconds, where listing windows took 13 s)
# ---------------------------------------------------------------------------


class FakeApplications:
    def __init__(self, *apps: tuple[str, int, int], windows: FakeWindows) -> None:
        self.apps = [
            RunningApplication(name, pid, count, window(f"app:{pid}", name, name, pid))
            for name, pid, count in apps
        ]
        self.windows = windows
        self.activated: list[str] = []
        self.refuse = False

    def applications(self) -> list[RunningApplication]:
        return list(self.apps)

    def activate_application(self, application: RunningApplication, cancel: object = None) -> bool:
        self.activated.append(application.name)
        if self.refuse:
            return False
        self.windows.active = application.target
        return True


class NoWindowListing(FakeWindows):
    def list_windows(self) -> list[TargetWindow]:
        raise AssertionError("the slow window listing must not be used")


def app_runner(
    shell: FakeShell, *apps: tuple[str, int, int], windows: FakeWindows | None = None
) -> tuple[ScriptRunner, FakeApplications, FakeWindows]:
    windows = windows or NoWindowListing()
    applications = FakeApplications(*apps, windows=windows)
    ports = RunnerPorts(
        keyboard=shell,
        mouse=FakeMouse(),
        clock=FakeClock(),
        discovery=windows,
        windows=windows,
        terminal=shell,
        applications=applications,
        own_processes=(OwnProcess(RUNNER_PID, "iTerm2"),),
    )
    return ScriptRunner(ports, timing=TimingProfile.instant(), seed=3), applications, windows


def test_app_is_found_and_brought_forward_without_listing_windows() -> None:
    shell = FakeShell({"echo hi": "hi"})
    run, applications, _ = app_runner(shell, ("Terminal", TERMINAL_PID, 1), ("Finder", 200, 3))
    outcome = run.run(
        script_of('## S\nApp: Terminal\n- run `echo hi`\n- expect output contains "hi"\n')
    )

    assert outcome.ok, outcome.error
    assert applications.activated == ["Terminal"] and shell.ran == ["echo hi"]


def test_an_application_with_several_windows_must_have_the_one_meant_in_front() -> None:
    shell = FakeShell()
    run, applications, _ = app_runner(shell, ("Terminal", TERMINAL_PID, 2))
    outcome = run.run(script_of("## S\nApp: Terminal\n- run `ls`\n"))

    assert "Terminal has 2 windows" in (outcome.error or "")
    assert applications.activated == [] and shell.ran == []


def test_several_windows_are_fine_when_the_application_is_already_in_front() -> None:
    shell = FakeShell()
    windows = NoWindowListing(active=TERMINAL)
    run, _, _ = app_runner(shell, ("Terminal", TERMINAL_PID, 2), windows=windows)
    outcome = run.run(script_of("## S\nApp: Terminal\n- run `ls`\n"))
    assert outcome.ok, outcome.error


def test_the_application_running_the_script_is_refused_by_name() -> None:
    shell = FakeShell()
    run, applications, _ = app_runner(shell, ("iTerm2", RUNNER_PID, 1))
    outcome = run.run(script_of("## S\nApp: iTerm2\n- run `ls`\n"))

    assert "program running this script" in (outcome.error or "")
    assert applications.activated == []


def test_an_application_that_will_not_come_forward_fails_the_step() -> None:
    shell = FakeShell()
    run, applications, _ = app_runner(shell, ("Terminal", TERMINAL_PID, 1))
    applications.refuse = True
    outcome = run.run(script_of("## S\nApp: Terminal\n- run `ls`\n"))

    assert "could not bring Terminal to the front" in (outcome.error or "")
    assert shell.ran == []


def test_a_web_application_still_falls_back_to_window_titles() -> None:
    coggle = window("c1", "Portfolio — Coggle", "Google Chrome", 300)
    shell = FakeShell()
    windows = FakeWindows(windows=[coggle, HOST])
    run, applications, _ = app_runner(shell, ("Google Chrome", 300, 1), windows=windows)
    outcome = run.run(script_of("## S\nApp: Coggle\n- key-click cmd+t\n"))

    assert outcome.ok, outcome.error
    assert applications.activated == [] and "activate:c1" in windows.calls


def test_waiting_for_an_application_window_uses_the_quick_list() -> None:
    shell = FakeShell()
    clock = FakeClock()
    run, applications, _ = app_runner(shell, ("Finder", 200, 1))
    run.ports.clock = clock
    starting = RunningApplication("Terminal", TERMINAL_PID, 0, TERMINAL)

    def terminal_starts(clock: FakeClock) -> None:
        if starting not in applications.apps:
            applications.apps.append(starting)  # running, window not up yet
        elif clock.now > 1.0:
            applications.apps[-1] = RunningApplication("Terminal", TERMINAL_PID, 1, TERMINAL)

    clock.on_sleep = terminal_starts
    script = script_of('## S\nApp: Finder\n- key-click cmd+space\n- wait for window "Terminal"\n')
    outcome = run.run(script)
    assert outcome.ok, outcome.error
