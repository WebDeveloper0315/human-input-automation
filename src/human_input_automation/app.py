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

from .adapters.registry import AdapterSet, build_adapters
from .application.profiles import ProfileError, ProfileService
from .application.service import AutomationService
from .diagnostics import Diagnostics
from .ui.models import CapabilityLevel, capability_banner, host_status_text


def build_service(adapters: AdapterSet | None = None) -> AutomationService:
    return AutomationService(adapters or build_adapters())


def run_diagnose() -> int:
    """Print a full read-only capability report. Sends no input whatsoever."""
    adapters = build_adapters()
    try:
        diagnostics = Diagnostics.collect(adapters)
        print(diagnostics.render())
        return diagnostics.exit_code
    finally:
        adapters.close()


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
    try:
        print(host_status_text(service.host, service.problems, service.hotkey_support))
        banner = capability_banner(service.host, service.problems, service.hotkey_support)
        return 0 if banner.level in _USABLE_LEVELS else 1
    finally:
        service.close()


def run_profiles() -> int:
    """List stored profiles. Reads files only; sends no input."""
    service = ProfileService()
    summaries = service.list()
    print(f"Profile directory: {service.directory}")
    if not summaries:
        print("No profiles stored yet.")
        return 0
    for summary in summaries:
        if summary.is_readable:
            updated = f"  (updated {summary.updated_at})" if summary.updated_at else ""
            print(f"  {summary.id}  {summary.name}{updated}")
        else:
            print(f"  {summary.id}  UNREADABLE: {summary.error}")
    return 0


def run_validate_profile(path: str) -> int:
    """Validate a profile file structurally. Never executes it."""
    try:
        profile = ProfileService().validate_file(path)
    except ProfileError as error:
        print(f"Invalid profile: {error}", file=sys.stderr)
        return 1
    plan = profile.plan
    actions = len(plan.actions) if plan is not None else 0
    print(f"Profile is structurally valid: {profile.name} ({actions} action(s))")
    print(f"Target identity: {profile.target.describe()}")
    print("No input was generated, and nothing was executed.")
    return 0


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
        "--diagnose",
        action="store_true",
        help="print a detailed read-only platform diagnostic report, then exit "
        "(never sends keyboard or mouse input)",
    )
    parser.add_argument(
        "--profiles",
        action="store_true",
        help="list stored automation profiles, then exit (sends no input)",
    )
    parser.add_argument(
        "--validate-profile",
        metavar="PATH",
        help="validate a profile file and exit; never executes it",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log diagnostic detail to stderr",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    if args.diagnose:
        return run_diagnose()
    if args.profiles:
        return run_profiles()
    if args.validate_profile:
        return run_validate_profile(args.validate_profile)
    return run_check() if args.check else run_gui()
