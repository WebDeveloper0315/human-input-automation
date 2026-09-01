# Architecture

## Dependency rule

Dependencies point inwards only:

```
ui  ->  application  ->  core  <-  adapters
                          ^           |
                          +-- ports --+
```

* `core/` — domain: actions, plans, timing, validation, control, engine.
  Imports nothing but the standard library and `ports/`.
* `ports/` — `Protocol` definitions the core depends on (input, windows, clock,
  capabilities). No platform code, no third-party imports.
* `adapters/` — implementations of the ports: pynput input, pywinctl windows,
  system clock, null adapters, platform/capability detection.
* `application/` — orchestration: threaded runner, countdown, service facade.
  Qt-free.
* `ui/` — PySide6 widgets plus a Qt-free presentation layer (`ui/models.py`).
  Talks only to `application`.
* `app.py` — the composition root; the only module that wires all layers.

**No platform API may be imported from `core/`.** The engine never sees a
`HWND`, an `AXUIElement`, an X11 window id or a pynput object; it sees ports.

The package that holds adapters is called `adapters`, not `platform`: a module
named `platform` inside the package shadows the standard-library module of the
same name and confuses packaging and analysis tools.

## Module map

| Module | Responsibility |
| --- | --- |
| `core/actions.py` | Action dataclasses (the discriminated union) |
| `core/keys.py` | Platform-neutral key names, aliases, shortcut parsing |
| `core/plan.py` | `AutomationPlan`, `ExecutionLimits`, `RunOptions` |
| `core/target.py` | `TargetWindow`, `WindowCapabilities`, `PlatformReport` |
| `core/timing.py` | `TimingProfile`, `TimingService` |
| `core/validation.py` | Plan/action/target validation, errors vs warnings |
| `core/control.py` | `RunControl`: start/pause/resume/stop/emergency stop |
| `core/engine.py` | `AutomationEngine`, `ExecutionContext`, `ActionRegistry` |
| `core/handlers.py` | One handler function per built-in action |
| `core/events.py` | Run events and `RunReport` |
| `core/dryrun.py` | Recording no-op ports used by dry-run mode |
| `ports/*` | `KeyboardPort`, `MousePort`, `WindowDiscoveryPort`, `WindowControlPort`, `Clock`, `CancelToken`, `CapabilityProbe`, `HotkeyPort`, `ScreenPort` |
| `core/capabilities.py` | `CapabilityMatrix`: per-capability state, reason, permission |
| `core/screen.py` | `MonitorInfo`, `ScreenGeometry`, coordinate space |
| `adapters/platform_info.py` | Platform/display-server/permission detection, capability matrices |
| `adapters/keymap.py` | **The only** place platform key names live |
| `adapters/x11_windows.py` | X11/EWMH window discovery and activation (Linux) |
| `adapters/screens.py` | Monitor layout via pymonctl |
| `diagnostics.py` | `--diagnose`: read-only capability report |
| `adapters/pynput_input.py` | Real keyboard and mouse (lazy import) |
| `adapters/pywinctl_windows.py` | Real window discovery/activation (lazy import) |
| `adapters/registry.py` | Chooses adapters, degrades to null adapters |
| `adapters/pynput_hotkey.py` | Global emergency-stop hotkey (lazy import) |
| `adapters/hotkeys.py` | Hotkey capability reporting and the null hotkey |
| `application/runner.py` | Worker thread, pre-run countdown, event fan-out |
| `application/service.py` | Facade used by the UI |
| `ui/models.py` | **Qt-free** presentation logic: run-state machine, control enablement, capability banner, action/timing forms, log and error formatting |
| `ui/run_bridge.py` | The single worker-thread → Qt-thread boundary |
| `ui/main_window.py` | Window assembly and service wiring |
| `ui/target_panel.py` | Window list, selection, active-target indicator |
| `ui/action_editor.py` | Action list plus the generated per-action dialog |
| `ui/timing_panel.py` | Timing profile fields, seed and live preview |
| `ui/run_controls.py` | Start/Pause/Resume/Stop, countdown and emergency stop |
| `ui/capability_banner.py` | Persistent capability/permission banner |
| `ui/dry_run_panel.py` | Dry-run preview |
| `ui/run_log.py` | Structured run-event log |

## Action model

Actions are frozen dataclasses forming a union, not one struct with optional
fields, so invalid states cannot be constructed:

`TypeText`, `KeyPress`, `KeyDown`, `KeyUp`, `Shortcut`, `MouseMove`,
`MouseClick`, `MouseDown`, `MouseUp`, `Wait`.

