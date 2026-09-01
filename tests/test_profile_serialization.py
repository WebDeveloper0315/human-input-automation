"""Profile serialization: lossless round-trips and strict decoding."""

from __future__ import annotations

import json
from typing import Any

import pytest

from human_input_automation.application.profiles import (
    SCHEMA_VERSION,
    Profile,
    ProfileFormatError,
    TargetIdentity,
    UnsupportedSchemaError,
    action_from_dict,
    action_to_dict,
    migrate,
    plan_from_dict,
    plan_to_dict,
    profile_from_dict,
    profile_to_dict,
)
from human_input_automation.application.profiles.serialization import (
    ACTION_DECODERS,
    identity_from_dict,
    identity_to_dict,
    limits_from_dict,
    options_from_dict,
    timing_from_dict,
)
from human_input_automation.core.actions import (
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
from human_input_automation.core.keys import Key, MouseButton
from human_input_automation.core.plan import AutomationPlan, ExecutionLimits, RunOptions
from human_input_automation.core.target import DisplayServer, PlatformName
from human_input_automation.core.timing import TimingProfile

from .fakes import make_target

ALL_ACTIONS: list[Action] = [
    TypeText(text="hello world"),
    TypeText(text="unicode: ä ß 日本語 🎉 \n\ttabbed", delay_after_ms=25.5),
    KeyPress(key=Key.ENTER),
    KeyPress(key="a", count=7, delay_after_ms=0),
    KeyDown(key=Key.SHIFT),
    KeyUp(key=Key.SHIFT),
    Shortcut.parse("ctrl+shift+p"),
    Shortcut(keys=(Key.META, "+")),
    MouseMove(x=100, y=200),
    MouseMove(x=-40, y=-10, relative=True, duration_ms=250.0, delay_after_ms=10.0),
    MouseClick(),
    MouseClick(button=MouseButton.MIDDLE, x=5, y=6, count=3),
    MouseDown(button=MouseButton.RIGHT),
    MouseUp(button=MouseButton.RIGHT),
    Wait(duration_ms=1500.0),
    Wait(duration_ms=0, delay_after_ms=1),
]


# -- actions --------------------------------------------------------------
@pytest.mark.parametrize("action", ALL_ACTIONS, ids=lambda a: a.describe())
def test_every_action_round_trips(action: Action) -> None:
    assert action_from_dict(action_to_dict(action)) == action


@pytest.mark.parametrize("action", ALL_ACTIONS, ids=lambda a: a.describe())
def test_round_trip_survives_json(action: Action) -> None:
    encoded = json.loads(json.dumps(action_to_dict(action), allow_nan=False))
    assert action_from_dict(encoded) == action


@pytest.mark.parametrize("action", ALL_ACTIONS, ids=lambda a: a.describe())
def test_encoding_writes_every_declared_field(action: Action) -> None:
    """A field added to an action must not silently vanish from saved profiles."""
    import dataclasses

    encoded = action_to_dict(action)
    expected = {"type"} | {field.name for field in dataclasses.fields(action)}
    assert set(encoded) == expected


def test_every_action_type_is_serialisable() -> None:
    """No built-in action may be missing from the wire format."""
    from human_input_automation.core.handlers import default_registry

    registered = {kind for kind in ACTION_DECODERS}
    handled = {action_type.kind for action_type in default_registry()._handlers}
    assert handled == registered


def test_unknown_action_type_is_rejected_by_name() -> None:
    with pytest.raises(ProfileFormatError) as excinfo:
        action_from_dict({"type": "TeleportToMars"})
    assert "Unknown action type: TeleportToMars" in str(excinfo.value)


def test_unknown_action_field_is_rejected() -> None:
    with pytest.raises(ProfileFormatError) as excinfo:
        action_from_dict({"type": "wait", "duration_ms": 10, "shell": "rm -rf /"})
    assert "unknown field(s): shell" in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "type_text"},
        {"type": "type_text", "text": 5},
        {"type": "type_text", "text": ""},
        {"type": "key_press", "key": "nope"},
        {"type": "key_press", "key": "a", "count": 0},
        {"type": "key_press", "key": "a", "count": True},
        {"type": "shortcut", "keys": []},
        {"type": "shortcut", "keys": "ctrl+s"},
        {"type": "mouse_move", "x": 1},
        {"type": "mouse_move", "x": 1.5, "y": 2},
        {"type": "mouse_move", "x": -1, "y": 2},
        {"type": "mouse_click", "button": "elbow"},
        {"type": "wait", "duration_ms": -5},
        {"type": "wait", "duration_ms": "soon"},
        {"type": "wait", "duration_ms": 1, "delay_after_ms": -1},
        {"type": 42},
        [],
    ],
)
def test_malformed_actions_are_rejected(payload: Any) -> None:
    with pytest.raises(ProfileFormatError):
        action_from_dict(payload)


