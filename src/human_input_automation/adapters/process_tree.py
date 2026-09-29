"""Which processes are running this program.

A script must never type into the window that is running it: keystrokes sent
to the terminal a runner was started from sit in its input buffer and run in
the user's shell once the runner exits. The windows to keep away from are the
ones owned by this process or any process above it - the shell, the terminal,
the editor whose terminal it is.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import Any

from ..core.autoscript.runner import OwnProcess

#: Enough for any real chain of editor -> terminal -> shell -> interpreter.
MAX_DEPTH = 32


def own_processes(run: Callable[..., Any] = subprocess.run) -> tuple[OwnProcess, ...]:
    """This process and its ancestors, nearest first. Always includes itself.

    Uses ``ps``, present on macOS and Linux. Where it is missing (Windows), only
    this process is known, and the runner says so rather than pretending the
    guard is complete.
    """
    chain: list[OwnProcess] = []
    pid = os.getpid()
    for _ in range(MAX_DEPTH):
        try:
            result = run(
                ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            break
        fields = str(result.stdout).strip().split(None, 1) if result.returncode == 0 else []
        if len(fields) != 2 or not fields[0].isdigit():
            break
        chain.append(OwnProcess(pid, os.path.basename(fields[1].strip())))
        parent = int(fields[0])
        if parent <= 1 or parent == pid:
            break
        pid = parent
    if not chain:
        chain.append(OwnProcess(os.getpid(), "python"))
    return tuple(chain)
