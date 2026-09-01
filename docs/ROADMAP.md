# Roadmap

## Phase 1 — Core architecture (done)

- [x] Layered package: `core` / `ports` / `adapters` / `application` / `ui`
- [x] Discriminated-union action model with per-action validation
- [x] Extensible action dispatch (`ActionRegistry`) — new actions need no engine change
- [x] `TargetWindow` with handle, process, app id, platform and capabilities
- [x] Capability/permission detection per platform (`describe_host`)
- [x] Timing service: bounded jitter, min/max, word and punctuation pauses,
      action delays, mouse movement duration, deterministic seeds
- [x] Engine with target activation + focus verification before any input
- [x] Interruptible delays, pause/resume, stop and emergency stop
- [x] Guaranteed release of held keys and mouse buttons
- [x] Dry-run mode that cannot reach the desktop
- [x] Execution limits (actions, text length, total characters, duration)
- [x] Run events and `RunReport`
- [x] Threaded runner and `AutomationService` facade (GUI never blocks)
- [x] 115 tests against fake adapters; headless CI on Linux/macOS/Windows
- [x] `ruff` + `mypy --strict` clean, `py.typed` shipped

## Phase 2 — Desktop UI

- [ ] Target list with refresh, search and a persistent active-target indicator
- [ ] Action editor (text + action list) backed by the action model
- [ ] Timing profile controls with live preview of the resulting delays
- [ ] Start / Pause / Resume / Stop buttons wired to `AutomationService`
- [ ] Emergency stop: always-visible button, global hotkey, and a hard cap on
      how long any single action may block
- [ ] Run log fed by `RunEvent`s, marshalled onto the UI thread via Qt signals
- [ ] Dry-run preview panel showing `RunReport.performed`
- [ ] Capability banner showing `PlatformReport` warnings and missing permissions
- [ ] Countdown before a run starts, so the user can abort

## Phase 3 — Platform adapters

- [ ] Windows: verify pywinctl handles; consider `pywin32` behind the ports for
      `SetForegroundWindow` edge cases and per-window input
- [ ] macOS: Accessibility permission prompt and diagnostics; verify activation
      through the Accessibility APIs
- [ ] Linux/X11: verify enumeration, activation and focus checks under common
      window managers
- [ ] Wayland: portal-based diagnostics, and a clear, honest "unsupported here"
      path instead of silent failure
- [ ] Per-key layout handling (non-US keyboard layouts) in the input adapter
- [ ] Manual verification checklist per platform (cannot run in CI)

## Phase 4 — Profiles and persistence

- [ ] JSON serialisation for `AutomationPlan` (stdlib only)
- [ ] Save/load/rename profiles, with schema versioning
- [ ] Optional YAML import/export behind the `[yaml]` extra
- [ ] Target re-resolution on load (handles change between sessions)

## Phase 5 — Packaging and distribution

- [ ] PyInstaller builds for Windows, macOS and Linux
- [ ] macOS signing/notarisation notes and permission onboarding
- [ ] Versioned release artifacts and installation documentation

## Phase 6 — Advanced

- [ ] Mouse path interpolation strategies
- [ ] Global hotkeys for start/stop
- [ ] Scroll, drag and multi-monitor coordinate support
- [ ] Recording mode, only behind an explicit user action and a visible indicator

## Out of scope

Anything framed as making automated input undetectable, or as bypassing
anti-bot, CAPTCHA or access controls.
