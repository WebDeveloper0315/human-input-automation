"""Run events and the final run report.

The engine reports progress by emitting events to a listener callback. It never
imports a UI toolkit and never touches widgets - the application layer decides
how events reach the screen (for Qt, by marshalling them onto the UI thread).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from .actions import Action
from .errors import ValidationIssue
from .target import TargetWindow


class RunStatus(StrEnum):
    """Terminal state of a run."""

    COMPLETED = "completed"
    STOPPED = "stopped"
    EMERGENCY_STOPPED = "emergency_stopped"
    FAILED = "failed"
    INVALID = "invalid"


@dataclass(frozen=True)
class RunEvent:
    """Base class for everything the engine emits."""


@dataclass(frozen=True)
class CountdownStarted(RunEvent):
    """A pre-run countdown began. No target has been touched yet."""

    seconds: float


@dataclass(frozen=True)
class CountdownTick(RunEvent):
    """One countdown step elapsed; ``remaining`` counts down to zero."""

    remaining: float


@dataclass(frozen=True)
class CountdownCancelled(RunEvent):
    """The countdown was stopped before the run started."""

    emergency: bool = False


@dataclass(frozen=True)
class RunStarted(RunEvent):
    plan_name: str
    action_count: int
    dry_run: bool


@dataclass(frozen=True)
class TargetActivated(RunEvent):
    target: TargetWindow
    verified: bool


@dataclass(frozen=True)
class ActionStarted(RunEvent):
    index: int
    action: Action
    description: str


@dataclass(frozen=True)
class ActionCompleted(RunEvent):
    index: int
    action: Action
    elapsed_ms: float


@dataclass(frozen=True)
class RunPaused(RunEvent):
    index: int


@dataclass(frozen=True)
class RunResumed(RunEvent):
    index: int


@dataclass(frozen=True)
class RunFinished(RunEvent):
    status: RunStatus
    executed_actions: int
    elapsed_ms: float
    error: str | None = None


#: Listeners must be cheap and must not raise; the engine isolates them anyway.
EventListener = Callable[[RunEvent], None]


@dataclass(frozen=True)
class RunReport:
    """Everything the caller needs to know about a finished run."""

    status: RunStatus
    executed_actions: int
    elapsed_ms: float
    plan_name: str = ""
    dry_run: bool = False
    error: str | None = None
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    performed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.COMPLETED

    def summary(self) -> str:
        mode = " (dry run)" if self.dry_run else ""
        base = (
            f"{self.status.value}{mode}: {self.executed_actions} action(s) "
            f"in {self.elapsed_ms:.0f} ms"
        )
        return f"{base} - {self.error}" if self.error else base
