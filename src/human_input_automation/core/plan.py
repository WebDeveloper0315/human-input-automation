"""Automation plans: what to run, where, how fast, and under which limits."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from .actions import Action, TypeText
from .target import TargetWindow
from .timing import TimingProfile


@dataclass(frozen=True)
class ExecutionLimits:
    """Safety limits enforced before and during a run.

    They exist so a typo (a loop count of 100000, a pasted novel) cannot turn
    into an unstoppable flood of synthetic input.
    """

    max_actions: int = 500
    max_text_length: int = 5_000
    max_total_characters: int = 20_000
    max_run_duration_s: float | None = 300.0

    @classmethod
    def generous(cls) -> ExecutionLimits:
        """Relaxed limits for long-running batch use."""
        return cls(
            max_actions=10_000,
            max_text_length=100_000,
            max_total_characters=500_000,
            max_run_duration_s=None,
        )


@dataclass(frozen=True)
class RunOptions:
    """Per-run switches that do not belong to the actions themselves."""

    #: Execute nothing; report exactly what would have been sent.
    dry_run: bool = False
    #: Seed for the timing service; ``None`` means non-deterministic.
    seed: int | None = None
    #: Abort when the adapter cannot confirm the target actually has focus.
    require_focus_verification: bool = False


@dataclass(frozen=True)
class AutomationPlan:
    """An immutable, self-contained description of one automation run.

    Immutability matters: the plan is handed from the UI thread to the worker
    thread, and nothing may mutate it mid-run.
    """

    target: TargetWindow
    actions: tuple[Action, ...] = ()
    timing: TimingProfile = field(default_factory=TimingProfile)
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)
    options: RunOptions = field(default_factory=RunOptions)
    name: str = ""

    def __init__(
        self,
        target: TargetWindow,
        actions: Sequence[Action] = (),
        timing: TimingProfile | None = None,
        limits: ExecutionLimits | None = None,
        options: RunOptions | None = None,
        name: str = "",
    ) -> None:
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "actions", tuple(actions))
        object.__setattr__(self, "timing", timing or TimingProfile())
        object.__setattr__(self, "limits", limits or ExecutionLimits())
        object.__setattr__(self, "options", options or RunOptions())
        object.__setattr__(self, "name", name)

    @property
    def total_text_length(self) -> int:
        """Number of characters this plan would type in total."""
        return sum(len(a.text) for a in self.actions if isinstance(a, TypeText))

    def with_changes(self, **changes: object) -> AutomationPlan:
        return replace(self, **changes)  # type: ignore[arg-type]

    def as_dry_run(self) -> AutomationPlan:
        """Copy of this plan that cannot send real input."""
        return self.with_changes(options=replace(self.options, dry_run=True))

    def describe(self) -> str:
        label = self.name or "unnamed plan"
        mode = " [dry run]" if self.options.dry_run else ""
        return f"{label}: {len(self.actions)} action(s) -> {self.target.describe()}{mode}"
