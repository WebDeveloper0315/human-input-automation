"""Composition root.

This is the only module that knows about every layer at once: it builds the
adapters for the host, wires them into the service, and hands the service to
the UI.
"""

from __future__ import annotations

import argparse
import sys

from .adapters.registry import build_adapters
from .application.service import AutomationService


def _format_host(service: AutomationService) -> str:
    from .ui.main_window import build_status_text

    return build_status_text(service)


def run_check() -> int:
    """Print what this host supports. Works headless, useful for diagnostics."""
    service = AutomationService(build_adapters())
    print(_format_host(service))
    return 0 if service.host.can_automate else 1


def run_gui() -> int:
    service = AutomationService(build_adapters())
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            'PySide6 is not installed. Install the GUI extra: pip install ".[gui]"',
            file=sys.stderr,
        )
        return 2

    from .ui.main_window import create_main_window

    app = QApplication(sys.argv)
    window = create_main_window(service)
    window.show()
    exit_code = app.exec()
    return int(exit_code)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="human-input-automation")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report platform capabilities and permissions, then exit",
    )
    args = parser.parse_args(argv)
    return run_check() if args.check else run_gui()