def test_infinite_numbers_are_refused() -> None:
    with pytest.raises(ProfileFormatError):
        action_from_dict({"type": "wait", "duration_ms": float("inf")})


# -- plan pieces ----------------------------------------------------------
def test_timing_round_trips_including_punctuation_set() -> None:
    profile = TimingProfile(
        char_delay_ms=55, word_pause_ms=120, punctuation_chars=".;!", mouse_move_jitter_ms=12
    )
    from human_input_automation.application.profiles.serialization import timing_to_dict

    assert timing_from_dict(timing_to_dict(profile)) == profile


def test_invalid_timing_is_rejected_with_the_domain_message() -> None:
    with pytest.raises(ProfileFormatError) as excinfo:
        timing_from_dict({"min_delay_ms": 500, "max_delay_ms": 100})
    assert "min_delay_ms" in str(excinfo.value)


def test_timing_defaults_fill_in_missing_fields() -> None:
    assert timing_from_dict({}) == TimingProfile()


def test_limits_round_trip_and_reject_nonsense() -> None:
    from human_input_automation.application.profiles.serialization import limits_to_dict

    limits = ExecutionLimits(max_actions=42, max_run_duration_s=None)
    assert limits_from_dict(limits_to_dict(limits)) == limits
    with pytest.raises(ProfileFormatError):
        limits_from_dict({"max_actions": 0})
    with pytest.raises(ProfileFormatError):
        limits_from_dict({"max_run_duration_s": 0})


def test_options_round_trip_but_never_persist_dry_run() -> None:
    """Whether a run is a rehearsal is decided when it starts, not when saved."""
    from human_input_automation.application.profiles.serialization import options_to_dict

    options = RunOptions(dry_run=True, seed=99, require_focus_verification=True)
    decoded = options_from_dict(options_to_dict(options))
    assert decoded.seed == 99
    assert decoded.require_focus_verification
    assert decoded.dry_run is False


def test_negative_seed_is_rejected() -> None:
    with pytest.raises(ProfileFormatError):
        options_from_dict({"seed": -1})


def test_plan_round_trips_with_every_action() -> None:
    plan = AutomationPlan(
        make_target(),
        ALL_ACTIONS,
        timing=TimingProfile(char_delay_ms=33),
        limits=ExecutionLimits(max_actions=99),
        options=RunOptions(seed=7),
    )
    restored = plan_from_dict(plan_to_dict(plan), make_target())
    assert restored.actions == plan.actions
    assert restored.timing == plan.timing
    assert restored.limits == plan.limits
    assert restored.options.seed == 7


def test_a_plan_decoded_without_a_target_cannot_run() -> None:
    """The placeholder target has no capabilities, so validation refuses it."""
    from human_input_automation.core.validation import validate_plan

    plan = plan_from_dict({"actions": [{"type": "wait", "duration_ms": 10}]})
    assert not validate_plan(plan).ok


def test_plan_rejects_unknown_sections() -> None:
    with pytest.raises(ProfileFormatError):
        plan_from_dict({"actions": [], "script": "print(1)"})


# -- target identity ------------------------------------------------------
def test_identity_round_trips() -> None:
    identity = TargetIdentity(
        platform=PlatformName.LINUX,
        display_server=DisplayServer.X11,
        process_name="firefox",
        app_id="org.mozilla.firefox",
        title="Mozilla Firefox",
        title_pattern=r".*Firefox.*",
        handle_hint="0x01800004",
    )
    assert identity_from_dict(identity_to_dict(identity)) == identity


def test_identity_from_a_live_target_drops_runtime_state() -> None:
    identity = TargetIdentity.from_target(make_target())
    encoded = identity_to_dict(identity)
    assert "process_id" not in encoded
    assert "capabilities" not in encoded
    assert encoded["handle_hint"] == "win-1"


def test_invalid_title_pattern_is_rejected() -> None:
    with pytest.raises(ProfileFormatError) as excinfo:
        identity_from_dict({"title_pattern": "([unclosed"})
    assert "regular expression" in str(excinfo.value)


def test_unknown_platform_value_is_rejected() -> None:
    with pytest.raises(ProfileFormatError) as excinfo:
        identity_from_dict({"platform": "atari"})
    assert "unknown platform" in str(excinfo.value)