Every action carries an optional `delay_after_ms` override. Structural rules are
enforced in `__post_init__` (`TypeText` needs text, `MouseClick` needs both
coordinates or neither, counts are >= 1, durations are >= 0); policy rules
(limits, capabilities) live in `core/validation.py`.

Dispatch goes through `ActionRegistry`, a `type[Action] -> handler` mapping.
**Adding an action never requires touching the engine**:

```python
@dataclass(frozen=True)
class Scroll(Action):
    kind = "scroll"
    amount: int

def handle_scroll(action: Scroll, ctx: ExecutionContext) -> None:
    ctx.mouse.scroll(action.amount)          # a new port method

engine.registry.register(Scroll, handle_scroll)
```

## Timing

`TimingProfile` is data; `TimingService` turns it into delays from a single
seeded `random.Random`, so `RunOptions(seed=...)` makes an entire run
reproducible.

Per typed character:

```
clamp(char_delay +- char_jitter, min_delay, max_delay)
  + word pause         (after whitespace)
  + punctuation pause  (after punctuation_chars)
```

Bounds apply to the base delay; the pauses are additive extras, so a tight
`max_delay_ms` cannot silently erase a configured sentence pause. Separately
configurable: `action_delay_ms`/`action_jitter_ms` between actions, and
`mouse_move_duration_ms`/`mouse_move_jitter_ms` for pointer movement. A
per-action `delay_after_ms` is used verbatim.

This produces *natural, configurable pacing* for automation, testing and
accessibility. It is not a model of a person, and the project does not claim or
attempt to make input undetectable, or to defeat anti-bot, CAPTCHA or other
security controls.

## Target-window handling

`TargetWindow` carries the stable platform `handle`, `title`, `process_name`,
`process_id`, `app_id`, `platform`, `display_server` and a `WindowCapabilities`
record. The handle - not the title - identifies the window, because titles
change while an application runs.

Before any input is sent, the engine activates the target and checks focus:

* activation returns `False` -> the run fails, nothing is typed;
* `is_active()` returns `False` -> the run fails ("did not take focus");
* `is_active()` returns `None` (unknown) -> the run proceeds, unless
  `RunOptions(require_focus_verification=True)`.

`TargetWindow.focused_window()` is an explicit opt-in fallback for platforms
that cannot enumerate or activate windows; validation warns whenever it is used.

### Platform capabilities are not uniform

Capabilities are a matrix, not a set of booleans. Each entry carries a state, a
reason, and where relevant the permission that would unblock it:

| State | Meaning |
| --- | --- |
| `available` | Works. |
| `restricted` | Works in a reduced form; the reason says how. |
| `denied` | Supported, but a permission is missing. Fixable by the user. |
| `unavailable` | The platform or backend does not provide it. |
| `unknown` | Could not be determined. **Never displayed as "no".** |

`available`, `restricted` and `unknown` permit an attempt (an attempt that
fails aborts the run safely); `denied` and `unavailable` block it. The boolean
`WindowCapabilities` the engine gates on are *derived* from the matrix, so the
engine keeps a simple gate while the UI and `--diagnose` show the full picture.

| | Windows | macOS | Linux/X11 | Linux/Wayland (+XWayland) |
| --- | --- | --- | --- | --- |
| Enumerate windows | available | Accessibility | available | unavailable (restricted: X11 clients only) |
| Activate window | available | Accessibility | available | unavailable |
| Verify focus | available | Accessibility | available | unavailable |
| Synthetic input | available | Accessibility | available | unavailable (restricted: X11 clients only) |
| Global hotkey | available | **Input Monitoring** | available | unavailable |
| Multi-monitor | available | restricted (logical points) | restricted (no scale reported) | restricted |

macOS needs **two different permissions**: Accessibility for input and window
control, Input Monitoring for observing global keys (the emergency-stop
hotkey). Holding one does not imply the other, so they are modelled and
reported separately, each with the settings pane that grants it and whether a
restart is needed.

Which window backend is used is decided from capabilities, not the OS name
(`registry.select_window_backend`): Linux gets the EWMH adapter, Windows and
macOS get pywinctl, and a session that cannot enumerate gets none at all with a
reason attached. Linux/X11 and Linux/Wayland are treated as different
platforms, because they are.

### Keyboard translation

All platform key knowledge lives in `adapters/keymap.py` — nothing else may
contain a platform key name. It also records which keys a platform's backend
genuinely lacks (`Key.INSERT` does not exist on macOS), which the host report
carries and validation rejects **before** a run starts rather than raising
mid-plan.

### Coordinates

