"""Saving the run log to a file the user chose.

The run log shows what each step did, including the text a script types, so it
is never written anywhere on its own: this runs only when the user asks to save
it, and only to the path they picked. The rotating diagnostic log
(:mod:`..logging_setup`) stays free of typed text either way.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from ..metadata import METADATA


def run_log_filename(now: datetime | None = None) -> str:
    """A name that sorts by time and does not overwrite the last one."""
    return f"run-log-{(now or datetime.now()).strftime('%Y%m%d-%H%M%S')}.txt"


def run_log_text(
    lines: Sequence[str],
    *,
    platform: str,
    script: str | None = None,
    now: datetime | None = None,
) -> str:
    """The saved file: a short header saying where it came from, then the log."""
    header = [
        f"{METADATA.name} {METADATA.version} - run log",
        f"Saved:    {(now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}",
        f"Platform: {platform}",
    ]
    if script:
        header.append(f"Script:   {script}")
    return "\n".join([*header, "", *lines]) + "\n"


def save_run_log(path: str | Path, text: str) -> str | None:
    """Write ``text`` to ``path``. Returns ``None``, or why it could not be saved."""
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as problem:
        return problem.strerror or str(problem)
    return None
