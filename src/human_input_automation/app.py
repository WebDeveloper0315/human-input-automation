"""Composition root.

The only module that knows about every layer at once: it builds the adapters
for the host, wires them into the service, and hands the service to the UI.

``--check`` deliberately imports nothing from Qt, so capability diagnostics work
on a headless machine.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .adapters.registry import build_adapters
from .application.service import AutomationService
from .ui.models import CapabilityLevel, capability_banner, host_status_text


def build_service() -> AutomationService:
    return AutomationService(build_adapters())


#: Capability levels that still allow a run to be attempted.
_USABLE_LEVELS = frozenset(
    {CapabilityLevel.AVAILABLE, CapabilityLevel.RESTRICTED, CapabilityLevel.UNKNOWN}
)


def run_check() -> int:
    """Print what this host supports. Works headless, useful for diagnostics.

    Exit code 0 means automation can be attempted (possibly with restrictions);
    1 means it is unavailable or a permission is missing.
    """
    service = build_service()
    print(host_status_text(service.host, service.problems, service.hotkey_support))
    banner = capability_banner(service.host, service.problems, service.hotkey_support)
    return 0 if banner.level in _USABLE_LEVELS else 1


def run_gui() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            'PySide6 is not installed. Install the GUI extra: pip install ".[gui]"',
            file=sys.stderr,
        )
        return 2

    from .ui.main_window import MainWindow

    service = build_service()
    app = QApplication(sys.argv)
    app.setApplicationName("Human Input Automation")
    window = MainWindow(service)
    window.show()
    return int(app.exec())


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="human-input-automation")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report platform capabilities and permissions, then exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log diagnostic detail to stderr",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    return run_check() if args.check else run_gui()
