"""The capability matrix: states, permissions and the boolean derivation."""

from __future__ import annotations

import pytest

from human_input_automation.core.capabilities import (
    Capability,
    CapabilityMatrix,
    CapabilityName,
    CapabilityState,
)
from human_input_automation.core.target import WindowCapabilities


def test_unknown_is_permitted_but_not_certain() -> None:
    """Unknown means "try and warn", never "no"."""
    assert CapabilityState.UNKNOWN.is_permitted
    assert not CapabilityState.UNKNOWN.is_certain
    assert CapabilityState.AVAILABLE.is_permitted
    assert CapabilityState.RESTRICTED.is_permitted
    assert not CapabilityState.DENIED.is_permitted
    assert not CapabilityState.UNAVAILABLE.is_permitted


def test_missing_entries_report_unknown_not_unavailable() -> None:
    matrix = CapabilityMatrix()
    assert matrix.state(CapabilityName.KEYBOARD_INPUT) is CapabilityState.UNKNOWN
    assert matrix.reason(CapabilityName.KEYBOARD_INPUT)


def test_matrix_covers_every_capability_when_built_unknown() -> None:
    matrix = CapabilityMatrix.unknown()
    assert {capability.name for capability in matrix} == set(CapabilityName)


def test_missing_permissions_are_deduplicated_and_only_from_denied() -> None:
    matrix = CapabilityMatrix.from_capabilities(
        [
            Capability(CapabilityName.KEYBOARD_INPUT, CapabilityState.DENIED, permission="Perm A"),
            Capability(CapabilityName.MOUSE_MOVE, CapabilityState.DENIED, permission="Perm A"),
            Capability(CapabilityName.GLOBAL_HOTKEY, CapabilityState.DENIED, permission="Perm B"),
            Capability(
                CapabilityName.WINDOW_ACTIVATION, CapabilityState.UNKNOWN, permission="Perm C"
            ),
        ]
    )
    assert matrix.missing_permissions() == ("Perm A", "Perm B")


def test_rows_render_every_capability_in_order() -> None:
    rows = CapabilityMatrix.unknown("because").rows()
    assert len(rows) == len(CapabilityName)
    assert rows[0] == (CapabilityName.WINDOW_ENUMERATION.value, "unknown", "because")


def test_with_capability_returns_a_new_matrix() -> None:
    matrix = CapabilityMatrix.unknown()
    updated = matrix.with_capability(
        Capability(CapabilityName.KEYBOARD_INPUT, CapabilityState.AVAILABLE)
    )
    assert updated.state(CapabilityName.KEYBOARD_INPUT) is CapabilityState.AVAILABLE
    assert matrix.state(CapabilityName.KEYBOARD_INPUT) is CapabilityState.UNKNOWN


def matrix_of(**states: CapabilityState) -> CapabilityMatrix:
    return CapabilityMatrix.from_capabilities(
        Capability(CapabilityName(name), state) for name, state in states.items()
    )


def test_booleans_are_derived_from_the_matrix() -> None:
    capabilities = WindowCapabilities.from_matrix(
        matrix_of(
            window_enumeration=CapabilityState.AVAILABLE,
            window_activation=CapabilityState.AVAILABLE,
            focus_verification=CapabilityState.AVAILABLE,
            keyboard_input=CapabilityState.AVAILABLE,
        )
    )
    assert capabilities.can_enumerate
    assert capabilities.can_activate
    assert capabilities.can_verify_focus
    assert capabilities.can_send_synthetic_input


def test_restricted_still_counts_as_usable() -> None:
    capabilities = WindowCapabilities.from_matrix(
        matrix_of(
            window_enumeration=CapabilityState.RESTRICTED,
            keyboard_input=CapabilityState.RESTRICTED,
        )
    )
    assert capabilities.can_enumerate and capabilities.can_send_synthetic_input


def test_focus_verification_is_only_claimed_when_certain() -> None:
    for state in (CapabilityState.RESTRICTED, CapabilityState.UNKNOWN):
        capabilities = WindowCapabilities.from_matrix(matrix_of(focus_verification=state))
        assert not capabilities.can_verify_focus


@pytest.mark.parametrize("state", [CapabilityState.DENIED, CapabilityState.UNAVAILABLE])
def test_denied_and_unavailable_block_input(state: CapabilityState) -> None:
    capabilities = WindowCapabilities.from_matrix(matrix_of(keyboard_input=state))
    assert not capabilities.can_send_synthetic_input


def test_the_blocking_permission_is_carried_into_the_booleans() -> None:
    matrix = CapabilityMatrix.from_capabilities(
        [
            Capability(
                CapabilityName.KEYBOARD_INPUT,
                CapabilityState.DENIED,
                "needs permission",
                permission="macOS Accessibility permission",
            )
        ]
    )
    capabilities = WindowCapabilities.from_matrix(matrix)
    assert capabilities.requires_permission == "macOS Accessibility permission"
