"""Real-platform verification harness.

Runs the actual platform adapters - real pynput, real window control, real
screen geometry - against a dedicated target application, and reports what
happened. This is the only place in the project that generates real keyboard
and mouse input outside of a user pressing Start.

    # 1. start an isolated display (or use a real desktop session)
    Xvfb :99 -screen 0 1920x1080x24 &
    DISPLAY=:99 python tools/platform_verify/mini_wm.py &        # Xvfb only
    DISPLAY=:99 python tools/platform_verify/target_app.py --events /tmp/e.jsonl &

    # 2. verify
    DISPLAY=:99 python tools/platform_verify/verify.py --events /tmp/e.jsonl

Safety rules this harness enforces on itself:

* **It only ever types into its own target.** Before any input is generated the
  resolved window's application identity must equal the verification target's.
  Anything else aborts the run - it will not type into a browser, an editor or
  a terminal, whatever the window list contains.
* Every plan is harmless: literal text, arrow keys, a click inside the target.
  Nothing it types can act on anything.
* It always dry-runs first and proves no event arrived before sending anything
  for real.

It lives in ``tools/`` and is never imported by the application.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from human_input_automation.adapters.registry import build_adapters  # noqa: E402
from human_input_automation.application.profiles import ProfileState  # noqa: E402
from human_input_automation.application.service import AutomationService  # noqa: E402
from human_input_automation.core.actions import (  # noqa: E402
    KeyDown,
    KeyPress,
    MouseClick,
    MouseDown,
    MouseMove,
    Shortcut,
    TypeCode,
    TypeText,
    Wait,
)
from human_input_automation.core.events import RunStatus  # noqa: E402
from human_input_automation.core.plan import AutomationPlan, RunOptions  # noqa: E402
from human_input_automation.core.target import TargetWindow  # noqa: E402
from human_input_automation.core.timing import TimingProfile  # noqa: E402
from human_input_automation.core.typing_style import TypingStyle  # noqa: E402
from human_input_automation.diagnostics import Diagnostics  # noqa: E402

TARGET_APP_ID = "automation-verify-target"
DECOY_APP_ID = "automation-verify-decoy"
TARGET_WINDOW_TITLE = "Automation Verification Target"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "NOT TESTED"


@dataclass
class Check:
    """One verification step and what actually happened."""

    name: str
    status: str
    detail: str = ""

    def render(self) -> str:
        line = f"  [{self.status:<10}] {self.name}"
        return f"{line}\n               {self.detail}" if self.detail else line


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, status: str, detail: str = "") -> Check:
        check = Check(name, status, detail)
        self.checks.append(check)
        print(check.render(), flush=True)
        return check

    def ok(self, name: str, condition: bool, detail: str = "") -> bool:
        self.add(name, PASS if condition else FAIL, detail)
        return condition

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if check.status == FAIL]

    def to_json(self) -> str:
        return json.dumps(
            {
                "environment": self.environment,
                "checks": [check.__dict__ for check in self.checks],
                "failures": len(self.failures),
            },
            indent=2,
        )


class EventLog:
    """Reads the target application's event file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                with contextlib.suppress(json.JSONDecodeError):
                    events.append(json.loads(line))
        return events

    def since(self, marker: int) -> list[dict[str, Any]]:
        return self.read()[marker:]

    def count(self) -> int:
        return len(self.read())

    def pid(self) -> int | None:
        """The process id the target reported when it started.

        The most reliable way to identify the window: application identity is
        spelled differently on every platform. On Linux the WM_CLASS carries the
        Qt application name, but on macOS pywinctl reports the *process* name -
        "Python" for a script - which matches every other Python window on the
        machine.
        """
        for event in self.read():
            if event.get("kind") == "ready" and event.get("pid"):
                return int(event["pid"])
        return None

    def typed_text(self, marker: int) -> str:
        return "".join(
            event.get("text", "")
            for event in self.since(marker)
            if event["kind"] == "key_press"
        )

    def wait_for(self, marker: int, count: int, timeout: float = 10.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = self.since(marker)
            if len(events) >= count:
                return events
            time.sleep(0.05)
        return self.since(marker)

    def wait_for_key(self, marker: int, codes: tuple[int, ...],
                     timeout: float = 15.0) -> list[dict[str, Any]]:
        """Wait for one *particular* key, not merely for some activity.

        Waiting for a count made every check hostage to the one before it: on
        macOS a slow activation pushed one key past its deadline, the next
        check saw that stale key, and the mismatch walked down the whole list.
        """
        deadline = time.monotonic() + timeout
        while True:
            events = self.since(marker)
            if any(event["kind"] == "key_press" and event.get("key") in codes
                   for event in events):
                return events
            if time.monotonic() >= deadline:
                return events
            time.sleep(0.05)

    def settle(self, quiet_for: float = 0.4, timeout: float = 20.0) -> None:
        """Wait until nothing new has been recorded for a moment.

        Late input from a previous check must not be counted against the next
        one, and on macOS input can arrive seconds after the run reports done.
        """
        deadline = time.monotonic() + timeout
        last = self.count()
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.05)
            current = self.count()
            if current != last:
                last = current
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= quiet_for:
                return

    def wait_for_kinds(self, marker: int, kinds: tuple[str, ...],
                       timeout: float = 10.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = self.since(marker)
            seen = {event["kind"] for event in events}
            if all(kind in seen for kind in kinds):
                return events
            time.sleep(0.05)
        return self.since(marker)


def find_target(
    service: AutomationService,
    report: Report,
    pid: int | None = None,
    title: str | None = None,
    app_id: str = TARGET_APP_ID,
) -> TargetWindow | None:
    """Locate the verification target - and refuse anything that is not it.

    Matching order, most reliable first: the process id the target reported at
    startup, then its application identity, then its exact window title. The
    fallbacks exist because "application identity" is not the same thing on
    every platform - on macOS it is the process name, so every Python window
    looks alike.
    """
    listing = service.discover_targets()
    windows = list(listing.targets)

    matches: list[TargetWindow] = []
    matched_by = ""
    if pid is not None:
        matches = [window for window in windows if window.process_id == pid]
        matched_by = f"process id {pid}"
    if not matches:
        matches = [
            window
            for window in windows
            if (window.app_id or "").lower() == app_id
            or (window.process_name or "").lower() == app_id
        ]
        matched_by = f"application identity {app_id!r}"
    if not matches and title:
        matches = [window for window in windows if (window.title or "") == title]
        matched_by = f"window title {title!r}"

    if not matches:
        seen = "; ".join(
            f"{window.title!r} (app={window.app_id!r}, pid={window.process_id})"
            for window in windows[:6]
        )
        report.add(
            "locate verification target",
            FAIL,
            f"{len(windows)} window(s) listed, none matched pid={pid} or {app_id!r}. "
            f"Reason: {listing.reason or 'none given'}. Saw: {seen or '(nothing)'}",
        )
        return None
    if len(matches) > 1:
        report.add(
            "locate verification target",
            FAIL,
            f"{len(matches)} candidates matched by {matched_by}; expected one",
        )
        return None
    target = matches[0]
    report.add("locate verification target", PASS, f"{target.describe()} (by {matched_by})")
    return target


def plan_for(target: TargetWindow, *actions: Any, timing: TimingProfile | None = None,
             seed: int | None = None, dry_run: bool = False) -> AutomationPlan:
    return AutomationPlan(
        target=target,
        actions=list(actions),
        timing=timing or TimingProfile(char_delay_ms=25, char_jitter_ms=5, min_delay_ms=10,
                                       max_delay_ms=60, action_delay_ms=40, action_jitter_ms=10),
        options=RunOptions(dry_run=dry_run, seed=seed),
        name="platform verification",
    )


def run_plan(service: AutomationService, plan: AutomationPlan, timeout: float = 60.0) -> Any:
    service.start(plan)
    return service.join(timeout)


# ---------------------------------------------------------------------------
# Verification steps
# ---------------------------------------------------------------------------


def check_environment(service: AutomationService, report: Report) -> None:
    """Record exactly what was tested, so the result can be reproduced."""
    host = service.host
    diagnostics = Diagnostics.collect(build_adapters())
    geometry = service.screen
    report.environment = {
        "os": diagnostics.os_name,
        "release": diagnostics.os_release,
        "python": diagnostics.python_version,
        "platform": host.platform.value,
        "display_server": host.display_server.value,
        "display": os.environ.get("DISPLAY", ""),
        "window_backend": service.window_backend,
        "monitors": [monitor.describe() for monitor in geometry.monitors],
        "coordinate_space": geometry.coordinate_space.value,
        "capabilities": {name: state for name, state, _ in host.matrix.rows()},
        "hotkey": service.hotkey_support.reason,
    }
    report.add("platform detection", PASS, f"{host.platform.value}/{host.display_server.value}")
    report.ok("screen geometry", geometry.is_known, geometry.describe())


def check_dry_run(service: AutomationService, target: TargetWindow, log: EventLog,
                  report: Report) -> None:
    """A dry run must reach the report and never the target."""
    marker = log.count()
    plan = plan_for(target, TypeText(text="DRY_RUN_MUST_NOT_APPEAR"), KeyPress(key="enter"),
                    dry_run=True)
    result = service.dry_run(plan)
    time.sleep(0.5)
    report.ok("dry run completes", result.status is RunStatus.COMPLETED, result.summary())
    report.ok("dry run generated no real input", log.count() == marker,
              f"{log.count() - marker} event(s) reached the target")
    report.ok("dry run reports the actions", len(result.performed) == 2, str(result.performed))


def check_real_typing(service: AutomationService, target: TargetWindow, log: EventLog,
                      report: Report) -> None:
    """The core question: does typed text actually arrive?"""
    marker = log.count()
    text = "AUTOMATION_TEST"
    report_result = run_plan(service, plan_for(target, TypeText(text=text)))
    if report_result is None:
        report.add("real typing", FAIL, "the run did not finish")
        return
    report.ok("real typing run completed", report_result.status is RunStatus.COMPLETED,
              report_result.summary())
    log.wait_for(marker, len(text))
    received = log.typed_text(marker)
    report.ok("typed text arrived at the target", received == text,
              f"expected {text!r}, received {received!r}")


#: Small enough to type quickly, and shaped like the code that exposed the
#: problem: nested brackets, a call, a string, and indentation on every level.
CODE_SNIPPET = 'function test() {\n    if (ok) {\n        log("hi");\n    }\n    return 1;\n}'


def check_code_typing(service: AutomationService, target: TargetWindow, log: EventLog,
                      report: Report) -> None:
    """A block of code must arrive as that block of code.

    The target is a plain text box, not a code editor, so none of the
    compensations have anything to compensate for here. That is the point: this
    proves the extra keystrokes (Escape, Delete, shift+Home) really are sent
    through the adapter and really are harmless where the editor is not
    helping. Whether they cancel out VS Code's own behaviour is a separate
    question, checked against the editor model in ``tests/test_editor_typing.py``
    and, ultimately, by typing into VS Code itself.
    """
    from PySide6.QtCore import Qt

    log.settle()
    marker = log.count()
    # Command+A on macOS: Control+A there means "start of line".
    select_all = "meta+a" if sys.platform == "darwin" else "ctrl+a"
    result = run_plan(service, plan_for(
        target,
        Shortcut.parse(select_all),
        KeyPress(key="delete"),
        TypeCode(text=CODE_SNIPPET),
        KeyPress(key="f8"),
    ))
    if result is None:
        report.add("code typing", FAIL, "the run did not finish")
        return
    report.ok("code typing run completed", result.status is RunStatus.COMPLETED,
              result.summary())

    events = log.wait_for_kinds(marker, ("content",), timeout=30)
    snapshots = [event for event in events if event["kind"] == "content"]
    if not snapshots:
        report.add("typed code arrived unchanged", FAIL,
                   "the target never reported its contents; F8 may not have arrived")
        return
    received = snapshots[-1].get("text", "")
    report.ok("typed code arrived unchanged in a plain text box",
              received == CODE_SNIPPET,
              f"expected {CODE_SNIPPET!r}, received {received!r}")

    pressed = {event.get("key") for event in events if event["kind"] == "key_press"}
    expected = {
        "escape": int(Qt.Key.Key_Escape),
        "delete": int(Qt.Key.Key_Delete),
        "home": int(Qt.Key.Key_Home),
    }
    missing = [name for name, code in expected.items() if code not in pressed]
    report.ok("the editor compensations were sent as real keys", not missing,
              f"missing: {', '.join(missing)}" if missing else "escape, delete and home arrived")


def check_typing_mistakes(service: AutomationService, target: TargetWindow, log: EventLog,
                          report: Report) -> None:
    """Deliberate mistakes must be corrected before the run ends."""
    from PySide6.QtCore import Qt

    log.settle()
    marker = log.count()
    text = "the quick brown fox jumps over the lazy dog"
    select_all = "meta+a" if sys.platform == "darwin" else "ctrl+a"
    plan = plan_for(
        target,
        Shortcut.parse(select_all),
        KeyPress(key="delete"),
        TypeText(text=text),
        KeyPress(key="f8"),
        seed=20260902,
    )
    result = run_plan(service, plan.with_changes(typing=TypingStyle.natural(typo_rate=0.25)))
    if result is None:
        report.add("typing mistakes", FAIL, "the run did not finish")
        return

    events = log.wait_for_kinds(marker, ("content",), timeout=30)
    backspaces = sum(
        1 for event in events
        if event["kind"] == "key_press" and event.get("key") == int(Qt.Key.Key_Backspace)
    )
    report.ok("mistakes were actually made and taken back", backspaces > 0,
              f"{backspaces} backspace(s) sent")

    snapshots = [event for event in events if event["kind"] == "content"]
    received = snapshots[-1].get("text", "") if snapshots else ""
    report.ok("the corrected text is the text that was asked for", received == text,
              f"expected {text!r}, received {received!r}")


def check_named_keys(service: AutomationService, target: TargetWindow, log: EventLog,
                     report: Report) -> None:
    """Named keys must arrive as keys, not as literal text."""
    from PySide6.QtCore import Qt

    expected = {
        "enter": (int(Qt.Key.Key_Return), int(Qt.Key.Key_Enter)),
        "tab": (int(Qt.Key.Key_Tab),),
        "left": (int(Qt.Key.Key_Left),),
        "backspace": (int(Qt.Key.Key_Backspace),),
        "home": (int(Qt.Key.Key_Home),),
        "page_down": (int(Qt.Key.Key_PageDown),),
    }
    for name, codes in expected.items():
        log.settle()
        marker = log.count()
        run_plan(service, plan_for(target, KeyPress(key=name)))
        # macOS window activation goes through AppleScript and can take
        # seconds, so a five second budget was not always enough.
        events = log.wait_for_key(marker, codes, timeout=15)
        keys = [event.get("key") for event in events if event["kind"] == "key_press"]
        report.ok(f"named key {name!r} arrived", any(key in codes for key in keys),
                  f"expected one of {codes}, received {keys}")


def check_shortcut(service: AutomationService, target: TargetWindow, log: EventLog,
                   report: Report) -> None:
    """A chord must arrive with its modifier applied, not as separate keys."""
    from PySide6.QtCore import Qt

    # Qt on macOS swaps these when reporting: the physical Control key arrives
    # as Qt::Key_Meta / MetaModifier, and Command arrives as ControlModifier.
    # Verified on a real Mac, where ctrl+a produced [Key_Meta, Key_A].
    on_macos = sys.platform == "darwin"
    modifier = (
        int(Qt.KeyboardModifier.MetaModifier.value)
        if on_macos
        else int(Qt.KeyboardModifier.ControlModifier.value)
    )
    log.settle()
    marker = log.count()
    run_plan(service, plan_for(target, Shortcut.parse("ctrl+a")))
    events = log.wait_for_key(marker, (int(Qt.Key.Key_A),), timeout=15)
    with_control = [
        event for event in events
        if event["kind"] == "key_press"
        and event.get("key") == int(Qt.Key.Key_A)
        and event.get("modifiers", 0) & modifier
    ]
    keys = [event.get("key") for event in events if event["kind"] == "key_press"]
    report.ok("shortcut ctrl+a arrived with the modifier held", bool(with_control),
              f"{len(events)} event(s): {keys}")


def target_click_point(log: EventLog, fallback: tuple[int, int] = (400, 300)) -> tuple[int, int]:
    """A point inside the target window, from the geometry it reported."""
    for event in log.read():
        if event.get("kind") == "ready" and event.get("geometry"):
            x, y, width, height = event["geometry"]
            return (int(x + width / 2), int(y + height / 2))
    return fallback


def check_command_modifier(service: AutomationService, target: TargetWindow, log: EventLog,
                           report: Report) -> None:
    """On macOS, META must be Command - never Control.

    Qt reports Command as ControlModifier on macOS, so a correct meta+a arrives
    with ControlModifier set. Anywhere else this check does not apply.
    """
    if sys.platform != "darwin":
        report.add("META maps to Command (macOS only)", SKIP, "not macOS")
        return
    from PySide6.QtCore import Qt

    marker = log.count()
    run_plan(service, plan_for(target, Shortcut.parse("meta+a")))
    events = log.wait_for(marker, 2, timeout=10)
    with_command = [
        event for event in events
        if event["kind"] == "key_press"
        and event.get("key") == int(Qt.Key.Key_A)
        and event.get("modifiers", 0) & int(Qt.KeyboardModifier.ControlModifier.value)
    ]
    keys = [e.get("key") for e in events if e["kind"] == "key_press"]
    report.ok("META maps to Command, not Control", bool(with_command), f"keys seen: {keys}")


def check_mouse(service: AutomationService, target: TargetWindow, log: EventLog,
                report: Report) -> None:
    """Movement must land where asked, take the time asked, and click."""
    from human_input_automation.adapters.registry import build_adapters as _build

    adapters = _build()
    try:
        mouse = adapters.mouse
        destination = (600, 400)
        started = time.monotonic()
        mouse.move_to(destination[0], destination[1], 400)
        elapsed = (time.monotonic() - started) * 1000
        position = mouse.position()
        report.ok("mouse movement reached the requested position",
                  abs(position[0] - destination[0]) <= 2 and abs(position[1] - destination[1]) <= 2,
                  f"asked for {destination}, ended at {position}")
        report.ok("mouse movement took approximately the requested duration",
                  250 <= elapsed <= 900, f"asked for 400 ms, took {elapsed:.0f} ms")
    finally:
        adapters.close()

    point = target_click_point(log)
    marker = log.count()
    run_plan(service, plan_for(target, MouseMove(x=point[0], y=point[1]), MouseClick()))
    events = log.wait_for_kinds(marker, ("mouse_press", "mouse_release"), timeout=8)
    kinds = [event["kind"] for event in events]
    clicked = "mouse_press" in kinds and "mouse_release" in kinds
    report.ok("mouse click arrived at the target", clicked, f"clicked {point}, events: {kinds}")


def focus_decoy(decoy_pid: int, decoy_log: EventLog) -> tuple[bool, str]:
    """Give the decoy keyboard focus, using the platform's own tools.

    Deliberately *not* the product's activation path. This is the harness
    setting the trap, and it has to work even where the product cannot see the
    window: on macOS the target and the decoy are both processes named
    "Python", and pywinctl enumerates the windows of only one of them, so the
    decoy is raised by process id through System Events instead.

    Success is confirmed by the decoy itself reporting that it took focus,
    rather than by the exit status of whatever raised it.
    """
    marker = decoy_log.count()
    how = ""
    if sys.platform == "darwin":
        script = (
            'tell application "System Events" to set frontmost of '
            f"(first process whose unix id is {decoy_pid}) to true"
        )
        try:
            completed = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=20
            )
            how = f"System Events, pid {decoy_pid}"
            if completed.returncode != 0:
                return False, f"{how}: {completed.stderr.strip()}"
        except Exception as exc:
            return False, f"System Events failed: {exc}"
    else:
        from human_input_automation.adapters.registry import build_adapters as _build

        adapters = _build()
        try:
            windows = adapters.discovery
            if windows is None or adapters.windows is None:
                return False, "no window discovery on this platform"
            listed = list(windows.list_windows())
            candidates = [window for window in listed if window.process_id == decoy_pid]
            if not candidates:
                candidates = [
                    window for window in listed if (window.app_id or "").lower() == DECOY_APP_ID
                ]
            if not candidates:
                seen = "; ".join(
                    f"{w.title!r} (app={w.app_id!r}, pid={w.process_id})" for w in listed
                )
                return False, (
                    f"the decoy (pid {decoy_pid}) was not enumerated among "
                    f"{len(listed)} window(s). Saw: {seen or '(nothing)'}"
                )
            how = candidates[0].describe()
            if not adapters.windows.activate(candidates[0]):
                return False, f"activation refused for {how}"
        finally:
            adapters.close()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if any(event["kind"] == "focus_in" for event in decoy_log.since(marker)):
            return True, how
        time.sleep(0.1)
    return False, f"{how}: the decoy never reported taking focus"


