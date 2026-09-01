"""Target-window abstraction.

Selecting *which* window receives input is the most platform-sensitive part of
this application, so the model is explicit about what is known and what a given
platform can actually do. The three desktop platforms are not equivalent:

* **Windows** exposes native window handles (``HWND``); enumeration, activation
  and focus verification are all available without special permissions.
* **macOS** requires the user to grant Accessibility (and, for some flows,
  Screen Recording) permission to the *host application*. Without it, synthetic
  input and window control silently do nothing.
* **Linux** depends on the display server. X11 allows enumeration, activation
  and global synthetic input. Wayland deliberately does not: compositors
  restrict window control and global input injection, and behaviour differs per
  compositor. This is a platform policy, not a bug to work around.

The core therefore never assumes a capability; it reads
:class:`WindowCapabilities` and refuses to run when a required one is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from .capabilities import Capability, CapabilityMatrix, CapabilityName, CapabilityState
from .keys import Key

#: Sentinel handle for "whatever window currently has focus".
FOCUSED_WINDOW_HANDLE = "<focused>"


class PlatformName(StrEnum):
    """Operating system family a target belongs to."""

    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"


class DisplayServer(StrEnum):
    """Windowing system in use, which decides what is actually possible."""

    WINDOWS = "windows"
    QUARTZ = "quartz"
    X11 = "x11"
    WAYLAND = "wayland"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class WindowCapabilities:
    """What the platform adapter can do with a particular window.

    Unknown is represented honestly: ``can_verify_focus=False`` means "cannot
    confirm", not "not focused".
    """

    can_enumerate: bool = False
    can_activate: bool = False
    can_verify_focus: bool = False
    can_send_synthetic_input: bool = False
    requires_permission: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def unknown(cls) -> WindowCapabilities:
        """Capabilities for a target whose platform support was not probed."""
        return cls(notes=("capabilities were not probed",))

    @classmethod
    def from_matrix(cls, matrix: CapabilityMatrix) -> WindowCapabilities:
        """Collapse a capability matrix into the booleans the engine gates on.

        ``UNKNOWN`` counts as permitted - the engine attempts the operation and
        aborts if it fails - except for focus verification, which is only
        claimed when it is certain.
        """
        denied = [
            capability
            for capability in matrix
            if capability.state is CapabilityState.DENIED and capability.permission
        ]
        notes = tuple(
            capability.reason
            for capability in matrix
            if capability.reason and capability.state is not CapabilityState.AVAILABLE
        )
        return cls(
            can_enumerate=matrix.is_permitted(CapabilityName.WINDOW_ENUMERATION),
            can_activate=matrix.is_permitted(CapabilityName.WINDOW_ACTIVATION),
            can_verify_focus=(
                matrix.state(CapabilityName.FOCUS_VERIFICATION) is CapabilityState.AVAILABLE
            ),
            can_send_synthetic_input=matrix.is_permitted(CapabilityName.KEYBOARD_INPUT),
            requires_permission=denied[0].permission if denied else None,
            notes=tuple(dict.fromkeys(notes)),
        )

    @classmethod
    def full(cls) -> WindowCapabilities:
        """Every capability available (used by tests and fully supported hosts)."""
        return cls(
            can_enumerate=True,
            can_activate=True,
            can_verify_focus=True,
            can_send_synthetic_input=True,
        )

    def with_notes(self, *notes: str) -> WindowCapabilities:
        return replace(self, notes=self.notes + notes)


@dataclass(frozen=True)
class TargetWindow:
    """A window the user selected as the destination for automation.

    ``handle`` is the stable platform identifier (stringified ``HWND`` on
    Windows, X11 window id, or the adapter's own opaque id). Titles change while
    an application runs, so the handle - not the title - identifies the window.
    """

    handle: str
    title: str = ""
    platform: PlatformName = PlatformName.UNKNOWN
    display_server: DisplayServer = DisplayServer.UNKNOWN
    process_name: str | None = None
    process_id: int | None = None
    app_id: str | None = None
    capabilities: WindowCapabilities = field(default_factory=WindowCapabilities.unknown)

    @property
    def is_focused_window(self) -> bool:
        """True for the "current focus" pseudo-target, which is never activated."""
        return self.handle == FOCUSED_WINDOW_HANDLE

    @classmethod
    def focused_window(
        cls,
        *,
        platform: PlatformName = PlatformName.UNKNOWN,
        display_server: DisplayServer = DisplayServer.UNKNOWN,
        capabilities: WindowCapabilities | None = None,
    ) -> TargetWindow:
        """Opt-in fallback target: send to whatever window has focus at run time.

        Explicit selection is the supported path; this exists for platforms
        (notably Wayland) where enumeration and activation are unavailable.
        """
        return cls(
            handle=FOCUSED_WINDOW_HANDLE,
            title="<currently focused window>",
            platform=platform,
            display_server=display_server,
            capabilities=capabilities
            or WindowCapabilities(can_send_synthetic_input=True).with_notes(
                "input goes to whatever window is focused when the run starts"
            ),
        )

    def describe(self) -> str:
        """Single-line description for the UI's active-target indicator."""
        parts = [self.title or "(untitled)"]
        if self.process_name:
            parts.append(self.process_name)
        if self.process_id is not None:
            parts.append(f"pid {self.process_id}")
        parts.append(f"{self.platform.value}/{self.display_server.value}")
        return " - ".join(parts)


@dataclass(frozen=True)
class PlatformReport:
    """Result of probing the host for automation support.

    Surfaced in the UI so the user learns *why* something is unavailable
    (missing macOS permission, Wayland restrictions) instead of seeing input
    silently do nothing.
    """

    platform: PlatformName
    display_server: DisplayServer
    capabilities: WindowCapabilities
    missing_permissions: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    #: Per-capability detail. The boolean ``capabilities`` above are derived
    #: from this; the matrix is what the UI and ``--diagnose`` display.
    matrix: CapabilityMatrix = field(default_factory=CapabilityMatrix)
    #: Named keys this platform's input backend cannot send at all. Filled in by
    #: the adapter layer; validation rejects plans that use them *before* a run
    #: starts, rather than failing halfway through.
    unsupported_keys: tuple[Key, ...] = field(default_factory=tuple)

    @property
    def can_automate(self) -> bool:
        return self.capabilities.can_send_synthetic_input

    def capability(self, name: CapabilityName) -> Capability:
        return self.matrix.get(name)

    def state_of(self, name: CapabilityName) -> CapabilityState:
        return self.matrix.state(name)
