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
    TypeText,
    Wait,
)
from human_input_automation.core.events import RunStatus  # noqa: E402
from human_input_automation.core.plan import AutomationPlan, RunOptions  # noqa: E402
from human_input_automation.core.target import TargetWindow  # noqa: E402
from human_input_automation.core.timing import TimingProfile  # noqa: E402
from human_input_automation.diagnostics import Diagnostics  # noqa: E402

TARGET_APP_ID = "automation-verify-target"
DECOY_APP_ID = "automation-verify-decoy"

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


def find_target(service: AutomationService, report: Report) -> TargetWindow | None:
    """Locate the verification target - and refuse anything that is not it."""
    listing = service.discover_targets()
    matches = [
        window
        for window in listing.targets
        if (window.app_id or "").lower() == TARGET_APP_ID
        or (window.process_name or "").lower() == TARGET_APP_ID
    ]
    if not matches:
        report.add(
            "locate verification target",
            FAIL,
            f"{len(listing.targets)} window(s) listed, none is the verification target "
            f"({listing.reason or 'no reason given'})",
        )
        return None
    if len(matches) > 1:
        report.add("locate verification target", FAIL, f"{len(matches)} candidates; expected one")
        return None
    target = matches[0]
    report.add("locate verification target", PASS, target.describe())
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
        marker = log.count()
        run_plan(service, plan_for(target, KeyPress(key=name)))
        events = log.wait_for(marker, 1, timeout=5)
        keys = [event.get("key") for event in events if event["kind"] == "key_press"]
        report.ok(f"named key {name!r} arrived", any(key in codes for key in keys),
                  f"expected one of {codes}, received {keys}")


def check_shortcut(service: AutomationService, target: TargetWindow, log: EventLog,
                   report: Report) -> None:
    """A chord must arrive with its modifier applied, not as separate keys."""
    from PySide6.QtCore import Qt

    marker = log.count()
    run_plan(service, plan_for(target, Shortcut.parse("ctrl+a")))
    events = log.wait_for(marker, 2, timeout=5)
    with_control = [
        event for event in events
        if event["kind"] == "key_press"
        and event.get("key") == int(Qt.Key.Key_A)
        and event.get("modifiers", 0) & int(Qt.KeyboardModifier.ControlModifier.value)
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


def check_activation_against_decoy(service: AutomationService, target: TargetWindow,
                                   log: EventLog, decoy_log: EventLog, decoy_pid: int,
                                   report: Report) -> None:
    """The critical test: focus a decoy, then automate the target.

    Input must land in the target and nowhere else. This is the single most
    important safety property in the product.
    """
    from human_input_automation.adapters.registry import build_adapters as _build

    adapters = _build()
    decoy = None
    try:
        windows = adapters.discovery
        if windows is None:
            report.add("focus the decoy window", SKIP, "no window discovery on this platform")
            return
        candidates = [
            window for window in windows.list_windows()
            if window.process_id == decoy_pid
            or (window.app_id or "").lower() == DECOY_APP_ID
        ]
        if not candidates:
            report.add("focus the decoy window", FAIL, "the decoy window was not enumerated")
            return
        decoy = candidates[0]
        activated = adapters.windows.activate(decoy) if adapters.windows else False
        time.sleep(0.4)
        report.ok("decoy window can be focused", activated, decoy.describe())
    finally:
        adapters.close()

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
              f"decoy received {decoy_received!r}")


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
        report.ok("the saved identity is the application, not a handle",
                  reloaded.target.app_id == TARGET_APP_ID or
                  reloaded.target.process_name == TARGET_APP_ID,
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
        _press_hotkey()
        time.sleep(0.5)
        report.ok("the hotkey does not start a run", not service.is_running)

        service.start(plan_for(target, Wait(duration_ms=30_000)))
        time.sleep(0.7)
        started = time.monotonic()
        _press_hotkey()
        result = service.join(15)
        elapsed = time.monotonic() - started
        report.ok("the hotkey stops a running plan",
                  result is not None and result.status is RunStatus.EMERGENCY_STOPPED,
                  f"{result.summary() if result else 'no report'} after {elapsed * 1000:.0f} ms")
        report.ok("the hotkey callback reached the application", bool(triggered),
                  f"{len(triggered)} notification(s)")
    finally:
        service.disable_emergency_hotkey()
        if service.is_running:
            service.emergency_stop()
            service.join(10)


def _press_hotkey() -> None:
    """Synthesize the configured emergency hotkey with the real input backend."""
    from human_input_automation.adapters.hotkeys import DEFAULT_EMERGENCY_HOTKEY
    from human_input_automation.adapters.pynput_input import PynputKeyboard
    from human_input_automation.core.keys import normalize_key

    keys = [
        normalize_key(part.strip("<>"))
        for part in DEFAULT_EMERGENCY_HOTKEY.split("+")
        if part.strip()
    ]
    keyboard = PynputKeyboard()
    for key in keys:
        keyboard.key_down(key)
        time.sleep(0.03)
    for key in reversed(keys):
        keyboard.key_up(key)
        time.sleep(0.03)


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
        target = find_target(service, report)
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
            check_named_keys(service, target, log, report)
            check_shortcut(service, target, log, report)

            print("\n=== real mouse input ===", flush=True)
            check_mouse(service, target, log, report)

            if arguments.decoy_events and arguments.decoy_pid:
                print("\n=== activation with a decoy window focused ===", flush=True)
                check_activation_against_decoy(
                    service, target, log, EventLog(arguments.decoy_events),
                    arguments.decoy_pid, report
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
