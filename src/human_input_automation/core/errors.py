"""Exception hierarchy for the automation domain.

Every error raised by the core is a subclass of :class:`AutomationError`, so the
application layer can catch one type and report it to the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    """Severity of a validation issue."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    """A single problem found while validating a plan, action or target."""

    code: str
    message: str
    location: str = ""
    severity: Severity = Severity.ERROR

    def __str__(self) -> str:
        where = f" [{self.location}]" if self.location else ""
        return f"{self.severity.value}: {self.code}{where}: {self.message}"


class AutomationError(Exception):
    """Base class for all errors raised by this package."""


class ValidationError(AutomationError):
    """Raised when a plan, action or target is not fit for execution."""

    def __init__(self, issues: tuple[ValidationIssue, ...] | list[ValidationIssue]) -> None:
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)
        joined = "; ".join(str(issue) for issue in self.issues) or "invalid input"
        super().__init__(joined)


class Cancelled(AutomationError):
    """Raised inside the engine when a run is stopped.

    ``emergency`` marks a stop triggered by the emergency-stop control, which is
    reported separately so the UI can distinguish it from an orderly stop.
    """

    def __init__(self, *, emergency: bool = False) -> None:
        self.emergency = emergency
        super().__init__("emergency stop requested" if emergency else "stop requested")


class UnsupportedActionError(AutomationError):
    """Raised when no handler is registered for an action type."""


class TargetActivationError(AutomationError):
    """Raised when the selected target window could not be focused.

    The engine treats this as fatal: sending input to an unverified window is
    never acceptable, because the input would land in whatever happens to be
    focused instead.
    """


class AdapterUnavailableError(AutomationError):
    """Raised when a platform adapter cannot be constructed on this system."""

    def __init__(self, message: str, *, remedy: str = "") -> None:
        self.remedy = remedy
        super().__init__(f"{message} ({remedy})" if remedy else message)


class LimitExceededError(AutomationError):
    """Raised when a run exceeds a configured safety limit at execution time."""


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a plan: separate error and warning channels."""

    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if not self.ok:
            raise ValidationError(self.errors)