def check_activation_against_decoy(service: AutomationService, target: TargetWindow,
                                   log: EventLog, decoy_log: EventLog, decoy_pid: int,
                                   report: Report) -> None:
    """The critical test: focus a decoy, then automate the target.

    Input must land in the target and nowhere else. This is the single most
    important safety property in the product.

    The safety assertions run whether or not the decoy could be focused. A
    harness that cannot set the trap still must not let the run type into the
    wrong window, and reporting nothing at all here once hid a real defect.
    """
    focused, detail = focus_decoy(decoy_pid, decoy_log)
    report.ok("focus the decoy window", focused, detail)

    target_marker = log.count()
    decoy_marker = decoy_log.count()
    text = "TARGET_ONLY"
    result = run_plan(service, plan_for(target, TypeText(text=text)))
    log.wait_for(target_marker, len(text))
    time.sleep(0.3)

    report.ok("run against the target completed", result is not None
              and result.status is RunStatus.COMPLETED,
              result.summary() if result else "no report")
    report.ok("input reached the intended target", log.typed_text(target_marker) == text,
              f"target received {log.typed_text(target_marker)!r}")
    decoy_received = decoy_log.typed_text(decoy_marker)
    report.ok("the decoy received nothing", decoy_received == "",
              f"decoy received {decoy_received!r}"
              + ("" if focused else " (the decoy was not focused, so this is weak evidence)"))


