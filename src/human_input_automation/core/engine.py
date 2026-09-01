"""The automation engine.

The engine is pure domain logic: it depends only on the ports and knows nothing
about pynput, Qt, Win32, Quartz, X11 or Wayland. Everything it needs - input,
window control, time - is injected, which is what makes it testable with fakes
and safe to reuse behind any UI.

Responsibilities:

* validate the plan before sending any input;
* focus the selected target window, and refuse to run if that cannot be done;
* execute actions through a handler registry (so new action types never require
  changes here);
* honour pause/resume and stop/emergency-stop at every step, including during
  delays;
* always release held keys and mouse buttons, whatever the outcome.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ..ports.clock import Clock
from ..ports.input import KeyboardPort, MousePort
from ..ports.window import WindowControlPort
from .actions import Action
from .control import RunControl
from .dryrun import RecordingKeyboard, RecordingMouse, RecordingWindowControl, VirtualClock
from .errors import (
    AutomationError,
    Cancelled,
    LimitExceededError,
    TargetActivationError,
    UnsupportedActionError,
    ValidationResult,
)
from .events import (
    ActionCompleted,
    ActionStarted,
    EventListener,
    RunEvent,
    RunFinished,
    RunPaused,
    RunReport,
    RunResumed,
    RunStarted,
    RunStatus,
    TargetActivated,
)
from .keys import KeyLike, MouseButton
from .plan import AutomationPlan
from .screen import ScreenGeometry
from .target import PlatformReport
from .timing import TimingService
from .validation import validate_plan

logger = logging.getLogger(__name__)

_A = TypeVar("_A", bound=Action)

#: Handlers receive their action and the execution context.
ActionHandlerFn = Callable[[Any, "ExecutionContext"], None]


@dataclass
class InputState:
    """Keys and buttons currently held down by the engine.

    Tracked so that a stop - emergency or not - never leaves a modifier stuck
    down, which would otherwise keep affecting the user's whole desktop.
    """

    keys: list[KeyLike] = field(default_factory=list)
    buttons: list[MouseButton] = field(default_factory=list)


class ExecutionContext:
    """Everything a handler needs to execute one action."""

    def __init__(
        self,
        *,
        keyboard: KeyboardPort,
        mouse: MousePort,
        timing: TimingService,
        control: RunControl,
        clock: Clock,
        emit: Callable[[RunEvent], None],
        dry_run: bool,
        state: InputState | None = None,
    ) -> None:
        self.keyboard = keyboard
        self.mouse = mouse
        self.timing = timing
        self.control = control
        self.clock = clock
        self.emit = emit
        self.dry_run = dry_run
        self.state = state or InputState()
        self.index = 0

    # -- cooperative cancellation -----------------------------------------
    def checkpoint(self) -> None:
        """Raise :class:`Cancelled` if stopped; block here while paused."""
        self.control.raise_if_stopped()
        if self.control.is_paused:
            self.emit(RunPaused(self.index))
            self.control.wait_while_paused()
            self.control.raise_if_stopped()
            self.emit(RunResumed(self.index))

    def sleep_ms(self, milliseconds: float) -> None:
        """Interruptible delay: a stop request ends it immediately."""
        if milliseconds <= 0:
            self.control.raise_if_stopped()
            return
        self.clock.sleep_ms(milliseconds, self.control)
        self.control.raise_if_stopped()

    # -- tracked input ------------------------------------------------------
    def hold_key(self, key: KeyLike) -> None:
        self.keyboard.key_down(key)
        self.state.keys.append(key)

    def release_key(self, key: KeyLike) -> None:
        self.keyboard.key_up(key)
        if key in self.state.keys:
            self.state.keys.remove(key)

    def hold_button(self, button: MouseButton) -> None:
        self.mouse.button_down(button)
        self.state.buttons.append(button)

    def release_button(self, button: MouseButton) -> None:
        self.mouse.button_up(button)
        if button in self.state.buttons:
            self.state.buttons.remove(button)


class ActionRegistry:
    """Maps action types to handlers.

    This is the extension point: supporting a new action means registering a
    handler, not editing the engine.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Action], ActionHandlerFn] = {}

    def register(
        self, action_type: type[_A], handler: Callable[[_A, ExecutionContext], None]
    ) -> None:
        self._handlers[action_type] = handler

    def handler_for(self, action: Action) -> ActionHandlerFn:
        try:
            return self._handlers[type(action)]
        except KeyError:
            raise UnsupportedActionError(
                f"no handler registered for {type(action).__name__}"
            ) from None

    def supports(self, action_type: type[Action]) -> bool:
        return action_type in self._handlers

    def copy(self) -> ActionRegistry:
        clone = ActionRegistry()
        clone._handlers = dict(self._handlers)
        return clone