`core/screen.py` models the monitor layout and states the coordinate space
(`physical` on Windows/X11, `logical` on macOS, `unknown` otherwise) instead of
assuming one. Per-monitor scale is `None` when the backend cannot report it.
Validation rejects absolute coordinates that land on no monitor - including the
gap between two non-adjacent monitors - while negative coordinates (monitors
left of or above the primary) are valid. Unknown geometry disables the check
rather than blocking a run.

## Safety

* **Validation first** — an invalid plan returns an `INVALID` report; no input.
* **Limits** — `ExecutionLimits` caps action count, per-action text length,
  total characters and run duration; the count and duration caps are re-checked
  during the run.
* **Dry run** — the engine swaps in recording ports *and* a virtual clock, so
  nothing can reach the desktop whatever the adapters are, the preview returns
  immediately, and the report lists every action plus the estimated duration.
* **Emergency stop** — `RunControl.emergency_stop()` sets a `threading.Event`.
  Every delay is `Event.wait(timeout)`, so a pending 60-second wait ends
  immediately instead of running out.
* **Cleanup** — held keys and mouse buttons are always released in the engine's
  `finally`, so a stop never leaves a modifier stuck down.
* **Failure isolation** — a broken event listener or an adapter exception is
  caught, reported as `FAILED`, and never crashes the caller. Platform adapters
  additionally convert backend failures into empty results or `False`, so a
  library defect cannot surface as a traceback.
* **Mid-run focus re-verification** — before each action, a target that the
  platform can verify is re-checked. If it stopped being focused (closed, or the
  user switched away) the run fails instead of letting the remaining actions
  land in another application. Platforms that cannot verify focus skip the
  check; unknown is never treated as failure.
* **Bounded stop latency** — every wait is an interruptible `Event.wait`.
  The two exceptions are documented, not hidden: a mouse movement can delay a
  stop by one ~8 ms interpolation step, and a zero-delay `TypeText` is handed
  to the backend as one uninterruptible call. See
  `docs/PHASE3-PLATFORM-REPORT.md` §6.

## Threading and the Qt boundary

`AutomationEngine.run()` blocks, by design: it is a pure, testable loop.
`application/runner.py` runs it on a daemon worker thread, which keeps the UI
thread free to render and - critically - to receive the emergency stop.

The **one rule** for the UI is that widgets are touched only on the Qt main
thread. `ui/run_bridge.py` is the only place the boundary is crossed:

```
worker thread                     Qt main thread
-------------                     --------------
engine emits RunEvent
   -> RunEventBridge.__call__
        -> Signal.emit  ── queued ──>  slot _on_run_event
                                          -> run log, controls, state
```

`RunEventBridge` is created on the main thread, so `emit` from the worker uses a
queued connection and every slot runs on the main thread. The pynput hotkey
listener crosses the same bridge (`notify_hotkey`). Nothing else in `ui/` may be
called from another thread, and `tests/test_ui_threading.py` asserts it by
recording the thread identity of every slot invocation during a real run.

The bridge's signal is called `run_event`, not `event`: `QObject.event` is Qt's
own event handler and must not be shadowed.

## UI architecture

Widgets are thin. Everything that can be decided without Qt lives in
`ui/models.py`, which imports no GUI toolkit at all:

* `UiState` + `next_state(state, event)` — the run-state machine, folded from
  run events;
* `controls_for(state, has_target, has_actions)` — which controls are enabled
  and whether editing is locked;
* `capability_banner(...)` — capability level, headline and details;
* `ACTION_SPECS` — declarative field lists per action type, plus
  `build_action` / `action_to_values` for conversion to and from domain actions;
* `TIMING_FIELDS`, `build_timing_profile`, `preview_delays` — timing form and
  preview;
* `format_event`, `friendly_error`, `dry_run_view` — log lines, user-facing
  error text and the dry-run panel content.

That split is why most of the UI is testable without a display, and why adding
an action type gives it an editor for free: define the dataclass, register a
handler, add an `ActionSpec`.

### Run lifecycle

```
IDLE ──start──> STARTING ──> COUNTDOWN ──> RUNNING ──> COMPLETED ─┐
                    │            │           │  ↑                 │
                    │            │        PAUSE│  │RESUME         ├─> idle-like
                    │            │           PAUSED                │   (start
                    └──stop──────┴──stop──────┴──> STOPPED ────────┤    enabled
                                             failure ─> FAILED ────┘    again)
```

The terminal states (`COMPLETED`, `STOPPED`, `FAILED`) enable the same controls
as `IDLE` while keeping the outcome visible in the status line. While a run is
active the target list, action editor and timing fields are locked, so the plan
cannot change under a running engine.

### Pre-run countdown