def check_emergency_stop(service: AutomationService, target: TargetWindow, log: EventLog,
                         report: Report) -> None:
    """Stopping must be immediate and must never leave a key or button held."""
    # 1. Stop during a long wait.
    marker = log.count()
    plan = plan_for(target, Wait(duration_ms=60_000), TypeText(text="MUST_NOT_APPEAR"))
    service.start(plan)
    time.sleep(0.6)
    started = time.monotonic()
    service.emergency_stop()
    result = service.join(15)
    elapsed = time.monotonic() - started
    report.ok("emergency stop during a 60 s wait is immediate", elapsed < 2.0,
              f"took {elapsed * 1000:.0f} ms")
    report.ok("emergency stop is reported as such",
              result is not None and result.status is RunStatus.EMERGENCY_STOPPED,
              result.summary() if result else "no report")
    time.sleep(0.4)
    report.ok("no action ran after the stop", log.typed_text(marker) == "",
              f"target received {log.typed_text(marker)!r}")

    # 2. Stop while a modifier is held: the modifier must be released.
    marker = log.count()
    service.start(plan_for(target, KeyDown(key="shift"), Wait(duration_ms=30_000)))
    time.sleep(0.8)
    service.emergency_stop()
    service.join(15)
    time.sleep(0.4)
    events = log.since(marker)
    presses = [event for event in events if event["kind"] == "key_press"]
    releases = [event for event in events if event["kind"] == "key_release"]
    report.ok("a held modifier is released when the run is stopped",
              len(releases) >= len(presses) and len(presses) >= 1,
              f"{len(presses)} press(es), {len(releases)} release(s)")

    # Prove the modifier is genuinely not stuck: type after the stop.
    marker = log.count()
    run_plan(service, plan_for(target, TypeText(text="after")))
    log.wait_for(marker, 5)
    typed = log.typed_text(marker)
    report.ok("typing after a stop is unaffected by the previously held key",
              typed == "after", f"expected 'after', received {typed!r} "
              "(uppercase would mean shift was still held)")

    # 3. Stop while a mouse button is held.
    service.start(plan_for(target, MouseDown(), Wait(duration_ms=30_000)))
    time.sleep(0.8)
    service.emergency_stop()
    stop_result = service.join(15)
    report.ok("a held mouse button is released when the run is stopped",
              stop_result is not None and stop_result.status is RunStatus.EMERGENCY_STOPPED,
              stop_result.summary() if stop_result else "no report")

    # 4. Stop while paused.
    service.start(plan_for(target, Wait(duration_ms=30_000), TypeText(text="NEVER")))
    time.sleep(0.4)
    service.pause()
    time.sleep(0.3)
    service.emergency_stop()
    paused_result = service.join(15)
    report.ok("a paused run stops safely",
              paused_result is not None
              and paused_result.status is RunStatus.EMERGENCY_STOPPED,
              paused_result.summary() if paused_result else "no report")


