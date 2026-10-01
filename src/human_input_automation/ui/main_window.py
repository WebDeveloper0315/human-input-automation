"""Main window: assembles the panels and drives the application service.

The window is the only place that knows about all the panels, but it still owns
no automation logic. It builds a plan from the panels, hands it to
:class:`~..application.service.AutomationService`, and renders the events that
come back. Automation itself always runs on the service's worker thread.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, Qt, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..application.autoscript import ScriptCheck
from ..application.profiles import (
    LoadedProfile,
    Profile,
    ProfileError,
    ProfileState,
)
from ..application.run_log import run_log_filename, run_log_text, save_run_log
from ..application.service import AutomationService, ScriptSettings
from ..core.autoscript.runner import StepStarted
from ..core.events import (
    CountdownStarted,
    CountdownTick,
    RunEvent,
    RunFinished,
    RunStarted,
)
from ..core.plan import AutomationPlan, ExecutionLimits, RunOptions
from ..core.pointer_path import PointerStyle
from ..core.target import TargetWindow, WindowCapabilities
from ..core.timing import TimingProfile
from ..core.typing_style import TypingStyle
from ..paths import ApplicationPaths
from .action_editor import ActionEditor
from .capability_banner import CapabilityBanner
from .dry_run_panel import DryRunPanel
from .models import (
    FirstRunSummary,
    PointerSource,
    UiState,
    UnsavedChoice,
    capability_banner,
    controls_for,
    dry_run_view,
    first_run_summary,
    format_event,
    friendly_error,
    next_state,
    preview_delays,
    profile_title,
    script_dry_run_view,
    script_run_confirmation,
    script_view,
    target_status_view,
    timing_to_values,
)
from .onboarding import OnboardingDialog
from .profile_panel import ProfilePanel
from .run_bridge import RunEventBridge
from .run_controls import RunControls
from .run_log import RunLog
from .script_panel import ScriptPanel
from .stop_overlay import StopOverlay
from .target_panel import TargetPanel
from .timing_panel import TimingPanel


class MainWindow(QMainWindow):
    """The desktop application window."""

    def __init__(
        self,
        service: AutomationService,
        *,
        show_dialogs: bool = True,
        paths: ApplicationPaths | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._show_dialogs = show_dialogs
        self._paths = paths
        self._state = UiState.IDLE
        self.last_message: tuple[str, str] | None = None
        #: The last briefing built, so tests and the log can inspect it.
        self.last_onboarding: FirstRunSummary | None = None

        #: Current profile, whether it has unsaved edits, and what is known
        #: about its target. ``None`` means "an unsaved profile".
        self._profile: Profile | None = None
        self._loaded: LoadedProfile | None = None
        self._dirty = False
        #: Set while the UI is being populated from a profile, so applying a
        #: profile does not look like the user editing one.
        self._applying = False
        #: Overridable in tests; the GUI shows a Save/Discard/Cancel dialog.
        self.unsaved_prompt: Callable[[], UnsavedChoice] | None = None
        #: The open AutoScript, as last checked, and whether the run in flight
        #: is that script rather than the plan.
        self._script: ScriptCheck | None = None
        self._script_running = False
        #: Overridable in tests; the GUI asks before a script takes over input.
        self.script_run_prompt: Callable[[str], bool] | None = None

        self.setWindowTitle("Human Input Automation")
        # Ask for enough height to show every panel at once; _fit_to_screen()
        # clamps it to whatever the desktop actually offers, and the body
        # scrolls below that. The minimum keeps the Start row and the emergency
        # stop reachable even on a 1366x768 laptop.
        self.setMinimumSize(880, 520)
        self.resize(1180, 940)

        self.bridge = RunEventBridge()
        self.bridge.run_event.connect(self._on_run_event)
        self.bridge.hotkey_triggered.connect(self._on_hotkey)

        self.banner = CapabilityBanner()
        self.profile_panel = ProfilePanel()
        self.script_panel = ScriptPanel()
        self.target_panel = TargetPanel()
        self.action_editor = ActionEditor()
        self.timing_panel = TimingPanel()
        self.dry_run_panel = DryRunPanel()
        self.run_log = RunLog()
        self.controls = RunControls()
        #: Carries the emergency stop while the main window is minimised, so
        #: the one control that must always be reachable still is.
        self.stop_overlay = StopOverlay(self)

        self._build_layout()
        self._connect()

        self.action_editor.set_pointer_source(
            PointerSource(
                position=self._service.pointer_position, geometry=lambda: self._service.screen
            )
        )
        self._update_banner()
        self.refresh_targets()
        self.refresh_profiles()
        self._enable_hotkey()
        self._sync_controls()
        self._maybe_show_onboarding()

    # -- construction ------------------------------------------------------
    def _build_layout(self) -> None:
        # What a run does: a plan of actions, or an AutoScript file. Start and
        # Dry run act on whichever tab is showing.
        self.work_tabs = QTabWidget()
        self.work_tabs.setAccessibleName("What to run")
        self.action_editor.setTitle("")
        self.action_editor.setFlat(True)
        self.work_tabs.addTab(self.action_editor, "Actions")
        self.work_tabs.addTab(self.script_panel, "Script")
        self.work_tabs.setTabToolTip(0, "A plan of actions for the selected target window")
        self.work_tabs.setTabToolTip(1, "An AutoScript file: it names its own applications")

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.target_panel)
        top.addWidget(self.work_tabs)
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

        # Nothing may collapse to nothing: a splitter will happily reduce a
        # child to zero height, which is how the timing fields disappeared.
        # Room for the header plus a couple of whole rows: a half-clipped row
        # reads as a rendering fault.
        #
        # These are floors, never ceilings. Setting a minimum *below* what a
        # panel's own contents need would let the splitter squeeze it until its
        # layout had to overlap its widgets - which is exactly what happened to
        # the target panel, whose active-target label was drawn over the window
        # list once a real target made it wrap onto a second line.
        self._floors = (
            (self.target_panel, 185),
            (self.work_tabs, 185),
            (self.timing_panel, 0),
            (self.dry_run_panel, 140),
            (self.run_log, 90),
        )
        for splitter in (top, middle, body):
            splitter.setChildrenCollapsible(False)

        # The panels have real minimum heights, and together they can exceed a
        # short screen. Scrolling the body keeps every panel at a usable size
        # instead of squeezing one of them out of existence - which is how the
        # timing fields vanished on a 1080p display.
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidget(body)
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._body = body
        self._apply_floors()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        layout.addWidget(self.banner)
        layout.addWidget(self.profile_panel)
        layout.addWidget(self.body_scroll, 1)
        # The run controls sit outside the splitter and keep their own height,
        # so Start and the emergency stop can never be squeezed off screen.
        self.controls.setSizePolicy(
            self.controls.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.controls)
        self.setCentralWidget(central)
        self._fit_to_screen()

        self.setTabOrder(self.target_panel, self.work_tabs)
        self.setTabOrder(self.work_tabs, self.timing_panel)
        self.setTabOrder(self.timing_panel, self.controls)

    def _apply_floors(self) -> None:
        """Minimum heights from what each panel's contents need *now*.

        Measured again whenever the window is shown or restyled: a measurement
        taken while building the window predates the platform's style, and on
        macOS the larger controls then had the last rows of a panel clipped.
        """
        for panel, floor in self._floors:
            panel.setMinimumHeight(max(floor, panel.minimumSizeHint().height()))
        self._body.setMinimumHeight(max(600, self._body.minimumSizeHint().height()))

    def showEvent(self, event: Any) -> None:  # Qt naming convention
        self._apply_floors()
        super().showEvent(event)

    def changeEvent(self, event: Any) -> None:  # Qt naming convention
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._apply_floors()
        super().changeEvent(event)

    def _fit_to_screen(self) -> None:
        """Never open taller or wider than the desktop it appears on."""
        screen: Any = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(self.width(), max(self.minimumWidth(), available.width() - 80))
        height = min(self.height(), max(self.minimumHeight(), available.height() - 80))
        self.resize(width, height)

    def _connect(self) -> None:
        self.target_panel.refresh_requested.connect(self.refresh_targets)
        self.target_panel.target_changed.connect(self._on_target_changed)
        self.action_editor.actions_changed.connect(self._on_plan_edited)
        self.timing_panel.profile_changed.connect(self._on_plan_edited)
        self.profile_panel.profile_selected.connect(self.load_profile)
        self.profile_panel.new_requested.connect(self.new_profile)
        self.profile_panel.save_requested.connect(self.save_profile)
        self.profile_panel.save_as_requested.connect(self.save_profile_as)
        self.profile_panel.duplicate_requested.connect(self.duplicate_profile)
        self.profile_panel.delete_requested.connect(self.delete_profile)
        self.profile_panel.import_requested.connect(self.import_profile)
        self.profile_panel.export_requested.connect(self.export_profile)
        self.profile_panel.resolve_requested.connect(self.resolve_profile_target)
        self.banner.details_requested.connect(self.show_onboarding)
        self.stop_overlay.emergency_requested.connect(self.emergency_stop)
        self.stop_overlay.restore_requested.connect(self.restore_from_run)
        self.controls.start_requested.connect(self.start_requested)
        self.controls.pause_requested.connect(self.pause_run)
        self.controls.resume_requested.connect(self.resume_run)
        self.controls.stop_requested.connect(self.stop_run)
        self.controls.emergency_requested.connect(self.emergency_stop)
        self.controls.dry_run_requested.connect(self.dry_run_requested)
        self.run_log.save_requested.connect(self.save_log)
        self.script_panel.open_requested.connect(self.open_script)
        self.script_panel.reload_requested.connect(self.reload_script)
        self.work_tabs.currentChanged.connect(lambda _index: self._sync_controls())

    # -- first run and permissions -----------------------------------------
    def build_first_run_summary(self) -> FirstRunSummary:
        """The briefing shown on first launch and from the banner button."""
        return first_run_summary(
            self._service.host,
            profile_directory=str(self._service.profiles.directory),
            log_directory=str(self._paths.logs) if self._paths else "",
            problems=self._service.problems,
        )

    @Slot()
    def show_onboarding(self) -> None:
        """Explain the platform and any permissions still needed.

        Never changes a system setting and never asks the OS for one; it only
        says what is missing and where the user can grant it.
        """
        summary = self.build_first_run_summary()
        self.last_onboarding = summary
        for guidance in summary.permissions:
            self._log(f"Permission required: {guidance.permission} - {guidance.instructions()}")
        if self._show_dialogs:
            OnboardingDialog(summary, self).exec()

    def _maybe_show_onboarding(self) -> None:
        """First launch only: brief the user, then record that we did."""
        paths = self._paths
        if paths is None or not paths.is_first_run:
            return
        self._log("First run: application directories initialised")
        self.show_onboarding()
        paths.mark_initialised()

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
        self._on_plan_edited()

    @Slot()
    def _on_plan_edited(self) -> None:
        """Any edit to the plan, timing or target counts as an unsaved change."""
        if not self._applying:
            self._set_dirty(True)
        self._sync_controls()

    def _check_target_available(self) -> bool:
        target = self.target_panel.selected_target
        if target is None:
            return False
        available = self._service.refresh_target(target) is not None
        self.target_panel.set_target_available(available)
        return available


    # -- profiles ----------------------------------------------------------
    @Slot()
    def refresh_profiles(self) -> None:
        """Reload the profile list from storage."""
        try:
            summaries = self._service.profiles.list()
        except ProfileError as error:
            self._show_message("Profiles unavailable", str(error))
            return
        self.profile_panel.set_profiles(summaries, self._profile.id if self._profile else None)
        self._update_profile_display()

    @Slot(str)
    def load_profile(self, profile_id: str) -> None:
        """Load a stored profile: read, validate, resolve, then show the result.

        Loading never runs anything, and a profile whose window cannot be found
        still loads - it simply cannot be started.
        """
        if not self._confirm_discard_changes():
            self.profile_panel.set_profiles(
                self._service.profiles.list(), self._profile.id if self._profile else None
            )
            return
        try:
            profile = self._service.profiles.load(profile_id)
        except ProfileError as error:
            self._show_message("Could not load the profile", str(error))
            return
        self._apply_profile(profile)
        self._log(f"Profile loaded: {profile.name}")
        self.resolve_profile_target()

    @Slot()
    def new_profile(self) -> None:
        """Start from an empty plan."""
        if not self._confirm_discard_changes():
            return
        self._applying = True
        try:
            self._profile = None
            self._loaded = None
            self.action_editor.set_actions([])
            self.timing_panel.set_values(timing_to_values(TimingProfile()))
            self.timing_panel.set_typing_style(TypingStyle())
            self.timing_panel.set_pointer_style(PointerStyle())
        finally:
            self._applying = False
        self._set_dirty(False)
        self.refresh_profiles()
        self._log("New profile")

    @Slot()
    def save_profile(self) -> None:
        """Save over the current profile, or create one if there is none."""
        if self._profile is None:
            self.save_profile_as()
            return
        self._store(self._build_profile(self._profile.name, self._profile.id))

    @Slot()
    def save_profile_as(self, name: str | None = None) -> None:
        """Save the current configuration as a new profile."""
        chosen = name or self._ask_for_name(self._profile.name if self._profile else "New profile")
        if not chosen:
            return
        self._store(self._build_profile(chosen, None))

    @Slot()
    def duplicate_profile(self) -> None:
        if self._profile is None:
            self._show_message("Nothing to duplicate", "Save this profile first.")
            return
        current = self._build_profile(self._profile.name, self._profile.id)
        copy = self._service.profiles.duplicate(current)
        self._store(copy)

    @Slot()
    def delete_profile(self) -> None:
        if self._profile is None:
            self._show_message("Nothing to delete", "This profile has not been saved yet.")
            return
        if not self._confirm_delete(self._profile.name):
            return
        try:
            self._service.profiles.delete(self._profile.id)
        except ProfileError as error:
            self._show_message("Could not delete the profile", str(error))
            return
        self._log(f"Profile deleted: {self._profile.name}")
        self._profile = None
        self._loaded = None
        self._set_dirty(False)
        self.refresh_profiles()

    @Slot()
    def import_profile(self, path: str | None = None) -> None:
        """Import a profile file. Importing never executes it."""
        chosen = path or self._ask_for_open_path()
        if not chosen:
            return
        try:
            profile = self._service.profiles.import_file(chosen)
        except ProfileError as error:
            self._show_message("Could not import the profile", str(error))
            return
        self._log(f"Profile imported: {profile.name}")
        self._apply_profile(profile)
        self.refresh_profiles()
        self.resolve_profile_target()

    @Slot()
    def export_profile(self, path: str | None = None) -> None:
        if self._profile is None:
            self._show_message("Nothing to export", "Save this profile first.")
            return
        chosen = path or self._ask_for_save_path(self._profile.name)
        if not chosen:
            return
        try:
            current = self._build_profile(self._profile.name, self._profile.id)
            self._service.profiles.export(current, chosen)
        except ProfileError as error:
            self._show_message("Could not export the profile", str(error))
            return
        self._log(f"Profile exported to {chosen}")

    @Slot()
    def resolve_profile_target(self) -> None:
        """Look for the profile's window and report what was found.

        Read-only: it enumerates windows and validates the plan. It never
        substitutes a different application, and never starts a run.
        """
        if self._profile is None:
            self._loaded = None
            self._update_profile_display()
            return
        profile = self._build_profile(self._profile.name, self._profile.id)
        loaded = self._service.prepare_profile(profile)
        self._loaded = loaded
        self._log(f"Target: {loaded.message or loaded.state.value}")

        self._applying = True
        try:
            if loaded.state is ProfileState.TARGET_RESOLVED and loaded.target is not None:
                self.refresh_targets()
                self.target_panel.select_handle(loaded.target.handle)
            else:
                # Never leave a stale selection behind: an unresolved profile
                # must not be runnable against whatever was selected before.
                self.target_panel.clear_selection()
        finally:
            self._applying = False
        self._update_profile_display()
        self._sync_controls()

    # -- profile helpers ---------------------------------------------------
    def _build_profile(self, name: str, profile_id: str | None) -> Profile:
        """Capture the current UI state as a profile (does not save it)."""
        plan = AutomationPlan(
            target=self.target_panel.selected_target
            or TargetWindow(handle="", capabilities=WindowCapabilities()),
            actions=self.action_editor.plan_actions,
            timing=self.timing_panel.profile() or TimingProfile(),
            typing=self.timing_panel.typing_style(),
            pointer=self.timing_panel.pointer_style(),
            limits=ExecutionLimits(),
            options=RunOptions(seed=self.timing_panel.seed),
            name=name,
        )
        existing = self._profile
        identity_source = self.target_panel.selected_target
        profile = self._service.profiles.build(
            name,
            plan,
            identity_source,
            profile_id=profile_id,
            description=existing.description if existing else "",
        )
        if identity_source is None and existing is not None:
            # Keep the saved identity when no window is currently selected, so
            # saving an edit to an unresolved profile does not erase its target.
            profile = profile.with_changes(target=existing.target)
        return profile

    def _apply_profile(self, profile: Profile) -> None:
        """Populate the editors from a profile without marking them dirty."""
        self.show_actions_tab()  # a profile is a plan of actions
        self._applying = True
        try:
            self._profile = profile
            self._loaded = None
            plan = profile.plan
            if plan is not None:
                self.action_editor.set_actions(plan.actions)
                self.timing_panel.set_values(timing_to_values(plan.timing))
                self.timing_panel.set_typing_style(plan.typing)
                self.timing_panel.set_pointer_style(plan.pointer)
                seed = plan.options.seed
                self.timing_panel.seed_check.setChecked(seed is not None)
                if seed is not None:
                    self.timing_panel.seed_spin.setValue(seed)
            self.target_panel.clear_selection()
        finally:
            self._applying = False
        self._set_dirty(False)
        self._update_profile_display()

    def _store(self, profile: Profile) -> None:
        """Save a profile, and only clear the dirty flag if it really worked."""
        try:
            saved = self._service.profiles.save(profile)
        except ProfileError as error:
            self._set_dirty(True)
            self._show_message("Could not save the profile", str(error))
            return
        self._profile = saved
        self._set_dirty(False)
        self._log(f"Profile saved: {saved.name}")
        self.refresh_profiles()

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._update_profile_display()

    def _update_profile_display(self) -> None:
        name = self._profile.name if self._profile else None
        self.profile_panel.set_current(name, dirty=self._dirty)
        self.profile_panel.set_status(target_status_view(self._loaded))
        self.setWindowTitle(f"Human Input Automation - {profile_title(name, dirty=self._dirty)}")

    @property
    def profile(self) -> Profile | None:
        return self._profile

    @property
    def loaded_profile(self) -> LoadedProfile | None:
        return self._loaded

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    # -- prompts (overridable so tests never open a modal dialog) ----------
    def _confirm_discard_changes(self) -> bool:
        """Returns False when the user cancelled the operation."""
        if not self._dirty:
            return True
        choice = self._ask_unsaved()
        if choice is UnsavedChoice.CANCEL:
            return False
        if choice is UnsavedChoice.SAVE:
            self.save_profile()
            return not self._dirty
        return True

    def _ask_unsaved(self) -> UnsavedChoice:
        if self.unsaved_prompt is not None:
            return self.unsaved_prompt()
        if not self._show_dialogs:
            # No way to ask: keep the user's work rather than discarding it.
            return UnsavedChoice.CANCEL
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        name = profile_title(self._profile.name if self._profile else None, dirty=False)
        box.setText(f"Save changes to {name}?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Save:
            return UnsavedChoice.SAVE
        if answer == QMessageBox.StandardButton.Discard:
            return UnsavedChoice.DISCARD
        return UnsavedChoice.CANCEL

    def _confirm_delete(self, name: str) -> bool:
        if not self._show_dialogs:
            return True
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete the profile {name!r}? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ask_for_name(self, suggestion: str) -> str | None:
        if not self._show_dialogs:
            return suggestion
        name, accepted = QInputDialog.getText(
            self, "Save profile as", "Profile name:", text=suggestion
        )
        return name.strip() if accepted and name.strip() else None

    def _ask_for_open_path(self) -> str | None:
        if not self._show_dialogs:
            return None
        path, _ = QFileDialog.getOpenFileName(
            self, "Import profile", "", "Profile files (*.json);;All files (*)"
        )
        return path or None

    @Slot()
    def save_log(self, path: str | None = None) -> None:
        """Write the run log to a file the user picks. Never automatically."""
        lines = self.run_log.lines
        if not lines:
            self._show_message("Nothing to save", "The run log is empty.")
            return
        chosen = path or self._ask_for_log_path()
        if not chosen:
            return
        host = self._service.host
        text = run_log_text(
            lines,
            platform=f"{host.platform.value}/{host.display_server.value}",
            script=self._script.path if self._script is not None else None,
        )
        problem = save_run_log(chosen, text)
        if problem is not None:
            self._show_message("Log not saved", f"Could not write {chosen}: {problem}")
            return
        self._log(f"Run log saved to {chosen}")

    def _ask_for_log_path(self) -> str | None:
        if not self._show_dialogs:
            return None
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save run log",
            str(Path.home() / run_log_filename()),
            "Text files (*.txt);;All files (*)",
        )
        return path or None

    def _ask_for_save_path(self, name: str) -> str | None:
        if not self._show_dialogs:
            return None
        path, _ = QFileDialog.getSaveFileName(
            self, "Export profile", f"{name}.json", "Profile files (*.json);;All files (*)"
        )
        return path or None

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
            typing=self.timing_panel.typing_style(),
            pointer=self.timing_panel.pointer_style(),
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
    @property
    def script_mode(self) -> bool:
        """Whether the Script tab is showing, so Start and Dry run act on it."""
        return self.work_tabs.currentWidget() is self.script_panel

    def show_script_tab(self) -> None:
        self.work_tabs.setCurrentWidget(self.script_panel)

    def show_actions_tab(self) -> None:
        self.work_tabs.setCurrentWidget(self.action_editor)

    @Slot()
    def start_requested(self) -> None:
        """The Run row's Start: the script or the plan, by the tab showing."""
        if self.script_mode:
            self.run_script()
        else:
            self.start_run()

    @Slot()
    def dry_run_requested(self) -> None:
        if self.script_mode:
            self.dry_run_script()
        else:
            self.dry_run()

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
        self._script_running = False
        try:
            self._service.start(
                plan, self.bridge, countdown_seconds=self.controls.countdown_seconds
            )
        except RuntimeError as error:  # a run is already in progress
            self._set_state(UiState.IDLE)
            self._show_message("Already running", str(error))
            return
        if self.controls.minimise_while_running:
            self._minimise_for_run()

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

    # -- AutoScript --------------------------------------------------------
    @Slot()
    def open_script(self, path: str | None = None) -> None:
        """Choose a script file and check it. Nothing is run."""
        if self._state.is_active:
            return
        chosen = path or self._ask_for_script_path()
        if chosen:
            self._check_script(chosen, announce=True)
            self.show_script_tab()

    @Slot()
    def reload_script(self) -> None:
        if self._script is not None and not self._state.is_active:
            self._check_script(self._script.path, announce=True)

    def _check_script(self, path: str, *, announce: bool = False) -> ScriptCheck:
        check = self._service.check_script(path)
        self._script = check
        view = script_view(check)
        unchanged = view == self.script_panel.view
        self.script_panel.show_view(view)
        if announce or not unchanged:  # re-read before every run; only news is logged
            self._log(f"Script {view.title}: {view.summary}")
            for problem in view.problems:
                self._log(f"  {problem}")
        return check

    @property
    def script(self) -> ScriptCheck | None:
        return self._script

    def _script_settings(self) -> ScriptSettings | None:
        """The timing panel's settings - a script types and moves like a plan."""
        timing = self.timing_panel.profile()
        if timing is None:
            self._show_message(
                "Invalid timing",
                self.timing_panel.error_text or "The timing values are not valid.",
            )
            return None
        return ScriptSettings(
            timing=timing,
            typing=self.timing_panel.typing_style(),
            pointer=self.timing_panel.pointer_style(),
            seed=self.timing_panel.seed,
        )

    @Slot()
    def dry_run_script(self) -> None:
        """Walk the script through recording ports. Sends nothing."""
        if self._script is None or self._state.is_active:
            return
        check = self._check_script(self._script.path)
        if not check.can_dry_run:
            self._show_message("Script has errors", "Fix the errors listed, then try again.")
            return
        settings = self._script_settings()
        if settings is None:
            return
        steps: list[StepStarted] = []

        def collect(event: RunEvent) -> None:
            if isinstance(event, StepStarted):
                steps.append(event)

        outcome = self._service.dry_run_script(check.script, settings, collect)
        self.dry_run_panel.show_view(script_dry_run_view(check, outcome, steps))
        self._log("Script dry run finished - no input was sent")

    @Slot()
    def run_script(self) -> None:
        """Check the file again, ask, then run it on the service's worker thread."""
        if self._script is None or self._state.is_active:
            return
        check = self._check_script(self._script.path)  # it may have been edited
        if not check.can_run:
            self._show_message(
                "Script cannot run",
                "\n".join(f"- {problem}" for problem in script_view(check).problems)
                or "The script has errors.",
            )
            return
        settings = self._script_settings()
        if settings is None or not self._confirm_script_run(check):
            return
        self._set_state(UiState.STARTING)
        self._script_running = True
        try:
            self._service.start_script(
                check.script,
                settings,
                self.bridge,
                countdown_seconds=self.controls.countdown_seconds,
            )
        except RuntimeError as error:
            self._script_running = False
            self._set_state(UiState.IDLE)
            self._show_message("Already running", str(error))
            return
        if self.controls.minimise_while_running:
            self._minimise_for_run()

    def _confirm_script_run(self, check: ScriptCheck) -> bool:
        question = script_run_confirmation(check)
        if self.script_run_prompt is not None:
            return self.script_run_prompt(question)
        if not self._show_dialogs:
            return False  # never run unasked
        answer = QMessageBox.question(
            self,
            "Run script",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ask_for_script_path(self) -> str | None:
        if not self._show_dialogs:
            return None
        path, _ = QFileDialog.getOpenFileName(
            self, "Open AutoScript", "", "AutoScript (*.md);;All files (*)"
        )
        return path or None

    # -- getting out of the way --------------------------------------------
    def _minimise_for_run(self) -> None:
        """Step aside for the target, keeping the emergency stop on screen.

        The window is minimised rather than merely lowered so it cannot cover
        the target or take its focus back; the overlay keeps the stop control a
        single click away, which is the reason minimising is safe at all.
        """
        self.stop_overlay.show_for_run("Starting...")
        self._place_overlay()
        self.showMinimized()
        self._log("Window minimised for the run; the emergency stop stays on screen")

    @Slot()
    def restore_from_run(self) -> None:
        """Bring the main window back and put the overlay away."""
        self.stop_overlay.hide()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _place_overlay(self) -> None:
        """Top-right of the screen the main window is on, clear of most targets."""
        # Typed as Any: Qt's stubs promise a QScreen, but a widget without a
        # window handle really can return None at runtime.
        screen: Any = self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        size = self.stop_overlay.size()
        self.stop_overlay.move(area.right() - size.width() - 24, area.top() + 24)

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
        if self.stop_overlay.isVisible():
            self.stop_overlay.show_state(controls_for(self._state).status_text)

        if isinstance(event, RunFinished):
            self.controls.show_countdown("")
            if self.stop_overlay.isVisible() or self.isMinimized():
                self.restore_from_run()
            if self._script_running:
                self._script_running = False
            else:
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
            script=self.script_panel.view if self.script_mode else None,
        )
        self.controls.apply_state(state)
        self.target_panel.set_locked(not state.editing_enabled)
        self.action_editor.set_locked(not state.editing_enabled)
        self.timing_panel.set_locked(not state.editing_enabled)
        self.profile_panel.set_locked(not state.editing_enabled)
        self.script_panel.set_locked(not state.editing_enabled)

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
    def closeEvent(self, event: Any) -> None:  # Qt naming convention
        """Offer to save, stop automation, then release adapter resources.

        Cancelling the unsaved-changes prompt cancels the close: unsaved work is
        never discarded silently.
        """
        if not self._confirm_discard_changes():
            ignore = getattr(event, "ignore", None)
            if callable(ignore):
                ignore()
            return
        self.stop_overlay.hide()
        if self._service.is_running:
            self._service.emergency_stop()
            self._service.join(2.0)
        self._service.close()
        super().closeEvent(event)