class AutomationEngine:
    """Executes automation plans against injected ports."""

    def __init__(
        self,
        *,
        keyboard: KeyboardPort,
        mouse: MousePort,
        clock: Clock,
        windows: WindowControlPort | None = None,
        registry: ActionRegistry | None = None,
    ) -> None:
        from .handlers import default_registry

        self._keyboard = keyboard
        self._mouse = mouse
        self._clock = clock
        self._windows = windows
        self._registry = registry or default_registry()

    @property
    def registry(self) -> ActionRegistry:
        return self._registry

    def validate(
        self,
        plan: AutomationPlan,
        *,
        host: PlatformReport | None = None,
        screen: ScreenGeometry | None = None,
    ) -> ValidationResult:
        """Validate ``plan`` without running it."""
        return validate_plan(plan, host=host, screen=screen)

    def run(
        self,
        plan: AutomationPlan,
        control: RunControl | None = None,
        listener: EventListener | None = None,
        *,
        host: PlatformReport | None = None,
        screen: ScreenGeometry | None = None,
    ) -> RunReport:
        """Execute ``plan`` and return a report. This call blocks.

        The engine never raises for an invalid plan or a stopped run; it reports
        them. Callers running this on a worker thread therefore always get a
        report back.
        """
        control = control or RunControl()
        emit = self._make_emitter(listener)

        result = validate_plan(plan, host=host, screen=screen)
        if not result.ok:
            report = RunReport(
                status=RunStatus.INVALID,
                executed_actions=0,
                elapsed_ms=0.0,
                plan_name=plan.name,
                dry_run=plan.options.dry_run,
                error="; ".join(issue.message for issue in result.errors),
                issues=result.issues,
            )
            emit(RunFinished(report.status, 0, 0.0, report.error))
            return report

        keyboard, mouse, windows, clock = self._ports_for(plan)
        timing = TimingService(plan.timing, seed=plan.options.seed)
        ctx = ExecutionContext(
            keyboard=keyboard,
            mouse=mouse,
            timing=timing,
            control=control,
            clock=clock,
            emit=emit,
            dry_run=plan.options.dry_run,
        )

        started_at = clock.monotonic()
        executed = 0
        performed: list[str] = []
        status = RunStatus.COMPLETED
        error: str | None = None

        control.begin()
        emit(RunStarted(plan.name, len(plan.actions), plan.options.dry_run))
        try:
            self._activate_target(plan, windows, emit)
            for index, action in enumerate(plan.actions):
                ctx.index = index
                ctx.checkpoint()
                self._enforce_runtime_limits(plan, executed, started_at, clock)
                self._verify_still_focused(plan, windows)

                emit(ActionStarted(index, action, action.describe()))
                action_started = clock.monotonic()
                self._registry.handler_for(action)(action, ctx)
                executed += 1
                performed.append(action.describe())
                emit(
                    ActionCompleted(
                        index, action, (clock.monotonic() - action_started) * 1000
                    )
                )

                self._delay_after(ctx, action, is_last=index == len(plan.actions) - 1)
        except Cancelled as exc:
            status = RunStatus.EMERGENCY_STOPPED if exc.emergency else RunStatus.STOPPED
            error = str(exc)
        except AutomationError as exc:
            status = RunStatus.FAILED
            error = str(exc)
        except Exception as exc:  # unexpected adapter failure - never crash the caller
            logger.exception("automation run failed")
            status = RunStatus.FAILED
            error = f"{type(exc).__name__}: {exc}"
        finally:
            self._release_held_inputs(ctx)
            control.finish()

        elapsed_ms = (clock.monotonic() - started_at) * 1000
        emit(RunFinished(status, executed, elapsed_ms, error))
        return RunReport(
            status=status,
            executed_actions=executed,
            elapsed_ms=elapsed_ms,
            plan_name=plan.name,
            dry_run=plan.options.dry_run,
            error=error,
            issues=result.issues,
            performed=tuple(performed),
        )

    # -- internals ---------------------------------------------------------
    def _make_emitter(self, listener: EventListener | None) -> Callable[[RunEvent], None]:
        def emit(event: RunEvent) -> None:
            if listener is None:
                return
            try:
                listener(event)
            except Exception:  # a broken listener must not stop automation
                logger.exception("event listener raised for %r", event)

        return emit

    def _ports_for(
        self, plan: AutomationPlan
    ) -> tuple[KeyboardPort, MousePort, WindowControlPort | None, Clock]:
        """Dry-run swaps in recording ports, so nothing can reach the desktop.

        It also swaps in a virtual clock: the preview returns immediately, while
        the report still shows how long the plan would really take.
        """
        if plan.options.dry_run:
            return RecordingKeyboard(), RecordingMouse(), RecordingWindowControl(), VirtualClock()
        return self._keyboard, self._mouse, self._windows, self._clock

    def _activate_target(
        self,
        plan: AutomationPlan,
        windows: WindowControlPort | None,
        emit: Callable[[RunEvent], None],
    ) -> None:
        target = plan.target
        if target.is_focused_window:
            emit(TargetActivated(target, verified=False))
            return
        if windows is None:
            raise TargetActivationError(
                "a target window was selected but no window control adapter is available"
            )
        if not windows.activate(target):
            raise TargetActivationError(f"could not activate target window {target.describe()}")

        active = windows.is_active(target)
        if active is False:
            raise TargetActivationError(
                f"target window {target.describe()} did not take focus; aborting so input "
                "is not sent to the wrong window"
            )
        if active is None and plan.options.require_focus_verification:
            raise TargetActivationError(
                "focus could not be verified on this platform and "
                "require_focus_verification is enabled"
            )
        emit(TargetActivated(target, verified=bool(active)))

    def _verify_still_focused(
        self, plan: AutomationPlan, windows: WindowControlPort | None
    ) -> None:
        """Stop if the target stopped being the focused window mid-run.

        A window can close, be replaced, or simply lose focus while a plan is
        running. Without this check the remaining actions would land in whatever
        window took over - a silent redirect into another application.
        ``None`` (cannot tell) is not treated as a failure.
        """
        if windows is None or not plan.options.reverify_focus:
            return
        target = plan.target
        if target.is_focused_window or not target.capabilities.can_verify_focus:
            return
        if windows.is_active(target) is False:
            raise TargetActivationError(
                f"the target window {target.describe()} is no longer focused; "
                "stopping so the remaining actions are not sent elsewhere"
            )

    def _enforce_runtime_limits(
        self, plan: AutomationPlan, executed: int, started_at: float, clock: Clock
    ) -> None:
        limits = plan.limits
        if executed >= limits.max_actions:
            raise LimitExceededError(f"action limit of {limits.max_actions} reached")
        if limits.max_run_duration_s is not None:
            elapsed = clock.monotonic() - started_at
            if elapsed > limits.max_run_duration_s:
                raise LimitExceededError(
                    f"run exceeded the {limits.max_run_duration_s:g} s duration limit"
                )

    def _delay_after(self, ctx: ExecutionContext, action: Action, *, is_last: bool) -> None:
        if action.delay_after_ms is not None:
            ctx.sleep_ms(ctx.timing.action_delay_ms(action.delay_after_ms))
        elif not is_last:
            ctx.sleep_ms(ctx.timing.action_delay_ms())

    def _release_held_inputs(self, ctx: ExecutionContext) -> None:
        """Best-effort cleanup; never raises."""
        for key in reversed(list(ctx.state.keys)):
            try:
                ctx.keyboard.key_up(key)
            except Exception:  # pragma: no cover - adapter specific
                logger.exception("failed to release key %r", key)
        ctx.state.keys.clear()
        for button in reversed(list(ctx.state.buttons)):
            try:
                ctx.mouse.button_up(button)
            except Exception:  # pragma: no cover - adapter specific
                logger.exception("failed to release button %r", button)
        ctx.state.buttons.clear()