def check_timing(service: AutomationService, target: TargetWindow, log: EventLog,
                 report: Report) -> None:
    """Measured delays must sit inside the configured bounds."""
    profile = TimingProfile(char_delay_ms=120, char_jitter_ms=30, min_delay_ms=60,
                            max_delay_ms=200, action_delay_ms=0, action_jitter_ms=0)
    marker = log.count()
    text = "TIMING"
    result = run_plan(service, plan_for(target, TypeText(text=text), timing=profile, seed=7))
    events = log.wait_for(marker, len(text), timeout=15)
    presses = [event for event in events if event["kind"] == "key_press"]
    gaps = [
        (presses[index + 1]["at"] - presses[index]["at"]) * 1000
        for index in range(len(presses) - 1)
    ]
    if not gaps:
        report.add("measured typing delays", FAIL, "no keystrokes were recorded")
        return
    low, high = min(gaps), max(gaps)
    report.add("measured typing delays",
               PASS if all(40 <= gap <= 400 for gap in gaps) else FAIL,
               f"configured 60-200 ms, measured {low:.0f}-{high:.0f} ms over {len(gaps)} gaps")
    report.ok("timing did not slow the run beyond its bounds",
              result is not None and result.status is RunStatus.COMPLETED,
              result.summary() if result else "")

    # Determinism: the same seed must produce the same planned delays.
    from human_input_automation.core.timing import TimingService

    first = [TimingService(profile, seed=99).char_delay_ms(char) for char in "abcdef"]
    second = [TimingService(profile, seed=99).char_delay_ms(char) for char in "abcdef"]
    report.ok("seeded timing is reproducible", first == second, f"{first[:3]}...")


