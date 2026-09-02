"""Read-only platform diagnostics.

Everything here inspects; nothing here sends input. That is a hard guarantee of
the ``--diagnose`` command: it constructs no input controller, presses no key
and moves no pointer. It is Qt-free so it works on a headless machine.
"""

from __future__ import annotations

import platform as platform_module
import sys
from dataclasses import dataclass

from .adapters.hotkeys import HotkeySupport
from .adapters.registry import AdapterSet
from .core.capabilities import CapabilityName, CapabilityState
from .core.screen import ScreenGeometry
from .core.target import PlatformReport

#: Text markers, so a terminal without colour still conveys the state.
_MARKS = {
    CapabilityState.AVAILABLE: "available",
    CapabilityState.RESTRICTED: "restricted",
    CapabilityState.DENIED: "denied",
    CapabilityState.UNAVAILABLE: "unavailable",
    CapabilityState.UNKNOWN: "unknown",
}


@dataclass(frozen=True)
class Diagnostics:
    """Everything ``--diagnose`` reports."""

    host: PlatformReport
    screen: ScreenGeometry
    hotkey: HotkeySupport
    window_backend: str
    problems: tuple[str, ...]
    os_name: str
    os_release: str
    python_version: str
    unsupported_keys: tuple[str, ...] = ()

    @classmethod
    def collect(cls, adapters: AdapterSet) -> Diagnostics:
        """Gather diagnostics. Performs no input and opens no window."""
        return cls(
            host=adapters.host,
            screen=adapters.geometry(),
            hotkey=adapters.hotkey_support,
            window_backend=adapters.window_backend,
            problems=adapters.problems,
            os_name=platform_module.system() or sys.platform,
            os_release=platform_module.release(),
            python_version=platform_module.python_version(),
            unsupported_keys=tuple(key.value for key in adapters.host.unsupported_keys),
        )

    def render(self) -> str:
        """Human-readable report."""
        host = self.host
        lines = [
            "Human Input Automation Diagnostics",
            "",
            f"OS: {self.os_name}",
            f"Kernel/release: {self.os_release}",
            f"Python: {self.python_version}",
            f"Platform: {host.platform.value}",
            f"Display server: {host.display_server.value}",
            f"Window backend: {self.window_backend}",
            "",
            "Capabilities:",
        ]
        width = max(len(name.value) for name in CapabilityName)
        for capability in host.matrix:
            state = _MARKS[capability.state]
            lines.append(f"  {capability.name.value:<{width}}  {state}")
        lines.append("")
        lines.append(f"Global emergency hotkey: {_hotkey_state(self.hotkey)}")
        lines.append(f"Reason: {self.hotkey.reason}")

        reasons = _distinct_reasons(host)
        if reasons:
            lines.append("")
            lines.append("Reasons:")
            lines.extend(f"  - {reason}" for reason in reasons)

        if host.missing_permissions:
            lines.append("")
            lines.append("Missing permissions:")
            for permission in host.missing_permissions:
                blocked = next(
                    (item for item in host.matrix if item.permission == permission), None
                )
                where = blocked.permission_category if blocked else None
                restart = (
                    " (restart the application after granting)"
                    if blocked is not None and blocked.requires_restart
                    else ""
                )
                lines.append(f"  - {permission}{restart}")
                if where:
                    lines.append(f"    Grant it in: {where}")

        if self.unsupported_keys:
            lines.append("")
            lines.append("Keys unavailable on this platform: " + ", ".join(self.unsupported_keys))

        lines.append("")
        lines.append("Displays:")
        if self.screen.is_known:
            lines.append(f"  {self.screen.describe()}")
            for monitor in self.screen.monitors:
                lines.append(f"  - {monitor.describe()}")
        else:
            lines.append(f"  {self.screen.describe()}")

        if self.problems:
            lines.append("")
            lines.append("Adapter problems:")
            lines.extend(f"  - {problem}" for problem in self.problems)

        lines.append("")
        lines.append("No input was generated.")
        return "\n".join(lines)

    @property
    def exit_code(self) -> int:
        """0 when automation can be attempted, 1 when it cannot."""
        return 0 if self.host.matrix.is_permitted(CapabilityName.KEYBOARD_INPUT) else 1


def _hotkey_state(support: HotkeySupport) -> str:
    if support.available is True:
        return "available"
    if support.available is False:
        return "unavailable"
    return "unknown"


def _distinct_reasons(host: PlatformReport) -> tuple[str, ...]:
    """One line per permission, not one per capability it happens to gate.

    Three near-identical Automation notes differing only in the clause at the
    end is noise; the permission is the thing the user has to act on.
    """
    seen: list[str] = []
    seen_permissions: set[str] = set()
    for capability in host.matrix:
        if capability.state is CapabilityState.AVAILABLE:
            continue
        if capability.permission:
            if capability.permission in seen_permissions:
                continue
            seen_permissions.add(capability.permission)
        if capability.reason and capability.reason not in seen:
            seen.append(capability.reason)
    return tuple(seen)
