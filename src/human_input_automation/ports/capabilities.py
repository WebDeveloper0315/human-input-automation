"""Capability and permission detection port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.target import PlatformReport


@runtime_checkable
class CapabilityProbe(Protocol):
    """Reports what automation this host actually supports.

    Implementations must be honest about uncertainty: report a missing
    permission or an unsupported display server instead of assuming success and
    letting input silently disappear.
    """

    def probe(self) -> PlatformReport:
        """Inspect the host and describe its automation capabilities."""
        ...