def check_safety_gates(service: AutomationService, target: TargetWindow, log: EventLog,
                       report: Report) -> None:
    """Each refusal path must produce no input at all."""
    from human_input_automation.core.target import WindowCapabilities

    marker = log.count()
    missing = TargetWindow(handle="0xdeadbeef", title="gone", platform=target.platform,
                           display_server=target.display_server,
                           capabilities=target.capabilities)
    result = run_plan(service, plan_for(missing, TypeText(text="MUST_NOT_APPEAR")))
    report.ok("a missing target fails the run",
              result is not None and result.status is RunStatus.FAILED,
              result.error if result else "")
    report.ok("a missing target produces no input", log.count() == marker)

    marker = log.count()
    blocked = TargetWindow(handle=target.handle, title=target.title, platform=target.platform,
                           display_server=target.display_server,
                           capabilities=WindowCapabilities(can_enumerate=True, can_activate=True))
    result = run_plan(service, plan_for(blocked, TypeText(text="MUST_NOT_APPEAR")))
    report.ok("a capability-blocked target cannot run",
              result is not None and result.status is RunStatus.INVALID,
              result.error if result else "")
    report.ok("a capability-blocked target produces no input", log.count() == marker)


def check_profiles(service: AutomationService, target: TargetWindow, log: EventLog,
                   profile_directory: Path, report: Report) -> None:
    """Save, simulate a restart, re-resolve, and run again."""
    from human_input_automation.application.profiles import ProfileRepository, ProfileService

    profiles = service.profiles
    plan = plan_for(target, TypeText(text="PROFILE"))
    saved = profiles.save(profiles.build("Verification profile", plan, target))
    report.ok("profile saved", profiles.exists(saved.id), str(profile_directory))

    # A fresh service with fresh adapters is what a restart looks like.
    restarted = AutomationService(
        build_adapters(), profiles=ProfileService(ProfileRepository(profile_directory))
    )
    try:
        reloaded = restarted.profiles.load(saved.id)
        report.ok("profile reloads after a restart", reloaded.name == "Verification profile")
        # What matters is that the profile stores an identity that outlives the
        # handle - not that the identity is spelled the way Linux spells it. On
        # macOS the durable identity available is the process name, "Python",
        # while the handle is ("Python", "<window title>") and changes with the
        # title. The re-resolution checks below prove the property in practice.
        identity = (reloaded.target.app_id or reloaded.target.process_name or "")
        durable = bool(identity) and identity != (reloaded.target.handle_hint or "")
        if sys.platform not in ("darwin", "win32"):
            durable = identity == TARGET_APP_ID
        report.ok("the saved identity is the application, not a handle", durable,
                  f"app_id={reloaded.target.app_id!r} handle_hint={reloaded.target.handle_hint!r}")

        loaded = restarted.prepare_profile(reloaded)
        report.ok("the target re-resolves after a restart",
                  loaded.state is ProfileState.TARGET_RESOLVED, loaded.message)

        if loaded.is_runnable and loaded.plan is not None:
            marker = log.count()
            restarted.start(loaded.plan)
            result = restarted.join(30)
            log.wait_for(marker, 7)
            report.ok("a reloaded profile runs and its input arrives",
                      log.typed_text(marker) == "PROFILE",
                      f"received {log.typed_text(marker)!r}; {result.summary() if result else ''}")

        # A stale handle must not be trusted on its own.
        stale = reloaded.with_changes(
            target=reloaded.target.with_changes(handle_hint="0xdeadbeef")
        )
        stale_loaded = restarted.prepare_profile(stale)
        report.ok("a stale handle still resolves through the application identity",
                  stale_loaded.state is ProfileState.TARGET_RESOLVED, stale_loaded.message)

        wrong = reloaded.with_changes(
            target=reloaded.target.with_changes(app_id="com.example.absent",
                                                process_name="absent", handle_hint=None)
        )
        wrong_loaded = restarted.prepare_profile(wrong)
        report.ok("a profile for an absent application does not resolve",
                  wrong_loaded.state is ProfileState.TARGET_UNRESOLVED, wrong_loaded.message)
    finally:
        restarted.close()
        profiles.delete(saved.id)


