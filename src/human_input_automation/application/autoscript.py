"""Reading AutoScript files from disk.

The core parses text and never learns that files exist; this is where a path
becomes text. Reading and checking a script is side-effect free - it sends no
input and runs nothing - exactly as validating a profile is.
"""

from __future__ import annotations

from pathlib import Path

from ..core.autoscript import ScriptReport, check_script
from ..core.autoscript.model import Script
from ..core.errors import Severity, ValidationIssue

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
