"""AutoScript files: reading them from disk, and running them.

The core parses text and never learns that files exist; this is where a path
becomes text. Reading and checking a script is side-effect free - it sends no
input and runs nothing - exactly as validating a profile is. Only
:class:`ScriptSession` sends input, and only once started.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..adapters.registry import AdapterSet
from ..core.autoscript import ScriptReport, check_script
from ..core.autoscript.model import Script
from ..core.autoscript.runner import (
    OwnProcess,
    RunnerPorts,
    ScriptOutcome,
    ScriptRunner,
    host_conflicts,
    unsupported_steps,
)
from ..core.control import RunControl
from ..core.errors import Severity, ValidationIssue
from ..core.events import CountdownTick, RunEvent, RunStatus
from ..core.target import PlatformName, PlatformReport
from ..ports.terminal import TerminalPort

#: A script is a document someone reads; anything this size is not one.
MAX_SCRIPT_BYTES = 2_000_000


def check_script_file(path: str | Path) -> ScriptReport:
    """Parse and validate the script at ``path``. Problems are reported, never raised."""
    location = Path(path)
    try:
        size = location.stat().st_size
        if size > MAX_SCRIPT_BYTES:
            return _unreadable(f"{size} bytes is too large for a script (limit {MAX_SCRIPT_BYTES})")
        text = location.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _unreadable("no such file")
    except IsADirectoryError:
        return _unreadable("this is a folder, not a script")
    except UnicodeDecodeError:
        return _unreadable("the file is not UTF-8 text")
    except OSError as problem:
        return _unreadable(f"cannot be read: {problem.strerror or problem}")
    return check_script(text)


def _unreadable(reason: str) -> ScriptReport:
    return ScriptReport(
        Script(title="", platform=None, stages=()),
        (ValidationIssue("script.unreadable", reason, "line 0", Severity.ERROR),),
    )


# ---------------------------------------------------------------------------
# Running a script
# ---------------------------------------------------------------------------


def terminal_reader(host: PlatformReport) -> TerminalPort | None:
    """How this host reads a terminal's text, or ``None`` where it cannot."""
    if host.platform is PlatformName.MACOS:
        from ..adapters.terminal_text import MacTerminalText

        return MacTerminalText()
    if host.platform is PlatformName.LINUX:
        from ..adapters.terminal_text import TmuxTerminalText

        return TmuxTerminalText()
    return None


def script_ports(adapters: AdapterSet) -> RunnerPorts:
    """Everything a script run reaches the desktop through, for this host."""
    from ..adapters.process_tree import own_processes

    return RunnerPorts(
        keyboard=adapters.keyboard,
        mouse=adapters.mouse,
        clock=adapters.clock,
        discovery=adapters.discovery,
        windows=adapters.windows,
        terminal=terminal_reader(adapters.host),
        screen=adapters.geometry(),
        own_processes=own_processes(),
    )


@dataclass(frozen=True)
class Refusal:
    """A reason a script will not be started, tied to a line where there is one."""

    line: int
    message: str


def refusals(
    report: ScriptReport, own: Sequence[OwnProcess], *, performing: bool = True
) -> list[Refusal]:
    """Everything that stops a checked script from being run, before any input.

    Errors in the script, steps this version cannot perform, and applications
    that are the one running this program. All are found up front so a run never
    fails half way through for a reason that was knowable at the start. A dry
    run (``performing=False``) sends nothing, so only errors stop it.
    """
    found = [
        Refusal(_line_of(issue.location), f"{issue.code}: {issue.message}")
        for issue in report.errors
    ]
    if found or not performing:
        return found
    found += [Refusal(line, reason) for line, reason in unsupported_steps(report.script)]
    found += [
        Refusal(
            line,
            f"App: {name} is the application running this program, so its windows cannot "
            "be told apart from this one. Start the run from another application (for "
            "example iTerm2 or VS Code's terminal)",
        )
        for line, name in host_conflicts(report.script, own)
    ]
    return found


class ScriptSession:
    """One script run on a worker thread, after an interruptible countdown.

    The caller's thread stays free to stop it: :meth:`emergency_stop` is safe
    from any thread, a signal handler or a hotkey listener, at any time.
    """

    def __init__(
        self,
        runner: ScriptRunner,
        script: Script,
        *,
        listener: Callable[[RunEvent], None] | None = None,
        countdown_s: float = 0.0,
        dry_run: bool = False,
    ) -> None:
        self._runner = runner
        self._script = script
        self._listener = listener
        self._countdown_s = countdown_s
        self._dry_run = dry_run
        self.control = RunControl()
        self._outcome: ScriptOutcome | None = None
        self._thread = threading.Thread(target=self._run, name="script-runner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        remaining = self._countdown_s
        while remaining > 0:
            if self._listener is not None:
                self._listener(CountdownTick(remaining))
            step = min(1.0, remaining)
            if self.control.wait_for_stop(step):
                break
            remaining -= step
        if self.control.is_stop_requested():
            emergency = self.control.is_emergency
            status = RunStatus.EMERGENCY_STOPPED if emergency else RunStatus.STOPPED
            self._outcome = ScriptOutcome(
                status, 0, 0.0, error="cancelled during the countdown; no input was sent"
            )
            return
        self._outcome = self._runner.run(
            self._script, self.control, self._listener, dry_run=self._dry_run
        )

    def emergency_stop(self) -> None:
        self.control.emergency_stop()

    def join(self, timeout: float | None = None) -> ScriptOutcome | None:
        """Wait up to ``timeout`` s; the outcome once the run has ended, else ``None``."""
        self._thread.join(timeout)
        return None if self._thread.is_alive() else self._outcome


def _line_of(location: str) -> int:
    digits = "".join(ch for ch in location if ch.isdigit())
    return int(digits) if digits else 0
