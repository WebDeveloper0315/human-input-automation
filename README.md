# Human Input Automation

Cross-platform desktop automation for keyboard and mouse input, inspired by
AutoIt. Windows, macOS and Ubuntu/Linux.

**Status:** Phase 2 complete — the automation core *and* a working desktop UI.
Real per-platform adapter behaviour is Phase 3, profile persistence is Phase 4
(see `docs/ROADMAP.md`).

## What it does

- Pick a **target window** from a live list and send input to it — never a
  silent fallback to whatever happens to be focused
- Build an action sequence: type text, key presses, key down/up, shortcuts,
  mouse move/click/down/up, waits, with per-action delay overrides
- Configure natural timing: bounded jitter, min/max, word and punctuation
  pauses, action delays, mouse movement duration, optional fixed seed — with a
  live preview sampled from the same timing service the engine uses
- Start / Pause / Resume / Stop, a cancellable pre-run countdown, and an
  always-visible emergency stop (`Ctrl+.`, plus a global `Ctrl+Alt+.` hotkey
  where the platform allows it)
- Dry-run preview that reports every action and the estimated duration without
  sending any input
- A run log of structured events, and a capability banner that says what this
  machine can actually do

### What it deliberately does not do

It does not claim to make generated input indistinguishable from a person's, and
it is not designed to bypass anti-bot, CAPTCHA or access controls. "Natural
timing" here means pacing that applications and users can follow, for testing,
accessibility and productivity work.

## Install

```bash
python -m venv .venv
# activate the environment
pip install -e ".[dev]"               # core + pytest/ruff/mypy (no desktop needed)
pip install -e ".[dev,gui]"           # adds PySide6, enough to run the UI and its tests
pip install -e ".[dev,desktop]"       # adds PySide6 + pynput + pywinctl (real input)
```

The core has **no runtime dependencies**. Everything that touches a real desktop
lives behind the `gui`, `input` and `windows` extras (`desktop` installs all
three).

## Run

```bash
python -m human_input_automation           # desktop UI (needs the gui extra)
python -m human_input_automation --check   # report platform capabilities, headless
python -m human_input_automation --verbose # add diagnostic logging
```

`--check` needs no display and no GUI extra. Exit code 0 means automation can be
attempted (possibly with restrictions), 1 means it is unavailable or a
permission is missing:

```
⚠ LIMITED: linux/wayland restricts window control; input can be sent but windows
cannot be listed or focused.

Platform: linux (wayland)
Send input: yes
Enumerate windows: no
Activate windows: no
Verify focus: no
Emergency hotkey: Wayland does not let applications observe global key presses;
use the on-screen emergency stop.
```

## The window

```
┌───────────────────────────────────────────────────────────────┐
│ ⚠ LIMITED / ✓ OK / ✗ UNAVAILABLE  capability + permission     │
├──────────────────────────┬────────────────────────────────────┤
│ TARGET                   │ ACTIONS                            │
│ [Refresh windows]        │ 1. type 'Hello' (5 chars)          │
│ Title | App | PID | Plat │ 2. press enter                     │
│ Active target: ...       │ [Add][Edit][Delete][Up][Down]      │
├──────────────────────────┼────────────────────────────────────┤
│ TIMING                   │ DRY RUN - NO INPUT WILL BE SENT    │
│ base/jitter/min/max      │ Estimated duration: 1.2 s          │
│ word/punctuation/action  │ 1. type 'Hello' ...                │
│ Next delays: 78 104 65   │ Completed 2 action(s).             │
├──────────────────────────┴────────────────────────────────────┤
│ RUN LOG   21:55:08  Run started: desktop plan, 2 action(s)    │
├───────────────────────────────────────────────────────────────┤
│ State: Running   [Start][Pause][Resume][Stop][Dry run] [3 s]   │
│ ███████████████ EMERGENCY STOP (Ctrl+.) ███████████████        │
└───────────────────────────────────────────────────────────────┘
```

While a run is in flight the target list, action editor and timing fields lock,
so the plan cannot change under a running engine. The emergency stop stays
enabled in every state, including during the countdown and while paused.

## Using the core directly

```python
from human_input_automation.application import AutomationService
from human_input_automation.core import (
    AutomationPlan, KeyPress, RunOptions, Shortcut, TimingProfile, TypeText,
)

service = AutomationService()
listing = service.discover_targets()        # .targets, plus .reason when empty
target = listing.targets[0]

plan = AutomationPlan(
    target=target,
    actions=[
        TypeText(text="Hello, world."),
        KeyPress(key="enter"),
        Shortcut.parse("ctrl+s"),
    ],
    timing=TimingProfile(char_delay_ms=70, word_pause_ms=120, punctuation_pause_ms=250),
    options=RunOptions(seed=42),            # reproducible timing
    name="demo",
)

print(service.dry_run(plan).performed)      # inspect before running for real
service.start(plan, countdown_seconds=3)    # runs on a worker thread
service.emergency_stop()                    # returns immediately, releases held keys
```

## Platform support

| | Windows | macOS | Linux/X11 | Linux/Wayland |
| --- | --- | --- | --- | --- |
| Enumerate windows | yes | with permission | yes | no |
| Activate window | yes | with permission | yes | no |
| Verify focus | yes | with permission | yes | no |
| Synthetic input | yes | Accessibility permission | yes | restricted (XWayland clients at best) |
| Global stop hotkey | yes | Input Monitoring permission | yes | no |

macOS requires Accessibility permission for the host application; without it,
input and window control silently do nothing, so the app reports the missing
permission instead of pretending to work. Wayland restricts window control and
global input injection by design — the app says so, and the on-screen emergency
stop always works regardless.

These capability tables describe what each platform *allows*. Real end-to-end
input behaviour on Windows, macOS and X11 has not been verified on those
systems yet; that is Phase 3.

## Development

```bash
pytest                                     # 253 tests with the gui extra, 187 without
ruff check .
mypy src
mypy src tests
python -m human_input_automation --check
```

Qt tests use the `offscreen` platform plugin (set automatically in
`tests/conftest.py`), so the whole suite runs headless; without PySide6 the
three Qt modules skip themselves. No test needs a real desktop, display server
or OS permission.

See `docs/ARCHITECTURE.md` for the layering, the Qt threading rule and the
design decisions, `docs/ROADMAP.md` for what comes next.