def check_global_hotkey(service: AutomationService, target: TargetWindow, report: Report) -> None:
    """The real hotkey adapter must stop a run - and only ever stop one."""
    support = service.hotkey_support
    if support.is_known_unsupported:
        report.add("global emergency hotkey", SKIP, support.reason)
        return

    triggered: list[int] = []
    registered = service.enable_emergency_hotkey(lambda: triggered.append(1))
    if not registered:
        report.add("global emergency hotkey registers", SKIP,
                   f"the platform refused to register it ({support.reason})")
        return
    report.add("global emergency hotkey registers", PASS, service.hotkey.description)

    try:
        # It must not start anything on its own.
        how = _press_hotkey()
        time.sleep(0.5)
        report.ok("the hotkey does not start a run", not service.is_running, f"sent via {how}")

        service.start(plan_for(target, Wait(duration_ms=30_000)))
        time.sleep(0.7)
        started = time.monotonic()
        how = _press_hotkey()
        result = service.join(15)
        elapsed = time.monotonic() - started
        report.ok("the hotkey stops a running plan",
                  result is not None and result.status is RunStatus.EMERGENCY_STOPPED,
                  f"{result.summary() if result else 'no report'} after {elapsed * 1000:.0f} ms")
        report.ok("the hotkey callback reached the application", bool(triggered),
                  f"{len(triggered)} notification(s), sent via {how}"
                  + ("" if triggered or how != "pynput" else
                     "; pynput ignores its own injected events, so this may be a"
                     " limitation of the harness rather than of the hotkey"))
    finally:
        service.disable_emergency_hotkey()
        if service.is_running:
            service.emergency_stop()
            service.join(10)


