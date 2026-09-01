"""Fine-grained platform capability reporting.

Phase 1 and 2 modelled capabilities as booleans, which cannot express the
difference between "this platform does not have the feature", "the user has not
granted permission yet", "the platform allows a reduced form of it" and "we
could not find out". Those distinctions matter: a denied permission is fixable
by the user, an unavailable capability is not, and "unknown" must never be
displayed as "no".

The boolean :class:`~.target.WindowCapabilities` used by the engine is derived
from this matrix, so the engine keeps its simple gate while the UI and the
diagnostics get the full picture.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class CapabilityName(StrEnum):
    """Every capability the application reasons about."""

    WINDOW_ENUMERATION = "window_enumeration"
    WINDOW_ACTIVATION = "window_activation"
    FOCUS_VERIFICATION = "focus_verification"
    KEYBOARD_INPUT = "keyboard_input"
    KEY_HOLD = "key_hold"
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    GLOBAL_HOTKEY = "global_hotkey"
    PROCESS_INFO = "process_info"
    MULTI_MONITOR = "multi_monitor"


class CapabilityState(StrEnum):
    """How available a capability is.

    * ``AVAILABLE`` - works.
    * ``RESTRICTED`` - works in a reduced form; the reason says how.
    * ``DENIED`` - the platform supports it but permission is missing.
    * ``UNAVAILABLE`` - the platform or backend does not provide it at all.
    * ``UNKNOWN`` - could not be determined. Never render this as "no".
    """

    AVAILABLE = "available"
    RESTRICTED = "restricted"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"

    @property
    def is_permitted(self) -> bool:
        """True when an attempt is allowed (unknown counts as "try, and warn")."""
        return self not in (CapabilityState.UNAVAILABLE, CapabilityState.DENIED)

    @property
    def is_certain(self) -> bool:
        return self is not CapabilityState.UNKNOWN


@dataclass(frozen=True)
class Capability:
    """One capability, with enough context for the UI to explain it."""

    name: CapabilityName
    state: CapabilityState
    reason: str = ""
    permission: str | None = None
    permission_category: str | None = None
    requires_restart: bool = False

    @property
    def is_permitted(self) -> bool:
        return self.state.is_permitted

    def describe(self) -> str:
        text = f"{self.name.value}: {self.state.value}"
        return f"{text} - {self.reason}" if self.reason else text


@dataclass(frozen=True)
class CapabilityMatrix:
    """The capability table for one host.

    Missing entries are reported as :attr:`CapabilityState.UNKNOWN` rather than
    defaulting to available or unavailable.
    """

    entries: Mapping[CapabilityName, Capability] = field(default_factory=dict)

    @classmethod
    def from_capabilities(cls, capabilities: Iterable[Capability]) -> CapabilityMatrix:
        return cls({capability.name: capability for capability in capabilities})

    @classmethod
    def unknown(cls, reason: str = "capabilities were not probed") -> CapabilityMatrix:
        return cls.from_capabilities(
            Capability(name, CapabilityState.UNKNOWN, reason) for name in CapabilityName
        )

    def get(self, name: CapabilityName) -> Capability:
        return self.entries.get(
            name, Capability(name, CapabilityState.UNKNOWN, "not reported by this adapter")
        )

    def state(self, name: CapabilityName) -> CapabilityState:
        return self.get(name).state

    def is_permitted(self, name: CapabilityName) -> bool:
        return self.get(name).is_permitted

    def reason(self, name: CapabilityName) -> str:
        return self.get(name).reason

    def with_capability(self, capability: Capability) -> CapabilityMatrix:
        merged = dict(self.entries)
        merged[capability.name] = capability
        return CapabilityMatrix(merged)

    def missing_permissions(self) -> tuple[str, ...]:
        """Distinct permissions that are currently blocking something."""
        seen: list[str] = []
        for capability in self:
            if (
                capability.state is CapabilityState.DENIED
                and capability.permission
                and capability.permission not in seen
            ):
                seen.append(capability.permission)
        return tuple(seen)

    def rows(self) -> tuple[tuple[str, str, str], ...]:
        """``(capability, state, reason)`` rows, in declaration order."""
        return tuple(
            (name.value, self.state(name).value, self.reason(name)) for name in CapabilityName
        )

    def __iter__(self) -> Iterator[Capability]:
        return (self.get(name) for name in CapabilityName)

    def __bool__(self) -> bool:
        return bool(self.entries)
