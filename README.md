# Human Input Automation

Cross-platform desktop automation for keyboard and mouse input, inspired by
AutoIt. Windows, macOS and Ubuntu/Linux.

**Status:** Phase 1 complete — the automation core, interfaces, engine, timing
and safety mechanisms are implemented and tested. The desktop UI and the
platform adapters are Phase 2 and Phase 3 (see `docs/ROADMAP.md`).

## What it does

- Type text and run keyboard/mouse action sequences
- Send input to a **selected target window**, not just whatever has focus
- Configurable, natural timing: bounded jitter, word and punctuation pauses,
  per-action delays, mouse movement duration, deterministic seeds
- Start / Pause / Resume / Stop, plus an emergency stop that interrupts a
  pending delay instead of waiting it out
- Dry-run mode that reports every action without touching the desktop
- Safety limits on action count, text length and run duration

### What it deliberately does not do

It does not claim to make generated input indistinguishable from a person's, and
it is not designed to bypass anti-bot, CAPTCHA or access controls. "Natural
timing" here means pacing that applications and users can follow, for testing,
accessibility and productivity work.

## Install

```bash
python -m venv .venv
# activate the environment
pip install -e ".[dev]"          # core + pytest/ruff/mypy (no desktop needed)
pip install -e ".[dev,desktop]"  # adds PySide6, pynput and pywinctl
```

The core has **no runtime dependencies**. Everything that touches a real desktop
lives behind the `gui`, `input` and `windows` extras (`desktop` installs all
three).

## Run

```bash
python -m human_input_automation --check   # report platform capabilities
python -m human_input_automation           # desktop UI (needs the gui extra)
```

`--check` is the fastest way to see what your machine supports:

```
Platform: linux (wayland)
Send input: yes
Enumerate windows: no
Activate windows: no
Verify focus: no
Note: Wayland compositors restrict global synthetic input and window control ...
```

## Using the core directly

```python
from human_input_automation.application import AutomationService
from human_input_automation.core import (
    AutomationPlan, KeyPress, RunOptions, Shortcut, TimingProfile, TypeText,
)

service = AutomationService()
target = service.list_targets()[0]          # or service.focused_window_target()

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
service.start(plan)                         # runs on a worker thread
service.emergency_stop()                    # returns immediately, releases held keys
```

## Platform support

| | Windows | macOS | Linux/X11 | Linux/Wayland |
| --- | --- | --- | --- | --- |
| Enumerate windows | yes | with permission | yes | no |
| Activate window | yes | with permission | yes | no |
| Verify focus | yes | with permission | yes | no |
| Synthetic input | yes | Accessibility permission | yes | restricted (XWayland clients at best) |

macOS requires Accessibility permission for the host application; without it,
input and window control silently do nothing, so the app reports the missing
permission instead of pretending to work. Wayland restricts window control and
global input injection by design — the app says so rather than failing quietly.

## Development

```bash
pytest          # 115 tests, no desktop required
ruff check .
mypy src
```

The core is tested entirely against fake adapters and a virtual clock, so the
suite runs headless on all three platforms in CI.

See `docs/ARCHITECTURE.md` for the layering and design decisions,
`docs/ROADMAP.md` for what comes next.
