# Claude Code Instructions

Read `README.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md` before changing
code.

## Layering (non-negotiable)

```
ui -> application -> core <- adapters, with ports/ between core and adapters
```

* `core/` may import the standard library and `ports/` — nothing else. No
  PySide6, no pynput, no pywinctl, no `os`-specific APIs.
* Platform code lives in `adapters/` and is imported **lazily**, so importing
  the package never requires a desktop session.
* `ui/` talks to `application/`, never to the engine or the adapters directly.
* `app.py` is the only composition root.

## Invariants

* Never send input before the target is activated and focus is checked.
* Every delay must be interruptible (`Event.wait`), never `time.sleep`, so the
  emergency stop stays responsive.
* Always release held keys and mouse buttons in a `finally`.
* Never run automation on the UI thread.
* Dry run must be incapable of reaching the desktop.
* Validation reports errors and warnings; it never silently drops an action.
* New action types are added by registering a handler, not by editing the
  engine's loop.
* Timing changes go through `TimingService`; no ad-hoc sleeps.
* Never claim input is indistinguishable from a human, and never add features
  aimed at defeating anti-bot, CAPTCHA or access controls.
* Be honest about platform differences — especially Wayland restrictions and
  macOS Accessibility permissions. "Unknown" is a valid answer; guessing is not.

## Tests

* Test the core with the fakes in `tests/fakes.py`; never require a real
  desktop, display server or permission in CI.
* Use `FakeClock` (and its `on_sleep` hook) for deterministic timing and
  cancellation tests.
* Add tests with every behaviour change.

## Before finishing any change

```bash
pytest
ruff check .
mypy src
```

All three must pass. Do not skip or silence failing tests. Update
`docs/ROADMAP.md` and `docs/ARCHITECTURE.md` when the architecture changes.
