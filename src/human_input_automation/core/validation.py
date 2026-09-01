"""Plan, action and target validation.

Validation runs before a single keystroke is sent. It separates *errors* (the
run must not start) from *warnings* (the run can start, but the user should know
something - for example that the platform cannot confirm the target has focus).
"""

from __future__ import annotations

from .actions import (
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
from .errors import Severity, ValidationIssue, ValidationResult
from .keys import Key, KeyLike, format_key
from .plan import AutomationPlan, ExecutionLimits
from .screen import ScreenGeometry
from .target import PlatformName, PlatformReport, TargetWindow


def _error(code: str, message: str, location: str = "") -> ValidationIssue:
    return ValidationIssue(code, message, location, Severity.ERROR)


def _warning(code: str, message: str, location: str = "") -> ValidationIssue:
    return ValidationIssue(code, message, location, Severity.WARNING)


def validate_target(
    target: TargetWindow,
    *,
    dry_run: bool = False,
    host: PlatformReport | None = None,
) -> list[ValidationIssue]:
    """Check that a target can plausibly receive input on this host."""
    issues: list[ValidationIssue] = []
    location = "target"

    if not target.handle:
        issues.append(_error("target.missing_handle", "no target window selected", location))

    capabilities = target.capabilities
    if not capabilities.can_send_synthetic_input:
        severity_factory = _warning if dry_run else _error
        issues.append(
            severity_factory(
                "target.no_input_capability",
                "this platform/adapter cannot send synthetic input to the target",
                location,
            )
        )
    if capabilities.requires_permission:
        issues.append(
            _warning(
                "target.permission_required",
                f"requires {capabilities.requires_permission}; "
                "input may silently do nothing until it is granted",
                location,
            )
        )
    if not target.is_focused_window and not capabilities.can_activate:
        issues.append(
            _warning(
                "target.cannot_activate",
                "the target window cannot be focused programmatically; "
                "focus it manually before starting",
                location,
            )
        )
    if not capabilities.can_verify_focus:
        issues.append(
            _warning(
                "target.cannot_verify_focus",
                "focus cannot be verified on this platform; "
                "input goes wherever the system directs it",
                location,
            )
        )
    if target.is_focused_window:
        issues.append(
            _warning(
                "target.focused_window",
                "no explicit target selected; input goes to the focused window",
                location,
            )
        )

    if host is not None and target.platform not in (PlatformName.UNKNOWN, host.platform):
        issues.append(
            _error(
                "target.platform_mismatch",
                f"target was captured on {target.platform.value} "
                f"but this host is {host.platform.value}",
                location,
            )
        )
    return issues


def _keys_of(action: Action) -> tuple[KeyLike, ...]:
    """Every key an action would send."""
    if isinstance(action, (KeyPress, KeyDown, KeyUp)):
        return (action.key,)
    if isinstance(action, Shortcut):
        return action.keys
    return ()


def _coordinates_of(action: Action) -> tuple[int, int] | None:
    """Absolute screen coordinates an action would move to, if any."""
    if isinstance(action, MouseMove) and not action.relative:
        return (action.x, action.y)
    if isinstance(action, MouseClick):
        return action.position
    return None


def validate_action(
    action: Action,
    index: int,
    limits: ExecutionLimits,
    host: PlatformReport | None = None,
    screen: ScreenGeometry | None = None,
) -> list[ValidationIssue]:
    """Check one action against the limits, the host and the screen layout."""
    issues: list[ValidationIssue] = []
    location = f"actions[{index}]"

    if host is not None and host.unsupported_keys:
        unsupported = set(host.unsupported_keys)
        for key in _keys_of(action):
            if isinstance(key, Key) and key in unsupported:
                issues.append(
                    _error(
                        "action.key_unsupported",
                        f"the {format_key(key)!r} key cannot be sent on "
                        f"{host.platform.value}; this is a platform limitation",
                        location,
                    )
                )

    coordinates = _coordinates_of(action)
    if coordinates is not None and screen is not None and screen.is_known:
        x, y = coordinates
        if not screen.contains(x, y):
            left, top, right, bottom = screen.virtual_bounds()
            issues.append(
                _error(
                    "action.coordinates_off_screen",
                    f"({x}, {y}) is not on any monitor; the desktop spans "
                    f"({left}, {top}) to ({right}, {bottom}) in "
                    f"{screen.coordinate_space.value} coordinates",
                    location,
                )
            )

    if isinstance(action, TypeText) and len(action.text) > limits.max_text_length:
        issues.append(
            _error(
                "action.text_too_long",
                f"text is {len(action.text)} characters, limit is {limits.max_text_length}",
                location,
            )
        )
    if (
        isinstance(action, Wait)
        and limits.max_run_duration_s is not None
        and action.duration_ms / 1000 > limits.max_run_duration_s
    ):
        issues.append(
            _error(
                "action.wait_exceeds_run_limit",
                f"wait of {action.duration_ms:g} ms exceeds the "
                f"{limits.max_run_duration_s:g} s run limit",
                location,
            )
        )
    return issues


def _validate_balance(actions: tuple[Action, ...]) -> list[ValidationIssue]:
    """Warn about keys or buttons left held at the end of a plan."""
    issues: list[ValidationIssue] = []
    held_keys: list[object] = []
    held_buttons: list[object] = []
    for action in actions:
        if isinstance(action, KeyDown):
            held_keys.append(action.key)
        elif isinstance(action, KeyUp) and action.key in held_keys:
            held_keys.remove(action.key)
        elif isinstance(action, MouseDown):
            held_buttons.append(action.button)
        elif isinstance(action, MouseUp) and action.button in held_buttons:
            held_buttons.remove(action.button)
    if held_keys:
        issues.append(
            _warning(
                "plan.unbalanced_keys",
                f"{len(held_keys)} key(s) are never released; "
                "the engine releases them when the run ends",
                "actions",
            )
        )
    if held_buttons:
        issues.append(
            _warning(
                "plan.unbalanced_buttons",
                f"{len(held_buttons)} mouse button(s) are never released; "
                "the engine releases them when the run ends",
                "actions",
            )
        )
    return issues


def validate_plan(
    plan: AutomationPlan,
    *,
    host: PlatformReport | None = None,
    screen: ScreenGeometry | None = None,
) -> ValidationResult:
    """Validate a whole plan: target, actions, limits, keys and coordinates."""
    issues: list[ValidationIssue] = []
    limits = plan.limits

    if not plan.actions:
        issues.append(_error("plan.no_actions", "the plan contains no actions", "actions"))
    if len(plan.actions) > limits.max_actions:
        issues.append(
            _error(
                "plan.too_many_actions",
                f"{len(plan.actions)} actions exceed the limit of {limits.max_actions}",
                "actions",
            )
        )
    total_text = plan.total_text_length
    if total_text > limits.max_total_characters:
        issues.append(
            _error(
                "plan.too_much_text",
                f"{total_text} characters exceed the total limit of {limits.max_total_characters}",
                "actions",
            )
        )

    for index, action in enumerate(plan.actions):
        issues.extend(validate_action(action, index, limits, host, screen))

    issues.extend(_validate_balance(plan.actions))
    issues.extend(
        validate_target(plan.target, dry_run=plan.options.dry_run, host=host)
    )
    return ValidationResult(tuple(issues))
