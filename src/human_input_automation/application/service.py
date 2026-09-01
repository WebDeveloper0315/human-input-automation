"""Application service: the single entry point a UI talks to.

It owns adapter wiring, the engine and the runner, and exposes the small set of
operations a front end needs. Keeping this Qt-free means the same service backs
the desktop GUI, a future CLI and the tests.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..adapters.registry import AdapterSet, build_adapters
from ..core.engine import AutomationEngine
from ..core.errors import ValidationResult
from ..core.events import EventListener, RunReport
from ..core.plan import AutomationPlan
from ..core.target import PlatformReport, TargetWindow
from ..core.validation import validate_plan
from .runner import AutomationRunner


class AutomationService:
    """Facade over adapters, engine and runner."""

    def __init__(self, adapters: AdapterSet | None = None) -> None:
        self._adapters = adapters or build_adapters()
        self._engine = AutomationEngine(
            keyboard=self._adapters.keyboard,
            mouse=self._adapters.mouse,
            clock=self._adapters.clock,
            windows=self._adapters.windows,
        )
        self._runner = AutomationRunner(self._engine)

    # -- host / targets ----------------------------------------------------
    @property
    def host(self) -> PlatformReport:
        """What this machine can and cannot do, including missing permissions."""
        return self._adapters.host

    @property
    def problems(self) -> tuple[str, ...]:
        """Adapter problems worth showing the user before they hit Start."""
        return self._adapters.problems

    def list_targets(self) -> Sequence[TargetWindow]:
        """Windows the user can select as a target (empty when unsupported)."""
        discovery = self._adapters.discovery
        if discovery is None:
            return ()
        return discovery.list_windows()

    def focused_window_target(self) -> TargetWindow:
        """Fallback target for platforms without window control (e.g. Wayland)."""
        return TargetWindow.focused_window(
            platform=self.host.platform,
            display_server=self.host.display_server,
            capabilities=self.host.capabilities,
        )

    # -- running -----------------------------------------------------------
    def validate(self, plan: AutomationPlan) -> ValidationResult:
        return validate_plan(plan, host=self.host)

    def dry_run(self, plan: AutomationPlan) -> RunReport:
        """Preview a plan.

        Uses recording adapters and a virtual clock, so it sends nothing and
        returns immediately; ``report.elapsed_ms`` is the estimated duration of
        a real run.
        """
        return self._engine.run(plan.as_dry_run(), host=self.host)

    def start(self, plan: AutomationPlan, listener: EventListener | None = None) -> None:
        self._runner.start(plan, listener, host=self.host)

    def pause(self) -> None:
        self._runner.pause()

    def resume(self) -> None:
        self._runner.resume()

    def stop(self) -> None:
        self._runner.stop()

    def emergency_stop(self) -> None:
        self._runner.emergency_stop()

    @property
    def is_running(self) -> bool:
        return self._runner.is_running

    @property
    def last_report(self) -> RunReport | None:
        return self._runner.last_report

    def join(self, timeout: float | None = None) -> RunReport | None:
        return self._runner.join(timeout)
