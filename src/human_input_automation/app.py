"""Composition root and command-line entry point.

The only module that knows about every layer at once: it initialises the
per-user directories, configures logging, builds the adapters for the host,
wires them into the service, and hands the service to the UI.

The headless commands (``--check``, ``--diagnose``, ``--profiles``,
``--validate-profile``) import nothing from Qt, so diagnostics work on a machine
with no desktop session - and none of them sends input.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .adapters.registry import AdapterSet, build_adapters
from .application.profiles import ProfileError, ProfileRepository, ProfileService
from .application.service import AutomationService
from .diagnostics import Diagnostics
from .logging_setup import configure_logging
from .metadata import METADATA
from .paths import ApplicationPaths, is_frozen
from .startup import (
    MISSING_GUI,
    NO_DISPLAY,
    StartupProblem,
    data_directory_problem,
    has_display,
    qt_plugin_problem,
)
from .ui.models import CapabilityLevel, capability_banner, host_status_text

logger = logging.getLogger(__name__)

#: Capability levels that still allow a run to be attempted.
_USABLE_LEVELS = frozenset(
    {CapabilityLevel.AVAILABLE, CapabilityLevel.RESTRICTED, CapabilityLevel.UNKNOWN}
)


def initialise(verbose: bool = False, *, log_to_file: bool = True) -> ApplicationPaths:
    """Create the per-user directories and start logging.

    Runs on every launch; on the first one it also creates the directories.
    Raises :class:`OSError` if the data directory cannot be created - the caller
    turns that into an actionable message rather than a traceback.
    """
    paths = ApplicationPaths.for_host()
    created = paths.ensure()
    configure_logging(verbose=verbose, log_directory=paths.logs, to_file=log_to_file)
    if created:
        logger.info("created application directories: %s", ", ".join(str(p) for p in created))
    logger.debug(
        "%s %s starting (frozen=%s, python=%s)",
        METADATA.name,
        METADATA.version,
        is_frozen(),
        sys.version.split()[0],
    )
    return paths


def build_service(
    adapters: AdapterSet | None = None, paths: ApplicationPaths | None = None
) -> AutomationService:
    """Assemble the application service for this host."""
    resolved = paths or ApplicationPaths.for_host()
    return AutomationService(
        adapters or build_adapters(),
        profiles=ProfileService(ProfileRepository(resolved.profiles)),
    )


def _fail(problem: StartupProblem) -> int:
    print(problem.render(), file=sys.stderr)
    return problem.exit_code


# -- headless commands ----------------------------------------------------
def run_check(paths: ApplicationPaths | None = None) -> int:
    """Print what this host supports. Works headless, sends no input."""
    service = build_service(paths=paths)
    try:
        print(host_status_text(service.host, service.problems, service.hotkey_support))
        banner = capability_banner(service.host, service.problems, service.hotkey_support)
        return 0 if banner.level in _USABLE_LEVELS else 1
    finally:
        service.close()


def run_diagnose(paths: ApplicationPaths | None = None) -> int:
    """Print a full read-only capability report. Sends no input whatsoever."""
    resolved = paths or ApplicationPaths.for_host()
    adapters = build_adapters()
    try:
        diagnostics = Diagnostics.collect(adapters)
        print(diagnostics.render())
        print()
        print(f"{METADATA.name} {METADATA.version} (packaged: {'yes' if is_frozen() else 'no'})")
        print(f"Profiles: {resolved.profiles}")
        print(f"Logs:     {resolved.logs}")
        return diagnostics.exit_code
    finally:
        adapters.close()


def run_profiles(paths: ApplicationPaths | None = None) -> int:
    """List stored profiles. Reads files only; sends no input."""
    resolved = paths or ApplicationPaths.for_host()
    service = ProfileService(ProfileRepository(resolved.profiles))
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


def run_validate_profile(path: str, paths: ApplicationPaths | None = None) -> int:
    """Validate a profile file structurally. Never executes it."""
    resolved = paths or ApplicationPaths.for_host()
    try:
        profile = ProfileService(ProfileRepository(resolved.profiles)).validate_file(path)
    except ProfileError as error:
        print(f"Invalid profile: {error}", file=sys.stderr)
        return 1
    plan = profile.plan
    actions = len(plan.actions) if plan is not None else 0
    print(f"Profile is structurally valid: {profile.name} ({actions} action(s))")
    print(f"Target identity: {profile.target.describe()}")
    print("No input was generated, and nothing was executed.")
    return 0


def run_smoke_test(paths: ApplicationPaths | None = None) -> int:
    """Verify a packaged build actually works. Sends no input.

    Used by the release pipeline to check an artifact rather than merely
    checking that a file exists: it builds the real service, opens the real
    window, saves and reloads a profile, and exits. It never enumerates input
    devices and never starts a run.
    """
    resolved = paths or ApplicationPaths.for_host()
    checks: list[str] = []

    if not has_display(dict(os.environ)):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        checks.append("no display: using the offscreen Qt platform")

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return _fail(MISSING_GUI)

    from .ui.main_window import MainWindow
    from .ui.resources import application_icon, icon_path

    service = build_service(paths=resolved)
    try:
        app = QApplication.instance() or QApplication([])
        checks.append(f"Qt platform: {QApplication.platformName()}")

        window = MainWindow(service, show_dialogs=False, paths=resolved)
        window.show()
        app.processEvents()  # let the window actually realise before checking it
        checks.append(f"window: {window.windowTitle()!r}")
        found = "found" if application_icon() is not None else "MISSING"
        checks.append(f"icon: {found} ({icon_path()})")
        checks.append(f"host: {service.host.platform.value}/{service.host.display_server.value}")

        from .core.actions import TypeText
        from .core.plan import AutomationPlan
        from .core.target import TargetWindow

        plan = AutomationPlan(TargetWindow(handle="smoke"), [TypeText(text="smoke test")])
        profile = service.profiles.save(
            service.profiles.build("Packaging smoke test", plan, None)
        )
        reloaded = service.profiles.load(profile.id)
        service.profiles.delete(profile.id)
        checks.append(f"profile round-trip: {reloaded.name!r}")

        window.close()
    finally:
        service.close()

    print(f"{METADATA.name} {METADATA.version} smoke test")
    for line in checks:
        print(f"  {line}")
    failed = [line for line in checks if "MISSING" in line]
    print("  no input was generated")
    return 1 if failed else 0


def run_version() -> int:
    print(f"{METADATA.name} {METADATA.version}")
    return 0


# -- graphical entry point ------------------------------------------------
def run_gui(paths: ApplicationPaths | None = None) -> int:
    """Launch the desktop UI, reporting start-up failures in plain language."""
    if not has_display(dict(os.environ)):
        return _fail(NO_DISPLAY)
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return _fail(MISSING_GUI)

    from .ui.main_window import MainWindow
    from .ui.resources import application_icon

    resolved = paths or ApplicationPaths.for_host()
    try:
        app = QApplication(sys.argv)
    except Exception as error:  # a Qt platform plugin that will not load
        logger.exception("Qt failed to start")
        return _fail(qt_plugin_problem(error))

    app.setApplicationName(METADATA.name)
    app.setApplicationDisplayName(METADATA.name)
    app.setApplicationVersion(METADATA.version)
    app.setOrganizationName(METADATA.publisher)
    app.setDesktopFileName(METADATA.identifier)
    icon = application_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    service = build_service(paths=resolved)
    window = MainWindow(service, paths=resolved)
    window.show()
    # Launched from a terminal, the window can open behind the terminal itself -
    # most visibly on macOS, where an unbundled process does not come forward on
    # its own. Ask for the front once, at start-up only.
    window.raise_()
    window.activateWindow()
    return int(app.exec())


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=METADATA.slug, description=METADATA.description
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
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
        "--smoke-test",
        action="store_true",
        help="verify this build starts, opens its window and stores a profile, "
        "then exit (sends no input; used to check release artifacts)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log diagnostic detail to stderr and the log file",
    )
    args = parser.parse_args(argv)

    if args.version:
        return run_version()

    try:
        paths = initialise(args.verbose)
    except OSError as error:
        fallback = ApplicationPaths.for_host()
        return _fail(data_directory_problem(fallback.data, error))

    if args.smoke_test:
        return run_smoke_test(paths)
    if args.diagnose:
        return run_diagnose(paths)
    if args.profiles:
        return run_profiles(paths)
    if args.validate_profile:
        return run_validate_profile(args.validate_profile, paths)
    if args.check:
        return run_check(paths)
    return run_gui(paths)
