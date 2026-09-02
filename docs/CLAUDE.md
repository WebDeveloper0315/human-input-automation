# Claude Code Instructions

Read `README.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md` before changing
code.

## Layering (non-negotiable)

```
ui -> application -> core <- adapters, with ports/ between core and adapters
```

* `core/` may import the standard library and `ports/` — nothing else. No
  PySide6, no pynput, no pywinctl, no `os`-specific APIs.
* `application/` may import `core`, `ports` and `adapters` — never Qt.
* Platform code lives in `adapters/` and is imported **lazily**, so importing
  the package never requires a desktop session.
* `ui/` talks to `application/`, never to the engine or the adapters directly.
* `app.py` is the only composition root.

## UI rules

* Widgets stay thin. Anything decidable without Qt belongs in `ui/models.py`,
  which must remain import-clean of PySide6 — `--check` and half the test suite
  depend on that.
* **Never touch a widget from a worker thread.** The only crossing point is
  `ui/run_bridge.RunEventBridge`, which turns run events into queued Qt signals.
  If you need another cross-thread notification, add a signal to the bridge.
* Never run automation on the Qt thread, and never block it waiting for the
  worker (including in the emergency-stop path).
* Never sleep on the Qt thread; the countdown lives in `application/runner.py`
  and uses the run's `RunControl`.
* The emergency stop is never disabled, never hidden behind a menu or dialog,
  and always reachable by keyboard.
* Show capability state honestly: available / restricted / denied / unknown /
  unavailable. "Unknown" is never rendered as "no", and status is never carried
  by colour alone.
* Show users messages, not tracebacks. Unexpected exceptions still go to the log
  with enough detail to debug.
* New action type? Add the dataclass and handler in `core/`, then an
  `ActionSpec` in `ui/models.py` — the editor dialog is generated from it.

## Platform rules

* All platform key names live in `adapters/keymap.py`. Nowhere else.
* Never report a capability as available without evidence, and never render
  `unknown` as "no". Use the five states in `core/capabilities.py`.
* Choose adapters from capabilities, not from the OS name. Linux/X11 and
  Linux/Wayland are different platforms.
* Wrap every third-party platform call: a backend defect must surface as data
  (empty result, `False`, `None`) with a reason, never as a traceback.
* Make third-party modules injectable (`module=`, `display=`) so adapter logic
  is testable without the library and without a desktop.
* Never work around a platform's security model. Wayland restrictions and macOS
  permissions are reported and explained, never circumvented.
* Mark OS-dependent tests (`@pytest.mark.manual`, `windows`, `macos`, `linux`,
  `x11`, `wayland`). They are excluded from the default run; CI never needs a
  desktop.
* When you verify something on a real machine, record it in
  `docs/PHASE3-PLATFORM-REPORT.md` with what you ran. Never upgrade a
  "NOT TESTED" to "PASS" without executing the test.

## Profile rules

* Persistence stays in `application/profiles/`. The core never learns that
  files exist, and no profile module may import Qt or a platform library.
* Bump `SCHEMA_VERSION` and add a migration for any change to the stored shape.
  Never infer the version from which fields are present.
* Reject unknown fields and unknown action types; never ignore them silently.
* Profiles are data. Never add a field that names a command, script or path to
  execute.
* Store identity (platform, app id, process name, title), never handles, pids,
  capabilities or focus state as identity.
* Resolution must be deterministic. Two matches means ambiguous, not "pick the
  first"; no match means unresolved, never "use the focused window".
* Load, import, export, validate, resolve and list must remain side-effect free
  with respect to input. Only Start runs automation.
* Do not duplicate `validate_plan`; sequence structural checks then call it.
* Never report a profile as saved when the write failed.

## Packaging rules

* One packaging system (PyInstaller). Do not add a second without a concrete
  reason the first cannot cover.
* Never import PyInstaller from application code, and never force-import a
  platform library to make freezing easier. Hidden imports belong in the spec.
