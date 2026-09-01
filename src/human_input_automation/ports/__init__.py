"""Ports: the interfaces the core depends on.

Nothing in this package imports a platform library. Each ``Protocol`` here is
implemented once per platform under ``adapters/``, and the composition root
(``app.py``) decides which implementation the engine receives.
"""

from .capabilities import CapabilityProbe
from .clock import CancelToken, Clock
from .input import KeyboardPort, MousePort
from .window import WindowControlPort, WindowDiscoveryPort

__all__ = [
    "CancelToken",
    "CapabilityProbe",
    "Clock",
    "KeyboardPort",
    "MousePort",
    "WindowControlPort",
    "WindowDiscoveryPort",
]
