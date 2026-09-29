"""AutoScript: work steps written as Markdown, read and checked here.

The language is ``docs/AUTOSCRIPT.md``. This package reads it
(:func:`parse_script`) and checks it (:func:`validate_script`), and
:func:`check_script` does both. Nothing here performs a step: reading and
checking a script is side-effect free, exactly as loading a profile is.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import Severity, ValidationIssue
from .model import Note, Script
from .parser import ParseResult, parse_script
from .validator import validate_script


@dataclass(frozen=True)
class ScriptReport:
    """Everything known about a script before it runs."""

    script: Script
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors

    def notes(self, kind: str) -> tuple[Note, ...]:
        """The ``> CHECK:`` or ``> UNSUPPORTED:`` lines left by the conversion."""
        return tuple(note for note in self.script.notes if note.kind == kind)


def check_script(text: str) -> ScriptReport:
    """Parse and validate. Problems in the text are reported, never raised."""
    parsed = parse_script(text)
    issues = list(parsed.issues) + list(validate_script(parsed.script))
    issues.sort(key=lambda issue: int("".join(c for c in issue.location if c.isdigit()) or 0))
    return ScriptReport(parsed.script, tuple(issues))


__all__ = ["ParseResult", "ScriptReport", "check_script", "parse_script", "validate_script"]