The countdown is part of the worker thread, not a Qt timer: `AutomationRunner`
waits on the run's `RunControl` (`wait_for_stop`) and emits `CountdownStarted` /
`CountdownTick` / `CountdownCancelled`. Consequences that matter:

* the Qt thread never sleeps;
* stop and emergency stop interrupt the countdown immediately, through the same
  cancellation path as the rest of a run;
* **the target is activated only after the countdown ends** - cancelling means
  no window was touched and no input was sent.

### Emergency stop

* Always visible, never disabled in any state, with an accessible name and the
  `Ctrl+.` shortcut.
* Clicking it signals the worker and updates the UI *immediately*; the window
  never blocks waiting for the thread, and reconciles when the final
  `RunReport` arrives.
* Works during the countdown, during a wait, while paused and mid-action, and
  releases any held keys and mouse buttons through the engine's cleanup.
* A global hotkey (`Ctrl+Alt+.`) is offered through `ports/hotkeys.py` and the
  pynput adapter. Where a platform cannot support it - Wayland, or macOS
  without Input Monitoring permission - the UI says so instead of pretending;
  the on-screen button is the guaranteed control. The hotkey can only ever
  stop a run, never start one.

### Dry run

The dry-run button builds the *same* plan and timing profile as a real run and
hands it to `AutomationService.dry_run`, which swaps in recording ports and a
virtual clock. Nothing can reach the desktop, the call returns immediately, and
the panel shows the target, the ordered actions, sampled delays, the estimated
duration and the outcome under a "DRY RUN - NO INPUT WILL BE SENT" header. The
execution algorithm is not duplicated anywhere in the UI.

### Capability display

The banner distinguishes five levels - `AVAILABLE`, `RESTRICTED`, `DENIED`,
`UNKNOWN`, `UNAVAILABLE` - and renders each with a word (`OK`, `LIMITED`,
`DENIED`, `UNKNOWN`, `UNAVAILABLE`) as well as a symbol, so status is never
carried by colour alone. `UNKNOWN` is a distinct level on purpose and is never
displayed as "no". The target panel shows the *reason* it cannot list windows
(Wayland restrictions, a missing macOS permission, an unavailable adapter)
rather than an empty list.

## Testing strategy

Everything above the adapters is tested with fakes (`tests/fakes.py`):
`FakeKeyboard`, `FakeMouse`, `FakeWindows`, `FakeHotkey`, and a `FakeClock`
whose virtual time advances instantly. A hook on the fake clock triggers stop
requests at an exact point in a run, so cancellation is tested deterministically
without sleeping.

The UI is tested at two levels:

* `ui/models.py` is pure Python, so its tests need no Qt at all;
* widget and main-window tests run on Qt's `offscreen` platform plugin
  (`QT_QPA_PLATFORM=offscreen`, set in `tests/conftest.py`), driving the real
  service, runner and engine against fake adapters.

Without the `gui` extra installed the three Qt modules skip themselves, so the
suite still runs on a machine that has no Qt at all. CI therefore needs no
desktop on any platform. The pynput and pywinctl adapters are thin, lazily
imported, and left to manual/Phase 3 verification on real hardware.

## Dependency decisions

| Dependency | Verdict | Reasoning |
| --- | --- | --- |
| PySide6 | keep, `[gui]` extra | Mature Qt binding, LGPL, all three platforms, good threading story. Only the `ui` layer may import it. |
| pynput | keep, `[input]` extra | The practical cross-platform synthetic-input library. Weaknesses (no key-name mapping, no movement interpolation, Wayland limits) are absorbed by the adapter. |
| pywinctl | keep for Windows/macOS, `[windows]` extra | Wraps Win32 and the macOS Accessibility APIs. **Not used on Linux**: its Linux path raises `KeyError: 'id'` on Ubuntu 26.04 GNOME (reproduced), so Linux uses the EWMH adapter instead. |
| python-xlib | added, `[x11]` extra (Linux only) | Already a pywinctl dependency. Drives the EWMH window adapter that replaces pywinctl on Linux. |
| pymonctl | used via pywinctl, no new requirement | Monitor layout for coordinate validation. |
| PyYAML | moved to `[yaml]` extra, unused for now | Profiles are not implemented yet, and `json` from the standard library covers them. YAML stays available if human-editable profiles are wanted later. |

The core itself has **no runtime dependencies**: `pip install -e ".[dev]"`
installs pytest, ruff and mypy only, which is why CI is fast and headless.

Considered and rejected for now: `pyautogui` (bundles more than needed, weaker
window model), per-platform native bindings such as `pywin32` / `pyobjc` /
`python-xlib` used directly (Phase 3 may add them *behind the existing ports*
where pynput or pywinctl fall short - the architecture already allows that
without touching the core).