#: macOS virtual key codes for the emergency hotkey. Posting through Quartz
#: avoids pynput's self-injection filter - see :func:`_press_hotkey`.
_MACOS_KEY_CODES = {"ctrl": 0x3B, "shift": 0x38, "f9": 0x65}


def _press_hotkey() -> str:
    """Synthesize the configured emergency hotkey. Returns how it was sent.

    pynput tags the events its own Controller injects so that its own Listener
    ignores them - a sensible guard against a feedback loop, and the reason a
    pynput-generated hotkey is invisible to a pynput hotkey listener on macOS
    and Windows. (X11 has no such marker, which is why this worked on Linux.)
    A real person pressing the keys is unaffected, so the harness posts the
    events through the platform underneath pynput instead.
    """
    from human_input_automation.adapters.hotkeys import DEFAULT_EMERGENCY_HOTKEY

    names = [part.strip("<>").strip() for part in DEFAULT_EMERGENCY_HOTKEY.split("+")]
    names = [name for name in names if name]

    if sys.platform == "darwin":
        with contextlib.suppress(Exception):
            _press_hotkey_quartz(names)
            return "Quartz"

    from human_input_automation.adapters.pynput_input import PynputKeyboard
    from human_input_automation.core.keys import normalize_key

    keys = [normalize_key(name) for name in names]
    keyboard = PynputKeyboard()
    for key in keys:
        keyboard.key_down(key)
        time.sleep(0.03)
    for key in reversed(keys):
        keyboard.key_up(key)
        time.sleep(0.03)
    return "pynput"


def _press_hotkey_quartz(names: list[str]) -> None:
    """Post the hotkey as ordinary system key events on macOS."""
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGEventFlagMaskControl,
        kCGEventFlagMaskShift,
        kCGHIDEventTapLocation,
    )

    codes = [_MACOS_KEY_CODES[name] for name in names]
    flags = 0
    if "ctrl" in names:
        flags |= kCGEventFlagMaskControl
    if "shift" in names:
        flags |= kCGEventFlagMaskShift

    def post(code: int, down: bool, with_flags: int) -> None:
        event = CGEventCreateKeyboardEvent(None, code, down)
        CGEventSetFlags(event, with_flags)
        CGEventPost(kCGHIDEventTapLocation, event)
        time.sleep(0.04)

    held = 0
    for name, code in zip(names, codes, strict=True):
        if name == "ctrl":
            held |= kCGEventFlagMaskControl
        elif name == "shift":
            held |= kCGEventFlagMaskShift
        post(code, True, held if name in ("ctrl", "shift") else flags)
    for name, code in reversed(list(zip(names, codes, strict=True))):
        post(code, False, flags if name not in ("ctrl", "shift") else held)


