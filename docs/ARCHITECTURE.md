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
* `application/` — orchestration: threaded runner, service facade. Qt-free.
* `ui/` — PySide6. Talks only to `application`.
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
| `ports/*` | `KeyboardPort`, `MousePort`, `WindowDiscoveryPort`, `WindowControlPort`, `Clock`, `CancelToken`, `CapabilityProbe` |
| `adapters/platform_info.py` | Platform/display-server/permission detection |
| `adapters/pynput_input.py` | Real keyboard and mouse (lazy import) |
| `adapters/pywinctl_windows.py` | Real window discovery/activation (lazy import) |
| `adapters/registry.py` | Chooses adapters, degrades to null adapters |
| `application/runner.py` | Worker thread, event fan-out |
| `application/service.py` | Facade used by the UI |

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

| | Windows | macOS | Linux/X11 | Linux/Wayland |
| --- | --- | --- | --- | --- |
| Enumerate windows | yes | yes (with permission) | yes | no |
| Activate window | yes | yes (with permission) | yes | no |
| Verify focus | yes | yes (with permission) | yes | no |
| Synthetic input | yes | Accessibility permission required | yes | restricted; XWayland clients at best |

`adapters/platform_info.describe_host()` reports this as a `PlatformReport`,
including missing permissions and warnings, and the UI surfaces it. Wayland's
restrictions are a deliberate security design, not a defect to work around.

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
  caught, reported as `FAILED`, and never crashes the caller.

## Threading

`AutomationEngine.run()` blocks, by design: it is a pure, testable loop.
`application/runner.py` runs it on a daemon worker thread, which keeps the UI
thread free to render and - critically - to receive the emergency stop.

Listener callbacks fire **on the worker thread**. A Qt front end must marshal
them (emit a signal); it must never touch widgets from the listener.

## Testing strategy

Everything above the adapters is tested with fakes (`tests/fakes.py`):
`FakeKeyboard`, `FakeMouse`, `FakeWindows`, and a `FakeClock` whose virtual time
advances instantly. A hook on the fake clock triggers stop requests at an exact
point in a run, so cancellation is tested deterministically without sleeping.

CI therefore needs no desktop on any platform. The pynput and pywinctl adapters
are thin, lazily imported, and left to manual/Phase 3 verification on real
hardware.

## Dependency decisions

| Dependency | Verdict | Reasoning |
| --- | --- | --- |
| PySide6 | keep, `[gui]` extra | Mature Qt binding, LGPL, all three platforms, good threading story. Only the `ui` layer may import it. |
| pynput | keep, `[input]` extra | The practical cross-platform synthetic-input library. Weaknesses (no key-name mapping, no movement interpolation, Wayland limits) are absorbed by the adapter. |
| pywinctl | keep, `[windows]` extra | The only maintained cross-platform window enumeration/activation layer; it wraps Win32, the macOS Accessibility APIs and X11 (EWMH). Replacing it would mean three separate native integrations. |
| PyYAML | moved to `[yaml]` extra, unused for now | Profiles are not implemented yet, and `json` from the standard library covers them. YAML stays available if human-editable profiles are wanted later. |

The core itself has **no runtime dependencies**: `pip install -e ".[dev]"`
installs pytest, ruff and mypy only, which is why CI is fast and headless.

Considered and rejected for now: `pyautogui` (bundles more than needed, weaker
window model), per-platform native bindings such as `pywin32` / `pyobjc` /
`python-xlib` used directly (Phase 3 may add them *behind the existing ports*
where pynput or pywinctl fall short - the architecture already allows that
without touching the core).