# -- whole profiles -------------------------------------------------------
def sample_profile() -> Profile:
    return Profile(
        id="4f3e" + "0" * 28,
        name="Open Search",
        description="Focus the search bar and type",
        target=TargetIdentity.from_target(make_target()),
        plan=AutomationPlan(make_target(), ALL_ACTIONS, options=RunOptions(seed=3)),
        created_at="2026-09-01T10:00:00+00:00",
        updated_at="2026-09-01T10:30:00+00:00",
    )


def test_profile_round_trips_through_json() -> None:
    profile = sample_profile()
    text = json.dumps(profile_to_dict(profile), allow_nan=False)
    restored = profile_from_dict(json.loads(text))
    assert restored.id == profile.id
    assert restored.name == profile.name
    assert restored.description == profile.description
    assert restored.target == profile.target
    assert restored.created_at == profile.created_at
    assert restored.plan is not None and profile.plan is not None
    assert restored.plan.actions == profile.plan.actions


def test_the_schema_version_is_always_written() -> None:
    assert profile_to_dict(sample_profile())["schema"] == SCHEMA_VERSION


def test_a_missing_schema_is_rejected_rather_than_guessed() -> None:
    data = profile_to_dict(sample_profile())
    del data["schema"]
    with pytest.raises(ProfileFormatError) as excinfo:
        profile_from_dict(data)
    assert "'schema' is required" in str(excinfo.value)


def test_a_future_schema_is_rejected_explicitly() -> None:
    data = profile_to_dict(sample_profile())
    data["schema"] = 2
    with pytest.raises(UnsupportedSchemaError) as excinfo:
        profile_from_dict(data)
    assert str(excinfo.value) == "Unsupported profile schema version: 2"


@pytest.mark.parametrize("version", ["1", 1.0, True, None, [1]])
def test_a_non_integer_schema_is_rejected(version: Any) -> None:
    data = profile_to_dict(sample_profile())
    data["schema"] = version
    with pytest.raises(ProfileFormatError):
        profile_from_dict(data)


def test_unknown_top_level_fields_are_rejected() -> None:
    data = profile_to_dict(sample_profile())
    data["command"] = "rm -rf /"
    with pytest.raises(ProfileFormatError) as excinfo:
        profile_from_dict(data)
    assert "unknown field(s): command" in str(excinfo.value)


def test_an_empty_name_is_rejected() -> None:
    data = profile_to_dict(sample_profile())
    data["name"] = "   "
    with pytest.raises(ProfileFormatError):
        profile_from_dict(data)


def test_a_tampered_id_is_rejected() -> None:
    data = profile_to_dict(sample_profile())
    data["id"] = "../../etc/passwd"
    with pytest.raises(ProfileFormatError):
        profile_from_dict(data)


def test_a_missing_id_gets_a_fresh_one() -> None:
    data = profile_to_dict(sample_profile())
    del data["id"]
    from human_input_automation.application.profiles.schema import is_valid_profile_id

    assert is_valid_profile_id(profile_from_dict(data).id)


def test_unicode_names_and_text_survive_a_json_file(tmp_path: Any) -> None:
    profile = sample_profile().with_changes(name="Recherche — été 🎉")
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(profile_to_dict(profile), ensure_ascii=False), encoding="utf-8"
    )
    restored = profile_from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert restored.name == "Recherche — été 🎉"
    assert restored.plan is not None
    assert any("日本語" in getattr(a, "text", "") for a in restored.plan.actions)


# -- migration ------------------------------------------------------------
def test_current_version_needs_no_migration() -> None:
    data = {"schema": SCHEMA_VERSION, "name": "x"}
    assert migrate(data) == data


def test_a_registered_migration_upgrades_older_data() -> None:
    """Only version 1 exists today; the mechanism is proven with a fake one."""

    def upgrade_zero(data: dict[str, Any]) -> dict[str, Any]:
        data["schema"] = 1
        data["name"] = data.pop("title", "Untitled profile")
        return data

    migrated = migrate({"schema": 0, "title": "Old"}, {0: upgrade_zero})
    assert migrated["schema"] == 1 and migrated["name"] == "Old"


def test_a_migration_that_does_not_advance_is_an_error() -> None:
    with pytest.raises(ProfileFormatError):
        migrate({"schema": 0}, {0: lambda data: data})


def test_an_unreachable_version_is_unsupported() -> None:
    with pytest.raises(UnsupportedSchemaError):
        migrate({"schema": 99}, {})