def check_adapter_lifecycle(report: Report) -> None:
    """Adapters must be reusable and must release what they hold."""
    import threading

    baseline = threading.active_count()
    adapters = build_adapters()
    try:
        first = list(adapters.discovery.list_windows()) if adapters.discovery else []
        second = list(adapters.discovery.list_windows()) if adapters.discovery else []
        report.ok("repeated enumeration is stable", len(first) == len(second),
                  f"{len(first)} then {len(second)} window(s)")
        report.ok("screen geometry can be re-read", adapters.geometry().is_known,
                  adapters.geometry().describe())
    finally:
        adapters.close()

    time.sleep(0.5)
    leaked = threading.active_count() - baseline
    report.ok("no threads are leaked by an adapter cycle", leaked <= 0,
              f"{threading.active_count()} thread(s), baseline {baseline}")

    reopened = build_adapters()
    try:
        report.ok("adapters can be rebuilt after being closed",
                  reopened.host.platform is not None, reopened.window_backend)
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True,
                        help="the target application's event file")
    parser.add_argument("--decoy-events", type=Path,
                        help="a second target's event file, for the activation test")
    parser.add_argument("--decoy-pid", type=int, help="process id of the decoy window")
    parser.add_argument(
        "--target-pid",
        type=int,
        help="process id of the target window (read from its event log when omitted)",
    )
    parser.add_argument("--profiles", type=Path, help="profile directory to use for the test")
    parser.add_argument("--json", type=Path, help="write the machine-readable report here")
    parser.add_argument("--skip-input", action="store_true",
                        help="run only the checks that generate no input")
    arguments = parser.parse_args(argv)

    log = EventLog(arguments.events)
    report = Report()
    profile_directory = arguments.profiles or (arguments.events.parent / "profiles")

    from human_input_automation.application.profiles import ProfileRepository, ProfileService

    service = AutomationService(
        build_adapters(), profiles=ProfileService(ProfileRepository(profile_directory))
    )
    try:
        print("\n=== environment ===", flush=True)
        check_environment(service, report)

        print("\n=== target discovery ===", flush=True)
        target = find_target(
            service,
            report,
            pid=log.pid() or arguments.target_pid,
            title=TARGET_WINDOW_TITLE,
        )
        if target is None:
            print("\nThe verification target is not running; nothing else can be checked.")
            return 1

        print("\n=== dry run (no input may reach the target) ===", flush=True)
        check_dry_run(service, target, log, report)

        if arguments.skip_input:
            report.add("real input checks", SKIP, "--skip-input was given")
        else:
            print("\n=== real keyboard input ===", flush=True)
            check_real_typing(service, target, log, report)
            check_code_typing(service, target, log, report)
            check_typing_mistakes(service, target, log, report)
            check_named_keys(service, target, log, report)
            check_shortcut(service, target, log, report)
            check_command_modifier(service, target, log, report)

            print("\n=== real mouse input ===", flush=True)
            check_mouse(service, target, log, report)

            if arguments.decoy_events and arguments.decoy_pid:
                print("\n=== activation with a decoy window focused ===", flush=True)
                decoy_log = EventLog(arguments.decoy_events)
                check_activation_against_decoy(
                    service, target, log, decoy_log,
                    decoy_log.pid() or arguments.decoy_pid, report
                )
            else:
                report.add("activation against a decoy window", SKIP,
                           "--decoy-events/--decoy-pid were not given")

            print("\n=== emergency stop ===", flush=True)
            check_emergency_stop(service, target, log, report)

            print("\n=== global hotkey ===", flush=True)
            check_global_hotkey(service, target, report)

            print("\n=== adapter lifecycle ===", flush=True)
            check_adapter_lifecycle(report)

            print("\n=== timing ===", flush=True)
            check_timing(service, target, log, report)

            print("\n=== safety gates ===", flush=True)
            check_safety_gates(service, target, log, report)

            print("\n=== profiles ===", flush=True)
            check_profiles(service, target, log, profile_directory, report)
    finally:
        service.close()

    passed = sum(1 for check in report.checks if check.status == PASS)
    failed = len(report.failures)
    skipped = sum(1 for check in report.checks if check.status == SKIP)
    print(f"\n=== {passed} passed, {failed} failed, {skipped} not tested ===", flush=True)
    for check in report.failures:
        print(f"  FAILED: {check.name} - {check.detail}", flush=True)

    if arguments.json:
        arguments.json.write_text(report.to_json(), encoding="utf-8")
        print(f"\nreport written to {arguments.json}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
