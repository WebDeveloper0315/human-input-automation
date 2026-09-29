"""Reading a terminal's text, per platform.

* **macOS**: Terminal and iTerm2 both answer AppleScript with the whole of the
  front window's scrollback. The first read makes macOS ask whether this
  application may control the terminal (Privacy & Security -> Automation); until
  that is allowed, the text cannot be read, and that is reported, not worked
  around.
* **Linux**: there is no common way to read another program's terminal, so the
  terminal is read through tmux - run the shell inside tmux, and the pane of the
  most recently active tmux client is what is read.

Both run a subprocess with a timeout and no shell, and both turn every failure
into ``None``. Nothing here types or runs anything in the terminal itself.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from ..core.target import TargetWindow

#: How long one read may take before it counts as unreadable.
READ_TIMEOUT_S = 5.0

Runner = Callable[..., Any]

_APPLESCRIPT = {
    "terminal": 'tell application "Terminal" to get history of selected tab of front window',
    "iterm2": 'tell application "iTerm2" to tell current session of current window to get contents',
    "iterm": 'tell application "iTerm2" to tell current session of current window to get contents',
}


def _capture(run: Runner, command: Sequence[str]) -> str | None:
    try:
        result = run(
            list(command),
            capture_output=True,
            text=True,
            timeout=READ_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return str(result.stdout)


class MacTerminalText:
    """Terminal.app and iTerm2, through ``osascript``."""

    def __init__(self, run: Runner = subprocess.run) -> None:
        self._run = run

    def read_text(self, window: TargetWindow) -> str | None:
        application = (window.process_name or window.app_id or "").casefold()
        script = _APPLESCRIPT.get(application)
        if script is None:
            return None
        return _capture(self._run, ["osascript", "-e", script])


class TmuxTerminalText:
    """Any terminal on Linux, provided the shell in it runs inside tmux."""

    def __init__(self, run: Runner = subprocess.run) -> None:
        self._run = run

    def read_text(self, window: TargetWindow) -> str | None:
        clients = _capture(
            self._run, ["tmux", "list-clients", "-F", "#{client_activity} #{session_name}"]
        )
        if not clients:
            return None
        latest = max(
            (line.split(" ", 1) for line in clients.splitlines() if " " in line),
            key=lambda parts: int(parts[0]) if parts[0].isdigit() else 0,
            default=None,
        )
        if latest is None:
            return None
        return _capture(
            self._run, ["tmux", "capture-pane", "-p", "-J", "-S", "-", "-t", latest[1]]
        )