* Find bundled files through `paths.resource_path`, never by walking up from
  `__file__`.
* Keep user data out of the installation directory, and never delete profiles
  during uninstall.
* Metadata (name, version, identifiers) comes from `metadata.py`; a test keeps
  it in step with `pyproject.toml`.
* Verify artifacts by running them (`--smoke-test`), not by checking that a
  file exists. Automated verification never sends input.
* Signing and notarisation run only when credentials are present, and an
  unsigned build must be labelled unsigned - never implied to be signed.
* Do not upgrade a platform from "packaged" to "verified" without executing the
  manual checklist on that platform, and record results in
  `docs/PHASE3-PLATFORM-REPORT.md`.
* Never log automated text or profile contents.

## Verification rules

* Fake adapters are never evidence of real OS behaviour. Only
  `tools/platform_verify/` results, or a manual run, can move a platform from
  "implemented" to "verified".
* Real input is generated in exactly one place outside the app: the harness.
  It types only into its own target, dry-runs first, and never runs a
  destructive action.
* Never inject input into someone's live desktop to test something. Use the
  isolated X server (`run_x11_session.sh`).
* Every bug found on a real platform gets a regression test against fakes, so
  the deterministic suite keeps catching it.
* Record what was executed in `docs/PHASE6-REAL-PLATFORM-REPORT.md`, and never
  turn a NOT TESTED into a PASS without running it.
* When a third-party library cannot do something, expose it through the
  capability system and say so - do not build a fragile workaround.
* Reading a dependency's source is legitimate evidence for *fixing* a defect,
  and is never evidence that a platform works. Label it "source-verified, not
  executed".
* Platform assumptions do not transfer. pywinctl's handle is an HWND on
  Windows and `(app, title)` on macOS; pynput overrides key matching on Windows
  but not on macOS or X11. Check the backend you mean.

## Invariants

* Never send input before the target is activated and focus is checked.
* Every delay must be interruptible (`Event.wait`), never `time.sleep`, so the
  emergency stop stays responsive.
* Always release held keys and mouse buttons in a `finally`.
* Dry run must be incapable of reaching the desktop, and must not duplicate the
  execution algorithm.
* Validation reports errors and warnings; it never silently drops an action, and
  never silently clamps invalid user input.
* Timing changes go through `TimingService`; no ad-hoc sleeps and no second
  timing algorithm in the GUI.
* A global hotkey is a convenience, never the primary safety control; report
  unsupported platforms instead of pretending.
* Never claim input is indistinguishable from a human, and never add features
  aimed at defeating anti-bot, CAPTCHA or access controls.
* Be honest about platform differences — especially Wayland restrictions and
  macOS Accessibility permissions.
* Validate keys and coordinates against the host before a run rather than
  failing halfway through one.
* Re-verify the target still has focus during a run where the platform allows
  it; never let a plan continue into a window the user did not select.

## Tests

* Test the core and the application layer with the fakes in `tests/fakes.py`;
  never require a real desktop, display server or permission in CI.
* Use `FakeClock` (and its `on_sleep` hook) for deterministic timing and
  cancellation tests.
* Prefer testing UI logic through `ui/models.py` (no Qt needed). Widget tests
  run on the `offscreen` platform via `tests/conftest.py` and must skip cleanly
  when the `gui` extra is missing.
* Use the `pump` fixture to drive queued signals; never `sleep` waiting for a
  worker thread.
* Add tests with every behaviour change.

## Before finishing any change

```bash
pytest
ruff check .
mypy src
mypy src tests
python -m human_input_automation --check      # must work headless
python -m human_input_automation --diagnose  # must work headless, sends no input
python -m human_input_automation --profiles  # must work headless, sends no input
python -m human_input_automation --smoke-test # starts the UI, stores a profile, no input
```

All must pass. Do not skip or silence failing tests, and do not weaken strict
typing to get green. Update `docs/ROADMAP.md` and `docs/ARCHITECTURE.md` when
the architecture changes.
