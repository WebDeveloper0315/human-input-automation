"""Main window: assembles the panels and drives the application service.

The window is the only place that knows about all the panels, but it still owns
no automation logic. It builds a plan from the panels, hands it to
:class:`~..application.service.AutomationService`, and renders the events that
come back. Automation itself always runs on the service's worker thread.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..application.service import AutomationService
from ..core.events import (
    CountdownStarted,
    CountdownTick,
    RunEvent,
    RunFinished,
    RunStarted,
)
from ..core.plan import AutomationPlan, ExecutionLimits, RunOptions
from ..core.target import TargetWindow
from .action_editor import ActionEditor
from .capability_banner import CapabilityBanner
from .dry_run_panel import DryRunPanel
from .models import (
    UiState,
    capability_banner,
    controls_for,
    dry_run_view,
    format_event,
    friendly_error,
    next_state,
    preview_delays,
)
from .run_bridge import RunEventBridge
from .run_controls import RunControls
from .run_log import RunLog
from .target_panel import TargetPanel
from .timing_panel import TimingPanel


class MainWindow(QMainWindow):
    """The desktop application window."""

    def __init__(self, service: AutomationService, *, show_dialogs: bool = True) -> None:
        super().__init__()
        self._service = service
        self._show_dialogs = show_dialogs
        self._state = UiState.IDLE
        self.last_message: tuple[str, str] | None = None

        self.setWindowTitle("Human Input Automation")
        self.resize(1150, 850)

        self.bridge = RunEventBridge()
        self.bridge.run_event.connect(self._on_run_event)
        self.bridge.hotkey_triggered.connect(self._on_hotkey)

        self.banner = CapabilityBanner()
        self.target_panel = TargetPanel()
        self.action_editor = ActionEditor()
        self.timing_panel = TimingPanel()
        self.dry_run_panel = DryRunPanel()
        self.run_log = RunLog()
        self.controls = RunControls()

        self._build_layout()
        self._connect()

        self._update_banner()
        self.refresh_targets()
        self._enable_hotkey()
        self._sync_controls()

    # -- construction ------------------------------------------------------
    def _build_layout(self) -> None:
        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.target_panel)
        top.addWidget(self.action_editor)
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 2)

        middle = QSplitter(Qt.Orientation.Horizontal)
        middle.addWidget(self.timing_panel)
        middle.addWidget(self.dry_run_panel)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 1)

        body = QSplitter(Qt.Orientation.Vertical)
        body.addWidget(top)
        body.addWidget(middle)
        body.addWidget(self.run_log)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        body.setStretchFactor(2, 2)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(body, 1)
        layout.addWidget(self.controls)
        self.setCentralWidget(central)

        self.setTabOrder(self.target_panel, self.action_editor)
        self.setTabOrder(self.action_editor, self.timing_panel)
        self.setTabOrder(self.timing_panel, self.controls)

    def _connect(self) -> None:
        self.target_panel.refresh_requested.connect(self.refresh_targets)
        self.target_panel.target_changed.connect(self._on_target_changed)
        self.action_editor.actions_changed.connect(self._sync_controls)
        self.timing_panel.profile_changed.connect(self._sync_controls)
        self.controls.start_requested.connect(self.start_run)
        self.controls.pause_requested.connect(self.pause_run)
        self.controls.resume_requested.connect(self.resume_run)
        self.controls.stop_requested.connect(self.stop_run)
        self.controls.emergency_requested.connect(self.emergency_stop)
        self.controls.dry_run_requested.connect(self.dry_run)

    # -- capability / targets ----------------------------------------------
    def _update_banner(self) -> None:
        self.banner.show_model(
            capability_banner(
                self._service.host, self._service.problems, self._service.hotkey_support
            )
        )

    @Slot()
    def refresh_targets(self) -> None:
        """Re-enumerate windows. Never falls back to the focused window."""
        listing = self._service.discover_targets()
        self.target_panel.set_listing(listing)
        if listing.reason:
            self._log(f"Window list: {listing.reason}")
        else:
            self._log(f"Window list refreshed: {len(listing.targets)} window(s)")
        self._sync_controls()

    @Slot(object)
    def _on_target_changed(self, target: TargetWindow | None) -> None:
        if target is not None:
            self._log(f"Target selected: {target.describe()}")
        self._sync_controls()

    def _check_target_available(self) -> bool:
        target = self.target_panel.selected_target
        if target is None:
            return False
        available = self._service.refresh_target(target) is not None
        self.target_panel.set_target_available(available)
        return available

    # -- plan --------------------------------------------------------------
    def build_plan(self, *, dry_run: bool = False) -> AutomationPlan | None:
        """Assemble a plan from the panels, or explain why it cannot be built."""
        target = self.target_panel.selected_target
        if target is None:
            self._show_message("No target", "Select a target window before starting.")
            return None
        if not self.action_editor.plan_actions:
            self._show_message("No actions", "Add at least one action to the plan.")
            return None
        profile = self.timing_panel.profile()
        if profile is None:
            self._show_message(
                "Invalid timing",
                self.timing_panel.error_text or "The timing values are not valid.",
            )
            return None

        plan = AutomationPlan(
            target=target,
            actions=self.action_editor.plan_actions,
            timing=profile,
            limits=ExecutionLimits(),
            options=RunOptions(seed=self.timing_panel.seed, dry_run=dry_run),
            name="desktop plan",
        )
        result = self._service.validate(plan)
        for warning in result.warnings:
            self._log(f"Warning: {warning.message}")
        if not result.ok:
            self._show_message(
                "Plan is not valid",
                "\n".join(f"- {issue.message}" for issue in result.errors),
            )
            return None
        return plan

    # -- run lifecycle -----------------------------------------------------
    @Slot()
    def start_run(self) -> None:
        if self._state.is_active:
            return
        if not self._check_target_available():
            self._show_message(
                "Target unavailable",
                "The selected window is no longer available.\n"
                "Refresh the window list and select it again.",
            )
            return
        plan = self.build_plan()
        if plan is None:
            return
        self._set_state(UiState.STARTING)
        try:
            self._service.start(
                plan, self.bridge, countdown_seconds=self.controls.countdown_seconds
            )
        except RuntimeError as error:  # a run is already in progress
            self._set_state(UiState.IDLE)
            self._show_message("Already running", str(error))

    @Slot()
    def pause_run(self) -> None:
        self._service.pause()

    @Slot()
    def resume_run(self) -> None:
        self._service.resume()

    @Slot()
    def stop_run(self) -> None:
        self._set_state(UiState.STOPPING)
        self._service.stop()

    @Slot()
    def emergency_stop(self) -> None:
        """Signal the worker and update the UI at once - never block on the thread."""
        self._log("EMERGENCY STOP requested")
        if self._state.is_active:
            self._set_state(UiState.STOPPING)
        self._service.emergency_stop()

    @Slot()
    def dry_run(self) -> None:
        plan = self.build_plan(dry_run=True)
        if plan is None:
            return
        report = self._service.dry_run(plan)
        delays = preview_delays(plan.timing, seed=plan.options.seed)
        self.dry_run_panel.show_view(dry_run_view(report, plan.target, delays))
        self._log("Dry run finished - no input was sent")

    # -- events ------------------------------------------------------------
    @Slot(object)
    def _on_run_event(self, event: RunEvent) -> None:
        """Runs on the Qt main thread; the worker only emits the signal."""
        line = format_event(event)
        if line is not None:
            self.run_log.append_line(line)

        if isinstance(event, CountdownStarted):
            self.controls.show_countdown(f"Starting in {event.seconds:.0f}...")
        elif isinstance(event, CountdownTick):
            self.controls.show_countdown(
                f"Starting in {event.remaining:.0f}..." if event.remaining > 0 else "Starting..."
            )
        elif isinstance(event, RunStarted):
            self.controls.show_countdown("")

        self._set_state(next_state(self._state, event))

        if isinstance(event, RunFinished):
            self.controls.show_countdown("")
            report = self._service.last_report
            if report is not None:
                self._log(friendly_error(report))
            self._check_target_available()

    @Slot()
    def _on_hotkey(self) -> None:
        """The global hotkey already stopped the run; this only updates the UI."""
        self._log("Emergency stop triggered by global hotkey")
        if self._state.is_active:
            self._set_state(UiState.STOPPING)

    # -- helpers -----------------------------------------------------------
    def _enable_hotkey(self) -> None:
        support = self._service.hotkey_support
        if support.is_known_unsupported:
            self._log(f"Global emergency hotkey unavailable: {support.reason}")
            self.statusBar().showMessage(
                f"Emergency stop: on-screen button only ({support.reason})"
            )
            return
        active = self._service.enable_emergency_hotkey(self.bridge.notify_hotkey)
        label = self._service.hotkey.description
        if active:
            self._log(f"Global emergency-stop hotkey active: {label}")
            self.statusBar().showMessage(f"Emergency stop: {label} or the on-screen button")
        else:
            self._log(f"Global emergency-stop hotkey could not be registered: {support.reason}")
            self.statusBar().showMessage("Emergency stop: on-screen button only")

    def _set_state(self, state: UiState) -> None:
        if state is not self._state:
            self._state = state
        self._sync_controls()

    @Slot()
    def _sync_controls(self) -> None:
        state = controls_for(
            self._state,
            has_target=self.target_panel.selected_target is not None,
            has_actions=bool(self.action_editor.plan_actions),
        )
        self.controls.apply_state(state)
        self.target_panel.set_locked(not state.editing_enabled)
        self.action_editor.set_locked(not state.editing_enabled)
        self.timing_panel.set_locked(not state.editing_enabled)

    @property
    def state(self) -> UiState:
        return self._state

    def _log(self, text: str) -> None:
        """Append a UI-originated line, in the same format as run events."""
        self.run_log.append_line(f"{datetime.now().strftime('%H:%M:%S')}  {text}")

    def _show_message(self, title: str, text: str) -> None:
        """User-facing message. Never a traceback."""
        self.last_message = (title, text)
        self._log(f"{title}: {text.splitlines()[0] if text else ''}")
        if self._show_dialogs:
            QMessageBox.warning(self, title, text)

    # -- Qt ----------------------------------------------------------------
    def closeEvent(self, event: object) -> None:  # Qt naming convention
        """Stop automation and release the hotkey before the window goes away."""
        if self._service.is_running:
            self._service.emergency_stop()
            self._service.join(2.0)
        self._service.close()
        super().closeEvent(event)  # type: ignore[arg-type]
