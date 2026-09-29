"""Reading a terminal's text, and finding this program's own processes.

Both shell out; here the subprocess runner is injected, so nothing is started.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from human_input_automation.adapters.process_tree import own_processes
from human_input_automation.adapters.terminal_text import MacTerminalText, TmuxTerminalText
from human_input_automation.core.target import TargetWindow

from .fakes import make_target


class Runs:
    """Answers each command by its first words; records what was run."""

    def __init__(self, answers: dict[str, tuple[int, str]]) -> None:
        self.answers = answers
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert kwargs.get("timeout"), "every subprocess has a timeout"
        assert "shell" not in kwargs, "no shell is ever involved"
        self.commands.append(command)
        for prefix, (code, out) in self.answers.items():
            if " ".join(command).startswith(prefix):
                return SimpleNamespace(returncode=code, stdout=out)
        return SimpleNamespace(returncode=1, stdout="")


def app(name: str) -> TargetWindow:
    return replace(make_target(), process_name=name, app_id=name)


def test_terminal_app_is_read_through_applescript() -> None:
    runs = Runs({"osascript": (0, "$ ls\nfile\n$ ")})
    assert MacTerminalText(runs).read_text(app("Terminal")) == "$ ls\nfile\n$ "
    assert "Terminal" in runs.commands[0][2]


def test_iterm_is_read_through_its_own_applescript() -> None:
    runs = Runs({"osascript": (0, "text")})
    MacTerminalText(runs).read_text(app("iTerm2"))
    assert "iTerm2" in runs.commands[0][2] and "contents" in runs.commands[0][2]


def test_an_unknown_terminal_is_not_guessed_at() -> None:
    runs = Runs({})
    assert MacTerminalText(runs).read_text(app("Warp")) is None
    assert runs.commands == []


def test_a_refused_automation_permission_is_unreadable_not_an_error() -> None:
    runs = Runs({"osascript": (1, "")})
    assert MacTerminalText(runs).read_text(app("Terminal")) is None


def test_a_timeout_is_unreadable_not_an_error() -> None:
    def slow(command: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    assert MacTerminalText(slow).read_text(app("Terminal")) is None


def test_tmux_reads_the_most_recently_used_client() -> None:
    runs = Runs(
        {
            "tmux list-clients": (0, "1700000000 old\n1700000500 work\n1700000100 other\n"),
            "tmux capture-pane": (0, "$ make\nok\n$ "),
        }
    )
    assert TmuxTerminalText(runs).read_text(app("xterm")) == "$ make\nok\n$ "
    assert runs.commands[1][-2:] == ["-t", "work"]


def test_no_tmux_is_unreadable() -> None:
    runs = Runs({"tmux list-clients": (0, "")})
    assert TmuxTerminalText(runs).read_text(app("xterm")) is None


def test_own_processes_walk_up_to_the_terminal() -> None:
    me = os.getpid()
    table = {
        me: (500, "python3"),
        500: (400, "-zsh"),
        400: (1, "/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"),
    }

    def ps(command: list[str], **kwargs: Any) -> SimpleNamespace:
        parent, name = table[int(command[-1])]
        return SimpleNamespace(returncode=0, stdout=f"  {parent} {name}\n")

    chain = own_processes(ps)
    assert [(p.pid, p.name) for p in chain] == [
        (me, "python3"),
        (500, "-zsh"),
        (400, "Terminal"),
    ]


def test_without_ps_this_process_is_still_known() -> None:
    def missing(command: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError("ps")

    assert [p.pid for p in own_processes(missing)] == [os.getpid()]
