"""Adapters: concrete implementations of the ports.

Naming note: this package is deliberately *not* called ``platform``. A module
named ``platform`` inside the package shadows the standard library module of
the same name for anything that imports it relatively, and confuses packaging
tools; ``adapters`` also matches the ports-and-adapters layering used here.

Desktop adapters (pynput, pywinctl) are imported lazily by
:func:`registry.build_adapters` so that importing this package never requires a
graphical session.
"""

from .null import NullCapabilityProbe, NullKeyboard, NullMouse, NullWindowBackend
from .platform_info import (
    HostCapabilityProbe,
    describe_host,
    detect_display_server,
    detect_platform,
)
from .registry import AdapterSet, build_adapters
from .system_clock import SystemClock

__all__ = [
    "AdapterSet",
    "HostCapabilityProbe",
    "NullCapabilityProbe",
    "NullKeyboard",
    "NullMouse",
    "NullWindowBackend",
    "SystemClock",
    "build_adapters",
    "describe_host",
    "detect_display_server",
    "detect_platform",
]
