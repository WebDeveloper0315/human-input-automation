"""Pure conversion between profiles and plain dictionaries.

Nothing in this module touches the filesystem, Qt, or an OS API. It is
deliberately boring, because it is the boundary where **untrusted input** meets
the domain model: a profile file is data someone may have edited by hand or
received from elsewhere, so decoding is strict and every failure names the field
that caused it.

Two asymmetric halves:

* **Encoding is generic** - it walks the dataclass fields of an action, so a
  field added to an action in future cannot silently vanish from saved
  profiles (``tests/test_profile_serialization.py`` asserts exactly that).
* **Decoding is explicit** - each action type has a decoder that accepts only
  the fields it knows, so a malformed or unknown structure is rejected rather
  than half-applied.

Unknown-field policy: **structural objects reject unknown keys.** Silently
ignoring a key means silently ignoring the user's intent, and a future format
change is handled by the schema version plus the migration registry instead.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Callable, Mapping
from typing import Any

from ...core.actions import (
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
from ...core.errors import ValidationError
from ...core.keys import Key, KeyLike, MouseButton, normalize_key
from ...core.plan import AutomationPlan, ExecutionLimits, RunOptions
from ...core.target import DisplayServer, PlatformName, TargetWindow, WindowCapabilities
from ...core.timing import TimingProfile
from .schema import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    Profile,
    ProfileFormatError,
    TargetIdentity,
    UnsupportedSchemaError,
    is_valid_profile_id,
    new_profile_id,
)

# ---------------------------------------------------------------------------
# Primitive readers
# ---------------------------------------------------------------------------


def _fail(message: str, location: str = "") -> ProfileFormatError:
    return ProfileFormatError(f"{location}: {message}" if location else message)


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(f"expected an object, got {type(value).__name__}", location)
    for key in value:
        if not isinstance(key, str):
            raise _fail(f"object keys must be strings, got {type(key).__name__}", location)
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise _fail(f"unknown field(s): {', '.join(unknown)}", location)


def _string(data: Mapping[str, Any], key: str, location: str, *, default: str | None = None) -> str:
    value = data.get(key, default)
    if value is None or not isinstance(value, str):
        raise _fail(f"{key!r} must be a string", location)
    return value


def _optional_string(data: Mapping[str, Any], key: str, location: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _fail(f"{key!r} must be a string or null", location)
    return value


def _number(value: Any, key: str, location: str) -> float:
    # bool is an int in Python; accepting it here would let `true` mean 1.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{key!r} must be a number", location)
    if not math.isfinite(float(value)):
        raise _fail(f"{key!r} must be a finite number", location)
    return float(value)


def _float(
    data: Mapping[str, Any], key: str, location: str, *, default: float | None = None
) -> float:
    if key not in data:
        if default is None:
            raise _fail(f"{key!r} is required", location)
        return default
    return _number(data[key], key, location)


def _optional_float(data: Mapping[str, Any], key: str, location: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    return _number(value, key, location)


def _int(data: Mapping[str, Any], key: str, location: str, *, default: int | None = None) -> int:
    if key not in data or data[key] is None:
        if default is None:
            raise _fail(f"{key!r} is required", location)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{key!r} must be an integer", location)
    return value


def _optional_int(data: Mapping[str, Any], key: str, location: str) -> int | None:
    if data.get(key) is None:
        return None
    return _int(data, key, location)


def _bool(data: Mapping[str, Any], key: str, location: str, *, default: bool = False) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise _fail(f"{key!r} must be true or false", location)
    return value


def _enum(enum_type: type[Any], value: Any, key: str, location: str, default: Any) -> Any:
    if value is None:
        return default
    if not isinstance(value, str):
        raise _fail(f"{key!r} must be a string", location)
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(sorted(member.value for member in enum_type))
        raise _fail(f"unknown {key} {value!r}; expected one of: {allowed}", location) from None


def _key(value: Any, location: str) -> KeyLike:
    if not isinstance(value, str):
        raise _fail("keys must be strings", location)
    try:
        return normalize_key(value, location=location)
    except ValidationError as error:
        raise _fail(error.issues[0].message if error.issues else str(error), location) from None


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _encode_value(value: Any, location: str) -> Any:
    if isinstance(value, (Key, MouseButton)):
        return value.value
    if isinstance(value, (str, bool, int, float)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            raise _fail("non-finite numbers cannot be stored", location)
        return value
    if isinstance(value, (tuple, list)):
        return [_encode_value(item, location) for item in value]
    raise _fail(f"cannot serialise a value of type {type(value).__name__}", location)


def action_to_dict(action: Action) -> dict[str, Any]:
    """Encode an action, including every field it declares.

    Generic on purpose: a new field on an action class is written out
    automatically instead of being quietly dropped from saved profiles.
    """
    payload: dict[str, Any] = {"type": action.kind}
    for field in dataclasses.fields(action):
        payload[field.name] = _encode_value(getattr(action, field.name), action.kind)
    return payload


def _decode_type_text(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return TypeText(text=_string(data, "text", location), delay_after_ms=delay)


def _decode_key_press(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return KeyPress(
        key=_key(data.get("key"), location),
        count=_int(data, "count", location, default=1),
        delay_after_ms=delay,
    )


def _decode_key_down(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return KeyDown(key=_key(data.get("key"), location), delay_after_ms=delay)


def _decode_key_up(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return KeyUp(key=_key(data.get("key"), location), delay_after_ms=delay)


def _decode_shortcut(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    raw = data.get("keys")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise _fail("'keys' must be a non-empty list of key names", location)
    return Shortcut(keys=tuple(_key(item, location) for item in raw), delay_after_ms=delay)


def _decode_mouse_move(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return MouseMove(
        x=_int(data, "x", location),
        y=_int(data, "y", location),
        relative=_bool(data, "relative", location),
        duration_ms=_optional_float(data, "duration_ms", location),
        delay_after_ms=delay,
    )


def _decode_mouse_click(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return MouseClick(
        button=_enum(MouseButton, data.get("button"), "button", location, MouseButton.LEFT),
        x=_optional_int(data, "x", location),
        y=_optional_int(data, "y", location),
        count=_int(data, "count", location, default=1),
        delay_after_ms=delay,
    )


def _decode_mouse_down(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return MouseDown(
        button=_enum(MouseButton, data.get("button"), "button", location, MouseButton.LEFT),
        delay_after_ms=delay,
    )


def _decode_mouse_up(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return MouseUp(
        button=_enum(MouseButton, data.get("button"), "button", location, MouseButton.LEFT),
        delay_after_ms=delay,
    )


def _decode_wait(data: Mapping[str, Any], location: str, delay: float | None) -> Action:
    return Wait(duration_ms=_float(data, "duration_ms", location), delay_after_ms=delay)


ActionDecoder = Callable[[Mapping[str, Any], str, "float | None"], Action]

#: Wire name -> (action class, decoder). The wire name is the action's own
#: ``kind``, so the stored format and the domain model cannot drift apart.
ACTION_DECODERS: dict[str, tuple[type[Action], ActionDecoder]] = {
    TypeText.kind: (TypeText, _decode_type_text),
    KeyPress.kind: (KeyPress, _decode_key_press),
    KeyDown.kind: (KeyDown, _decode_key_down),
    KeyUp.kind: (KeyUp, _decode_key_up),
    Shortcut.kind: (Shortcut, _decode_shortcut),
    MouseMove.kind: (MouseMove, _decode_mouse_move),
    MouseClick.kind: (MouseClick, _decode_mouse_click),
    MouseDown.kind: (MouseDown, _decode_mouse_down),
    MouseUp.kind: (MouseUp, _decode_mouse_up),
    Wait.kind: (Wait, _decode_wait),
}


def action_from_dict(data: Any, location: str = "action") -> Action:
    """Decode one action, rejecting unknown types and unknown fields."""
    mapping = _mapping(data, location)
    kind = mapping.get("type")
    if not isinstance(kind, str):
        raise _fail("'type' is required and must be a string", location)
    entry = ACTION_DECODERS.get(kind)
    if entry is None:
        known = ", ".join(sorted(ACTION_DECODERS))
        raise _fail(f"Unknown action type: {kind}. Known types: {known}", location)

    action_type, decoder = entry
    allowed = {"type"} | {field.name for field in dataclasses.fields(action_type)}
    _reject_unknown(mapping, allowed, f"{location} ({kind})")

    delay = _optional_float(mapping, "delay_after_ms", f"{location} ({kind})")
    try:
        return decoder(mapping, f"{location} ({kind})", delay)
    except ValidationError as error:
        message = "; ".join(issue.message for issue in error.issues) or str(error)
        raise _fail(message, f"{location} ({kind})") from None


# ---------------------------------------------------------------------------
# Plan pieces
# ---------------------------------------------------------------------------


def timing_to_dict(timing: TimingProfile) -> dict[str, Any]:
    return {field.name: getattr(timing, field.name) for field in dataclasses.fields(timing)}


def timing_from_dict(data: Any, location: str = "plan.timing") -> TimingProfile:
    mapping = _mapping(data, location)
    defaults = TimingProfile()
    allowed = {field.name for field in dataclasses.fields(TimingProfile)}
    _reject_unknown(mapping, allowed, location)
    numbers = {
        name: _float(mapping, name, location, default=getattr(defaults, name))
        for name in allowed
        if name != "punctuation_chars"
    }
    try:
        return TimingProfile(
            punctuation_chars=_string(
                mapping, "punctuation_chars", location, default=defaults.punctuation_chars
            ),
            **numbers,
        )
    except ValidationError as error:
        raise _fail("; ".join(issue.message for issue in error.issues), location) from None


def limits_to_dict(limits: ExecutionLimits) -> dict[str, Any]:
    return {field.name: getattr(limits, field.name) for field in dataclasses.fields(limits)}


def limits_from_dict(data: Any, location: str = "plan.limits") -> ExecutionLimits:
    mapping = _mapping(data, location)
    defaults = ExecutionLimits()
    allowed = {field.name for field in dataclasses.fields(ExecutionLimits)}
    _reject_unknown(mapping, allowed, location)
    duration = mapping.get("max_run_duration_s", defaults.max_run_duration_s)
    limits = ExecutionLimits(
        max_actions=_int(mapping, "max_actions", location, default=defaults.max_actions),
        max_text_length=_int(
            mapping, "max_text_length", location, default=defaults.max_text_length
        ),
        max_total_characters=_int(
            mapping, "max_total_characters", location, default=defaults.max_total_characters
        ),
        max_run_duration_s=None
        if duration is None
        else _number(duration, "max_run_duration_s", location),
    )
    for name in ("max_actions", "max_text_length", "max_total_characters"):
        if getattr(limits, name) < 1:
            raise _fail(f"{name!r} must be at least 1", location)
    if limits.max_run_duration_s is not None and limits.max_run_duration_s <= 0:
        raise _fail("'max_run_duration_s' must be positive or null", location)
    return limits


def options_to_dict(options: RunOptions) -> dict[str, Any]:
    return {field.name: getattr(options, field.name) for field in dataclasses.fields(options)}


def options_from_dict(data: Any, location: str = "plan.options") -> RunOptions:
    mapping = _mapping(data, location)
    defaults = RunOptions()
    _reject_unknown(mapping, {field.name for field in dataclasses.fields(RunOptions)}, location)
    seed = _optional_int(mapping, "seed", location)
    if seed is not None and seed < 0:
        raise _fail("'seed' must not be negative", location)
    return RunOptions(
        # A saved profile never carries dry-run state: whether a run is a
        # rehearsal is a decision made at the moment it is started.
        dry_run=False,
        seed=seed,
        require_focus_verification=_bool(
            mapping,
            "require_focus_verification",
            location,
            default=defaults.require_focus_verification,
        ),
        reverify_focus=_bool(
            mapping, "reverify_focus", location, default=defaults.reverify_focus
        ),
    )


def identity_to_dict(identity: TargetIdentity) -> dict[str, Any]:
    return {
        "platform": identity.platform.value,
        "display_server": identity.display_server.value,
        "process_name": identity.process_name,
        "app_id": identity.app_id,
        "title": identity.title,
        "title_pattern": identity.title_pattern,
        "handle_hint": identity.handle_hint,
    }


def identity_from_dict(data: Any, location: str = "target") -> TargetIdentity:
    mapping = _mapping(data, location)
    _reject_unknown(
        mapping,
        {
            "platform",
            "display_server",
            "process_name",
            "app_id",
            "title",
            "title_pattern",
            "handle_hint",
        },
        location,
    )
    pattern = _optional_string(mapping, "title_pattern", location)
    if pattern is not None:
        try:
            re.compile(pattern)
        except re.error as error:
            raise _fail(
                f"'title_pattern' is not a valid regular expression: {error}", location
            ) from None
    return TargetIdentity(
        platform=_enum(
            PlatformName, mapping.get("platform"), "platform", location, PlatformName.UNKNOWN
        ),
        display_server=_enum(
            DisplayServer,
            mapping.get("display_server"),
            "display_server",
            location,
            DisplayServer.UNKNOWN,
        ),
        process_name=_optional_string(mapping, "process_name", location),
        app_id=_optional_string(mapping, "app_id", location),
        title=_optional_string(mapping, "title", location),
        title_pattern=pattern,
        handle_hint=_optional_string(mapping, "handle_hint", location),
    )


def plan_to_dict(plan: AutomationPlan) -> dict[str, Any]:
    """Encode the runnable part of a profile.

    The target is *not* included here: a plan's live ``TargetWindow`` carries
    handles, a process id and platform capabilities, none of which survive a
    restart. Profiles store a :class:`TargetIdentity` instead.
    """
    return {
        "actions": [action_to_dict(action) for action in plan.actions],
        "timing": timing_to_dict(plan.timing),
        "limits": limits_to_dict(plan.limits),
        "options": options_to_dict(plan.options),
    }


def _placeholder_target() -> TargetWindow:
    """A target with no handle and no capabilities.

    Used when a plan is decoded before its target has been resolved: it cannot
    pass validation, so a profile whose application is not running can be
    loaded and inspected but never run.
    """
    return TargetWindow(handle="", platform=PlatformName.UNKNOWN, capabilities=WindowCapabilities())


def plan_from_dict(
    data: Any, target: TargetWindow | None = None, location: str = "plan"
) -> AutomationPlan:
    """Decode a plan, attaching ``target`` (or an empty placeholder).

    The placeholder deliberately has no capabilities, so a plan decoded without
    a resolved target cannot pass :func:`validate_plan` and therefore cannot run.
    """
    mapping = _mapping(data, location)
    _reject_unknown(mapping, {"actions", "timing", "limits", "options"}, location)

    raw_actions = mapping.get("actions")
    if not isinstance(raw_actions, list):
        raise _fail("'actions' must be a list", location)
    actions = [
        action_from_dict(item, f"{location}.actions[{index}]")
        for index, item in enumerate(raw_actions)
    ]
    return AutomationPlan(
        target=target or _placeholder_target(),
        actions=actions,
        timing=timing_from_dict(mapping.get("timing", {}), f"{location}.timing"),
        limits=limits_from_dict(mapping.get("limits", {}), f"{location}.limits"),
        options=options_from_dict(mapping.get("options", {}), f"{location}.options"),
    )


# ---------------------------------------------------------------------------
# Profiles and migration
# ---------------------------------------------------------------------------

#: ``from_version -> upgrade function``. Empty while only version 1 exists; the
#: mechanism is here so a future version 2 needs one entry, not a change at
#: every call site.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate(
    data: Mapping[str, Any],
    migrations: Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Upgrade raw profile data to :data:`SCHEMA_VERSION`.

    Raises :class:`UnsupportedSchemaError` for a version this build cannot reach
    - notably any version newer than its own. Never guesses the version from the
    fields present.
    """
    registry = MIGRATIONS if migrations is None else migrations
    if "schema" not in data:
        raise ProfileFormatError("'schema' is required; refusing to guess the profile version")
    version = data["schema"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProfileFormatError(f"'schema' must be an integer, got {version!r}")

    current = dict(data)
    seen: set[int] = set()
    while version != SCHEMA_VERSION:
        if version in seen:  # pragma: no cover - guards a malformed registry
            raise UnsupportedSchemaError(version)
        seen.add(version)
        upgrade = registry.get(version)
        if upgrade is None:
            raise UnsupportedSchemaError(version)
        current = upgrade(dict(current))
        next_version = current.get("schema")
        if not isinstance(next_version, int) or next_version == version:
            raise ProfileFormatError(f"migration from schema {version} did not advance the version")
        version = next_version
    if version not in SUPPORTED_SCHEMA_VERSIONS:  # pragma: no cover - defensive
        raise UnsupportedSchemaError(version)
    return current


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    """Encode a profile. Pure: no filesystem, no Qt, no OS calls."""
    plan = profile.plan
    return {
        "schema": SCHEMA_VERSION,
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "target": identity_to_dict(profile.target),
        "plan": plan_to_dict(plan) if plan is not None else {
            "actions": [],
            "timing": timing_to_dict(TimingProfile()),
            "limits": limits_to_dict(ExecutionLimits()),
            "options": options_to_dict(RunOptions()),
        },
    }


def profile_from_dict(
    data: Any,
    migrations: Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
) -> Profile:
    """Decode a profile from untrusted data.

    Structural validation only. Domain validation (limits, capabilities,
    coordinates) is the existing :func:`validate_plan`, run separately once a
    target has been resolved - this function never duplicates it.
    """
    mapping = _mapping(data, "profile")
    migrated = _mapping(migrate(mapping, migrations), "profile")
    _reject_unknown(
        migrated,
        {"schema", "id", "name", "description", "created_at", "updated_at", "target", "plan"},
        "profile",
    )

    profile_id = _optional_string(migrated, "id", "profile") or new_profile_id()
    if not is_valid_profile_id(profile_id):
        raise _fail("'id' must be 32 lowercase hexadecimal characters", "profile")

    name = _string(migrated, "name", "profile", default="Untitled profile").strip()
    if not name:
        raise _fail("'name' must not be empty", "profile")

    identity = identity_from_dict(migrated.get("target", {}), "profile.target")
    plan = plan_from_dict(migrated.get("plan", {"actions": []}), None, "profile.plan")
    return Profile(
        id=profile_id,
        name=name,
        description=_string(migrated, "description", "profile", default=""),
        target=identity,
        plan=plan,
        created_at=_optional_string(migrated, "created_at", "profile"),
        updated_at=_optional_string(migrated, "updated_at", "profile"),
    )
