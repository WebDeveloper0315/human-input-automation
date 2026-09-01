"""Presentation models for the desktop UI.

Everything in this module is plain Python: no Qt imports, no widgets, no
threads. Widgets stay thin because the decisions live here - which buttons are
enabled in which run state, how an event becomes a log line, how a form becomes
a domain action, what the capability banner should say.

That split is what makes the UI testable: most of the Phase 2 test suite
exercises this module directly, and the Qt tests only have to prove the wiring.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from ..adapters.hotkeys import HotkeySupport
from ..core.actions import (
    Action,
    KeyDown,
    KeyPress,
    KeyUp,
    MouseClick,
    MouseDown,
    MouseMove,
    MouseUp,
    Shortcut,
    TypeText,
    Wait,
)
from ..core.errors import ValidationError
from ..core.events import (
    ActionCompleted,
    ActionStarted,
    CountdownCancelled,
    CountdownStarted,
    CountdownTick,
    RunEvent,
    RunFinished,
    RunPaused,
    RunReport,
    RunResumed,
    RunStarted,
    RunStatus,
    TargetActivated,
)
from ..core.keys import MouseButton, normalize_key, parse_shortcut
from ..core.target import PlatformReport, TargetWindow
from ..core.timing import TimingProfile, TimingService

# ---------------------------------------------------------------------------
# Run state machine
# ---------------------------------------------------------------------------


class UiState(StrEnum):
    """What the user sees. Derived from run events, never from widget state."""

    IDLE = "idle"
    STARTING = "starting"
    COUNTDOWN = "countdown"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def is_active(self) -> bool:
        """True while a run is in flight (including the countdown)."""
        return self in (
            UiState.STARTING,
            UiState.COUNTDOWN,
            UiState.RUNNING,
            UiState.PAUSED,
            UiState.STOPPING,
        )

    @property
    def is_terminal(self) -> bool:
        """True for the outcome states, which behave like IDLE for the controls."""
        return self in (UiState.COMPLETED, UiState.STOPPED, UiState.FAILED)


_TERMINAL_FOR_STATUS: dict[RunStatus, UiState] = {
    RunStatus.COMPLETED: UiState.COMPLETED,
    RunStatus.STOPPED: UiState.STOPPED,
    RunStatus.EMERGENCY_STOPPED: UiState.STOPPED,
    RunStatus.FAILED: UiState.FAILED,
    RunStatus.INVALID: UiState.FAILED,
}


def next_state(current: UiState, event: RunEvent) -> UiState:
    """Fold a run event into the UI state machine."""
    if isinstance(event, CountdownStarted):
        return UiState.COUNTDOWN
    if isinstance(event, RunStarted):
        return UiState.RUNNING
    if isinstance(event, RunPaused):
        return UiState.PAUSED
    if isinstance(event, RunResumed):
        return UiState.RUNNING
    if isinstance(event, RunFinished):
        return _TERMINAL_FOR_STATUS.get(event.status, UiState.FAILED)
    return current


@dataclass(frozen=True)
class ControlsState:
    """Which controls are enabled, and what the status line says.

    ``emergency_enabled`` is always True: the emergency stop is never disabled,
    in any state, for any reason.
    """

    start_enabled: bool
    pause_enabled: bool
    resume_enabled: bool
    stop_enabled: bool
    dry_run_enabled: bool
    editing_enabled: bool
    status_text: str
    emergency_enabled: bool = True


_STATUS_TEXT: dict[UiState, str] = {
    UiState.IDLE: "Idle",
    UiState.STARTING: "Starting...",
    UiState.COUNTDOWN: "Counting down...",
    UiState.RUNNING: "Running",
    UiState.PAUSED: "Paused",
    UiState.STOPPING: "Stopping...",
    UiState.COMPLETED: "Completed",
    UiState.STOPPED: "Stopped",
    UiState.FAILED: "Failed",
}


def controls_for(
    state: UiState, *, has_target: bool = True, has_actions: bool = True
) -> ControlsState:
    """Map a UI state (plus plan readiness) onto the control enablement."""
    ready = has_target and has_actions
    if state.is_active:
        return ControlsState(
            start_enabled=False,
            pause_enabled=state is UiState.RUNNING,
            resume_enabled=state is UiState.PAUSED,
            stop_enabled=state is not UiState.STOPPING,
            dry_run_enabled=False,
            editing_enabled=False,
            status_text=_STATUS_TEXT[state],
        )
    return ControlsState(
        start_enabled=ready,
        pause_enabled=False,
        resume_enabled=False,
        stop_enabled=False,
        dry_run_enabled=has_actions,
        editing_enabled=True,
        status_text=_STATUS_TEXT[state],
    )


# ---------------------------------------------------------------------------
# Capability banner
# ---------------------------------------------------------------------------


class CapabilityLevel(StrEnum):
    """How the host's automation support should be presented.

    ``UNKNOWN`` is a distinct level on purpose: it must never be shown as "no".
    """

    AVAILABLE = "available"
    RESTRICTED = "restricted"
    DENIED = "denied"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


#: Text markers, so status is never conveyed by colour alone.
_LEVEL_MARKS: dict[CapabilityLevel, str] = {
    CapabilityLevel.AVAILABLE: "OK",
    CapabilityLevel.RESTRICTED: "LIMITED",
    CapabilityLevel.DENIED: "DENIED",
    CapabilityLevel.UNKNOWN: "UNKNOWN",
    CapabilityLevel.UNAVAILABLE: "UNAVAILABLE",
}

_LEVEL_SYMBOLS: dict[CapabilityLevel, str] = {
    CapabilityLevel.AVAILABLE: "✓",
    CapabilityLevel.RESTRICTED: "⚠",
    CapabilityLevel.DENIED: "⚠",
    CapabilityLevel.UNKNOWN: "?",
    CapabilityLevel.UNAVAILABLE: "✗",
}


@dataclass(frozen=True)
class BannerModel:
    """Everything the capability banner needs to render."""

    level: CapabilityLevel
    headline: str
    details: tuple[str, ...] = ()

    @property
    def marker(self) -> str:
        return _LEVEL_MARKS[self.level]

    @property
    def symbol(self) -> str:
        return _LEVEL_SYMBOLS[self.level]

    def as_text(self) -> str:
        return f"{self.symbol} {self.marker}: {self.headline}"


def _platform_label(host: PlatformReport) -> str:
    return f"{host.platform.value}/{host.display_server.value}"


def capability_banner(
    host: PlatformReport,
    problems: Sequence[str] = (),
    hotkey: HotkeySupport | None = None,
) -> BannerModel:
    """Summarise host capabilities into one honest banner."""
    details = list(host.warnings)
    details.extend(f"Missing permission: {permission}" for permission in host.missing_permissions)
    details.extend(problems)
    if hotkey is not None:
        details.append(f"Emergency-stop hotkey: {hotkey.reason}")

    capabilities = host.capabilities
    backend_missing = any("not usable on this host" in problem for problem in problems)

    if backend_missing:
        level = CapabilityLevel.UNAVAILABLE
        headline = "Input backend unavailable - install the desktop extra to send input."
    elif host.missing_permissions:
        level = CapabilityLevel.DENIED
        headline = f"Permission required on {_platform_label(host)} before input can be sent."
    elif not capabilities.can_send_synthetic_input:
        level = CapabilityLevel.UNAVAILABLE
        headline = f"Synthetic input is not available on {_platform_label(host)}."
    elif not (capabilities.can_enumerate and capabilities.can_activate):
        level = CapabilityLevel.RESTRICTED
        headline = (
            f"{_platform_label(host)} restricts window control; "
            "input can be sent but windows cannot be listed or focused."
        )
    elif not capabilities.can_verify_focus:
        level = CapabilityLevel.UNKNOWN
        headline = f"{_platform_label(host)} cannot confirm which window has focus."
    elif capabilities.requires_permission:
        level = CapabilityLevel.AVAILABLE
        headline = f"Input automation available on {_platform_label(host)} (permission granted)."
    else:
        level = CapabilityLevel.AVAILABLE
        headline = f"Input automation available on {_platform_label(host)}."
    return BannerModel(level, headline, tuple(details))


def host_status_text(
    host: PlatformReport,
    problems: Sequence[str] = (),
    hotkey: HotkeySupport | None = None,
) -> str:
    """Plain-text capability summary.

    Shared by the ``--check`` CLI (which must work headless) and by the tests;
    it contains no Qt, so importing it never requires a display.
    """
    capabilities = host.capabilities
    banner = capability_banner(host, problems, hotkey)
    lines = [
        banner.as_text(),
        "",
        f"Platform: {host.platform.value} ({host.display_server.value})",
        f"Send input: {_yes_no(capabilities.can_send_synthetic_input)}",
        f"Enumerate windows: {_yes_no(capabilities.can_enumerate)}",
        f"Activate windows: {_yes_no(capabilities.can_activate)}",
        f"Verify focus: {_yes_no(capabilities.can_verify_focus)}",
    ]
    if host.missing_permissions:
        lines.append("Missing permissions: " + ", ".join(host.missing_permissions))
    lines.extend(f"Note: {warning}" for warning in host.warnings)
    lines.extend(f"Adapter: {problem}" for problem in problems)
    if hotkey is not None:
        lines.append(f"Emergency hotkey: {hotkey.reason}")
    return "\n".join(lines)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


# ---------------------------------------------------------------------------
# Target presentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetRow:
    """One row of the target list."""

    handle: str
    title: str
    process: str
    pid: str
    platform: str

    @classmethod
    def from_target(cls, target: TargetWindow) -> TargetRow:
        return cls(
            handle=target.handle,
            title=target.title or "(untitled)",
            process=target.process_name or target.app_id or "-",
            pid=str(target.process_id) if target.process_id is not None else "-",
            platform=f"{target.platform.value}/{target.display_server.value}",
        )


def active_target_text(target: TargetWindow | None, *, available: bool = True) -> str:
    """Text for the always-visible active-target indicator."""
    if target is None:
        return "Active target: none selected - choose a window before starting."
    suffix = "" if available else "  [UNAVAILABLE - the window may have closed]"
    return f"Active target: {target.describe()}{suffix}"


# ---------------------------------------------------------------------------
# Action forms
# ---------------------------------------------------------------------------


class FieldKind(StrEnum):
    """How a form field should be rendered."""

    TEXT = "text"
    MULTILINE = "multiline"
    INT = "int"
    FLOAT = "float"
    CHOICE = "choice"
    BOOL = "bool"


@dataclass(frozen=True)
class FieldSpec:
    """Declarative description of one editor field."""

    name: str
    label: str
    kind: FieldKind
    default: Any = ""
    minimum: float = 0.0
    maximum: float = 1_000_000.0
    choices: tuple[str, ...] = ()
    suffix: str = ""
    help_text: str = ""


@dataclass(frozen=True)
class ActionSpec:
    """A supported action kind: its label, fields and conversions."""

    kind: str
    label: str
    fields: tuple[FieldSpec, ...]
    build: Callable[[Mapping[str, Any], float | None], Action]
    extract: Callable[[Action], dict[str, Any]]
    action_type: type[Action]


_BUTTON_CHOICES = tuple(button.value for button in MouseButton)


def _build_type_text(values: Mapping[str, Any], delay: float | None) -> Action:
    return TypeText(text=str(values.get("text", "")), delay_after_ms=delay)


def _build_key_press(values: Mapping[str, Any], delay: float | None) -> Action:
    return KeyPress(
        key=normalize_key(str(values.get("key", "")), location="key"),
        count=int(values.get("count", 1)),
        delay_after_ms=delay,
    )


def _build_key_down(values: Mapping[str, Any], delay: float | None) -> Action:
    key = normalize_key(str(values.get("key", "")), location="key")
    return KeyDown(key=key, delay_after_ms=delay)


def _build_key_up(values: Mapping[str, Any], delay: float | None) -> Action:
    key = normalize_key(str(values.get("key", "")), location="key")
    return KeyUp(key=key, delay_after_ms=delay)


def _build_shortcut(values: Mapping[str, Any], delay: float | None) -> Action:
    return Shortcut(keys=parse_shortcut(str(values.get("keys", ""))), delay_after_ms=delay)


def _build_mouse_move(values: Mapping[str, Any], delay: float | None) -> Action:
    duration = values.get("duration_ms")
    return MouseMove(
        x=int(values.get("x", 0)),
        y=int(values.get("y", 0)),
        relative=bool(values.get("relative", False)),
        duration_ms=None if duration in (None, "") else float(duration),
        delay_after_ms=delay,
    )


def _build_mouse_click(values: Mapping[str, Any], delay: float | None) -> Action:
    use_position = bool(values.get("use_position", False))
    return MouseClick(
        button=MouseButton(str(values.get("button", MouseButton.LEFT.value))),
        x=int(values.get("x", 0)) if use_position else None,
        y=int(values.get("y", 0)) if use_position else None,
        count=int(values.get("count", 1)),
        delay_after_ms=delay,
    )


def _build_mouse_down(values: Mapping[str, Any], delay: float | None) -> Action:
    return MouseDown(
        button=MouseButton(str(values.get("button", MouseButton.LEFT.value))), delay_after_ms=delay
    )


def _build_mouse_up(values: Mapping[str, Any], delay: float | None) -> Action:
    return MouseUp(
        button=MouseButton(str(values.get("button", MouseButton.LEFT.value))), delay_after_ms=delay
    )


def _build_wait(values: Mapping[str, Any], delay: float | None) -> Action:
    return Wait(duration_ms=float(values.get("duration_ms", 0)), delay_after_ms=delay)


_DELAY_HELP = "Leave empty to use the timing profile's action delay."

ACTION_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        kind="type_text",
        label="Type text",
        fields=(
            FieldSpec("text", "Text", FieldKind.MULTILINE, default="", help_text="Text to type."),
        ),
        build=_build_type_text,
        extract=lambda action: {"text": getattr(action, "text", "")},
        action_type=TypeText,
    ),
    ActionSpec(
        kind="key_press",
        label="Key press",
        fields=(
            FieldSpec(
                "key", "Key", FieldKind.TEXT, default="enter", help_text="e.g. enter, tab, a"
            ),
            FieldSpec("count", "Repeat", FieldKind.INT, default=1, minimum=1, maximum=1000),
        ),
        build=_build_key_press,
        extract=lambda action: {
            "key": _format_key_value(getattr(action, "key", "")),
            "count": getattr(action, "count", 1),
        },
        action_type=KeyPress,
    ),
    ActionSpec(
        kind="key_down",
        label="Key down (hold)",
        fields=(FieldSpec("key", "Key", FieldKind.TEXT, default="shift"),),
        build=_build_key_down,
        extract=lambda action: {"key": _format_key_value(getattr(action, "key", ""))},
        action_type=KeyDown,
    ),
    ActionSpec(
        kind="key_up",
        label="Key up (release)",
        fields=(FieldSpec("key", "Key", FieldKind.TEXT, default="shift"),),
        build=_build_key_up,
        extract=lambda action: {"key": _format_key_value(getattr(action, "key", ""))},
        action_type=KeyUp,
    ),
    ActionSpec(
        kind="shortcut",
        label="Shortcut",
        fields=(
            FieldSpec(
                "keys",
                "Combination",
                FieldKind.TEXT,
                default="ctrl+s",
                help_text="e.g. ctrl+shift+p",
            ),
        ),
        build=_build_shortcut,
        extract=lambda action: {
            "keys": "+".join(_format_key_value(key) for key in getattr(action, "keys", ()))
        },
        action_type=Shortcut,
    ),
    ActionSpec(
        kind="mouse_move",
        label="Mouse move",
        fields=(
            FieldSpec("x", "X", FieldKind.INT, default=0, minimum=-100_000, maximum=100_000),
            FieldSpec("y", "Y", FieldKind.INT, default=0, minimum=-100_000, maximum=100_000),
            FieldSpec("relative", "Relative to current position", FieldKind.BOOL, default=False),
            FieldSpec(
                "duration_ms",
                "Duration",
                FieldKind.FLOAT,
                default=None,
                maximum=60_000,
                suffix=" ms",
                help_text="Leave empty to use the timing profile.",
            ),
        ),
        build=_build_mouse_move,
        extract=lambda action: {
            "x": getattr(action, "x", 0),
            "y": getattr(action, "y", 0),
            "relative": getattr(action, "relative", False),
            "duration_ms": getattr(action, "duration_ms", None),
        },
        action_type=MouseMove,
    ),
    ActionSpec(
        kind="mouse_click",
        label="Mouse click",
        fields=(
            FieldSpec(
                "button",
                "Button",
                FieldKind.CHOICE,
                default=MouseButton.LEFT.value,
                choices=_BUTTON_CHOICES,
            ),
            FieldSpec("use_position", "Move to position first", FieldKind.BOOL, default=False),
            FieldSpec("x", "X", FieldKind.INT, default=0, maximum=100_000),
            FieldSpec("y", "Y", FieldKind.INT, default=0, maximum=100_000),
            FieldSpec("count", "Clicks", FieldKind.INT, default=1, minimum=1, maximum=10),
        ),
        build=_build_mouse_click,
        extract=lambda action: {
            "button": getattr(action, "button", MouseButton.LEFT).value,
            "use_position": getattr(action, "position", None) is not None,
            "x": getattr(action, "x", None) or 0,
            "y": getattr(action, "y", None) or 0,
            "count": getattr(action, "count", 1),
        },
        action_type=MouseClick,
    ),
    ActionSpec(
        kind="mouse_down",
        label="Mouse button down",
        fields=(
            FieldSpec(
                "button",
                "Button",
                FieldKind.CHOICE,
                default=MouseButton.LEFT.value,
                choices=_BUTTON_CHOICES,
            ),
        ),
        build=_build_mouse_down,
        extract=lambda action: {"button": getattr(action, "button", MouseButton.LEFT).value},
        action_type=MouseDown,
    ),
    ActionSpec(
        kind="mouse_up",
        label="Mouse button up",
        fields=(
            FieldSpec(
                "button",
                "Button",
                FieldKind.CHOICE,
                default=MouseButton.LEFT.value,
                choices=_BUTTON_CHOICES,
            ),
        ),
        build=_build_mouse_up,
        extract=lambda action: {"button": getattr(action, "button", MouseButton.LEFT).value},
        action_type=MouseUp,
    ),
    ActionSpec(
        kind="wait",
        label="Wait",
        fields=(
            FieldSpec(
                "duration_ms",
                "Duration",
                FieldKind.FLOAT,
                default=500.0,
                maximum=600_000,
                suffix=" ms",
            ),
        ),
        build=_build_wait,
        extract=lambda action: {"duration_ms": getattr(action, "duration_ms", 0.0)},
        action_type=Wait,
    ),
)

_SPECS_BY_KIND: dict[str, ActionSpec] = {spec.kind: spec for spec in ACTION_SPECS}
_SPECS_BY_TYPE: dict[type[Action], ActionSpec] = {spec.action_type: spec for spec in ACTION_SPECS}


def _format_key_value(key: object) -> str:
    return key.value if hasattr(key, "value") else str(key)


def spec_for_kind(kind: str) -> ActionSpec:
    """Look up an action spec, raising a readable error for unknown kinds."""
    try:
        return _SPECS_BY_KIND[kind]
    except KeyError:
        raise ValueError(f"unknown action kind {kind!r}") from None


def spec_for_action(action: Action) -> ActionSpec | None:
    """Spec for an existing action, or ``None`` for a type the UI cannot edit."""
    return _SPECS_BY_TYPE.get(type(action))


def build_action(
    kind: str, values: Mapping[str, Any], delay_after_ms: float | None = None
) -> Action:
    """Turn form values into a domain action.

    Raises :class:`ValidationError` with a message suitable for the UI; the
    domain dataclasses do the actual checking, so the editor cannot construct an
    action the engine would reject.
    """
    spec = spec_for_kind(kind)
    return spec.build(values, delay_after_ms)


def action_to_values(action: Action) -> dict[str, Any]:
    """Turn a domain action back into form values for editing."""
    spec = spec_for_action(action)
    if spec is None:
        return {}
    return spec.extract(action)


def action_error_message(error: ValidationError) -> str:
    """One readable line per validation issue."""
    return "\n".join(issue.message for issue in error.issues) or str(error)


def action_row_text(index: int, action: Action) -> str:
    """Row label for the action list."""
    delay = ""
    if action.delay_after_ms is not None:
        delay = f"  (+{action.delay_after_ms:g} ms)"
    return f"{index + 1}. {action.describe()}{delay}"


# ---------------------------------------------------------------------------
# Timing form
# ---------------------------------------------------------------------------

TIMING_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("char_delay_ms", "Base delay", FieldKind.FLOAT, 80.0, suffix=" ms", maximum=60_000),
    FieldSpec("char_jitter_ms", "Jitter", FieldKind.FLOAT, 35.0, suffix=" ms", maximum=60_000),
    FieldSpec("min_delay_ms", "Minimum delay", FieldKind.FLOAT, 20.0, suffix=" ms", maximum=60_000),
    FieldSpec(
        "max_delay_ms", "Maximum delay", FieldKind.FLOAT, 250.0, suffix=" ms", maximum=60_000
    ),
    FieldSpec("word_pause_ms", "Word pause", FieldKind.FLOAT, 0.0, suffix=" ms", maximum=60_000),
    FieldSpec(
        "punctuation_pause_ms",
        "Punctuation pause",
        FieldKind.FLOAT,
        0.0,
        suffix=" ms",
        maximum=60_000,
    ),
    FieldSpec(
        "action_delay_ms", "Action delay", FieldKind.FLOAT, 120.0, suffix=" ms", maximum=60_000
    ),
    FieldSpec(
        "action_jitter_ms", "Action jitter", FieldKind.FLOAT, 40.0, suffix=" ms", maximum=60_000
    ),
    FieldSpec(
        "mouse_move_duration_ms", "Mouse move", FieldKind.FLOAT, 200.0, suffix=" ms", maximum=60_000
    ),
    FieldSpec(
        "mouse_move_jitter_ms",
        "Mouse move jitter",
        FieldKind.FLOAT,
        50.0,
        suffix=" ms",
        maximum=60_000,
    ),
)


def build_timing_profile(values: Mapping[str, Any]) -> TimingProfile:
    """Construct a profile from form values.

    Invalid combinations (``min > max``, negatives) raise
    :class:`ValidationError`; the UI shows the message instead of silently
    clamping the user's input.
    """
    numbers = {spec.name: float(values.get(spec.name, spec.default)) for spec in TIMING_FIELDS}
    return TimingProfile(
        char_delay_ms=numbers["char_delay_ms"],
        char_jitter_ms=numbers["char_jitter_ms"],
        min_delay_ms=numbers["min_delay_ms"],
        max_delay_ms=numbers["max_delay_ms"],
        word_pause_ms=numbers["word_pause_ms"],
        punctuation_pause_ms=numbers["punctuation_pause_ms"],
        action_delay_ms=numbers["action_delay_ms"],
        action_jitter_ms=numbers["action_jitter_ms"],
        mouse_move_duration_ms=numbers["mouse_move_duration_ms"],
        mouse_move_jitter_ms=numbers["mouse_move_jitter_ms"],
    )


def timing_to_values(profile: TimingProfile) -> dict[str, Any]:
    """Form values for an existing profile."""
    return {spec.name: getattr(profile, spec.name) for spec in TIMING_FIELDS}


def preview_delays(
    profile: TimingProfile,
    *,
    seed: int | None = None,
    count: int = 5,
    sample: str = "ab cd,",
) -> list[float]:
    """Sample the delays a run would use.

    Uses :class:`TimingService` - the same code path as execution - so the
    preview cannot drift from reality. ``sample`` decides which delay sources
    appear (characters, a word boundary and punctuation).
    """
    timing = TimingService(profile, seed=seed)
    characters = (sample * (count // max(1, len(sample)) + 1))[:count]
    return [timing.char_delay_ms(char) for char in characters]


def format_preview(delays: Sequence[float]) -> str:
    """Render sampled delays for the preview label."""
    if not delays:
        return "no delays configured"
    return "  ".join(f"{delay:.0f} ms" for delay in delays)


# ---------------------------------------------------------------------------
# Run log and error presentation
# ---------------------------------------------------------------------------


def format_event(event: RunEvent, *, timestamp: datetime | None = None) -> str | None:
    """Render an event as a log line, or ``None`` if it is not worth logging."""
    stamp = (timestamp or datetime.now()).strftime("%H:%M:%S")
    text = _event_text(event)
    return None if text is None else f"{stamp}  {text}"


def _event_text(event: RunEvent) -> str | None:
    if isinstance(event, CountdownStarted):
        return f"Countdown started ({event.seconds:g} s)"
    if isinstance(event, CountdownTick):
        return f"Starting in {event.remaining:.0f}..." if event.remaining > 0 else "Starting now"
    if isinstance(event, CountdownCancelled):
        return "Countdown cancelled - no input was sent"
    if isinstance(event, RunStarted):
        mode = " [DRY RUN - no input will be sent]" if event.dry_run else ""
        name = event.plan_name or "automation"
        return f"Run started: {name}, {event.action_count} action(s){mode}"
    if isinstance(event, TargetActivated):
        confirmation = "focus confirmed" if event.verified else "focus not confirmed"
        return f"Target activated: {event.target.describe()} ({confirmation})"
    if isinstance(event, ActionStarted):
        return f"Action {event.index + 1}: {event.description}"
    if isinstance(event, ActionCompleted):
        return None
    if isinstance(event, RunPaused):
        return f"Paused before action {event.index + 1}"
    if isinstance(event, RunResumed):
        return f"Resumed at action {event.index + 1}"
    if isinstance(event, RunFinished):
        detail = f" - {event.error}" if event.error else ""
        return (
            f"Run {event.status.value}: {event.executed_actions} action(s) "
            f"in {event.elapsed_ms:.0f} ms{detail}"
        )
    return None


#: Maps recognisable engine failures onto messages a user can act on.
_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    (
        "could not activate",
        "Unable to activate the selected window.\n"
        "The window may have closed or become unavailable. Refresh the window list.",
    ),
    (
        "did not take focus",
        "The selected window did not take focus, so nothing was typed.\n"
        "Another window may be holding focus; try again or select a different target.",
    ),
    (
        "focus could not be verified",
        "This platform cannot confirm which window has focus.\n"
        "Disable 'require focus verification', or select a target the platform can verify.",
    ),
    (
        "no window control adapter",
        "No window control adapter is available on this system.\n"
        "See the capability banner for details.",
    ),
    (
        "not usable on this host",
        "Input permission or backend unavailable.\n"
        "Check the platform capability status for details.",
    ),
    ("limit", "The run stopped because a configured safety limit was reached."),
)


def friendly_error(report: RunReport) -> str:
    """A user-facing message for a finished run. Never a traceback."""
    if report.status is RunStatus.COMPLETED:
        mode = " (dry run - no input was sent)" if report.dry_run else ""
        return (
            f"Completed {report.executed_actions} action(s) "
            f"in {report.elapsed_ms:.0f} ms{mode}."
        )
    if report.status is RunStatus.STOPPED:
        return "Automation stopped by user."
    if report.status is RunStatus.INVALID:
        issues = "\n".join(
            f"- {issue.message}" for issue in report.issues if issue.severity == "error"
        )
        if issues:
            return f"The automation plan is not valid:\n{issues}"
        return "The plan is not valid."
    error = (report.error or "").lower()
    for needle, message in _ERROR_HINTS:
        if needle in error:
            return message
    return (
        "The run failed unexpectedly. See the run log for details."
        if not report.error
        else f"The run failed: {report.error}"
    )


@dataclass(frozen=True)
class DryRunView:
    """Everything the dry-run panel displays."""

    header: str = "DRY RUN - NO INPUT WILL BE SENT"
    target_text: str = ""
    estimated_duration: str = ""
    lines: tuple[str, ...] = field(default_factory=tuple)
    result: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


def dry_run_view(
    report: RunReport, target: TargetWindow | None, delays: Sequence[float] = ()
) -> DryRunView:
    """Build the dry-run panel content from a report."""
    seconds = report.elapsed_ms / 1000
    duration = (
        f"Estimated duration: {seconds:.1f} s ({report.elapsed_ms:.0f} ms)"
        if report.elapsed_ms
        else "Estimated duration: less than a second"
    )
    lines = tuple(f"{index + 1}. {text}" for index, text in enumerate(report.performed))
    if delays:
        lines += (f"Sample character delays: {format_preview(delays)}",)
    return DryRunView(
        target_text=f"Target: {target.describe()}" if target else "Target: none selected",
        estimated_duration=duration,
        lines=lines,
        result=friendly_error(report),
        warnings=tuple(issue.message for issue in report.issues if issue.severity == "warning"),
    )
