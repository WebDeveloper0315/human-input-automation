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
- [x] Tests against fake adapters; headless CI on Linux/macOS/Windows
- [x] `ruff` + `mypy --strict` clean, `py.typed` shipped

## Phase 2 — Desktop UI (done)

- [x] Target list with refresh, per-window metadata and a persistent
      active-target indicator; no silent fallback to the focused window
- [x] Reason shown when windows cannot be enumerated (Wayland, permissions,
      missing adapter), and invalid targets flagged before a run starts
- [x] Action editor: add, edit, delete, reorder, per-action delay override,
      validation errors surfaced inline
- [x] Generated per-action forms driven by `ACTION_SPECS`, so a new action type
      gets an editor without new widget code
- [x] Timing panel for the full `TimingProfile`, rejecting invalid combinations
      (for example `min > max`) instead of silently clamping
- [x] Live timing preview sampled from the real `TimingService`, with an
      optional fixed seed
- [x] Start / Pause / Resume / Stop with a visible run state and editing locked
      while a run is in flight
- [x] Pre-run countdown on the worker thread, cancellable, activating the target
      only after it completes
- [x] Always-visible emergency stop (`Ctrl+.`), enabled in every state, updating
      the UI without waiting for the worker
- [x] Global emergency-stop hotkey behind `HotkeyPort`, with honest
      per-platform support reporting (never fabricated)
- [x] Dry-run panel: same plan and timing, recording adapters, estimated
      duration, ordered actions, result
- [x] Run log fed by `RunEvent`s
- [x] Worker → Qt thread marshalling through a single `RunEventBridge`, proven
      by a test that records slot thread identity
- [x] Capability banner distinguishing available / restricted / denied /
      unknown / unavailable, never colour-only, never showing unknown as "no"
- [x] User-facing error messages instead of tracebacks
- [x] Keyboard-accessible controls, accessible names, explicit tab order
- [x] Qt tests on the `offscreen` platform; they skip when the `gui` extra is
      absent, so the suite still runs without Qt

## Phase 3 — Platform adapters

- [ ] Windows: verify pywinctl handles; consider `pywin32` behind the ports for
      `SetForegroundWindow` edge cases and per-window input
- [ ] macOS: Accessibility permission prompt and diagnostics; verify activation
      through the Accessibility APIs; verify Input Monitoring for the hotkey
- [ ] Linux/X11: verify enumeration, activation and focus checks under common
      window managers
- [ ] Wayland: portal-based diagnostics, and a clear, honest "unsupported here"
      path instead of silent failure
- [ ] Per-key layout handling (non-US keyboard layouts) in the input adapter
- [ ] Multi-monitor coordinate handling and screen-bounds validation for
      absolute mouse coordinates
- [ ] Manual verification checklist per platform (cannot run in CI)

## Phase 4 — Profiles and persistence

- [ ] JSON serialisation for `AutomationPlan` (stdlib only)
- [ ] Save/load/rename profiles, with schema versioning
- [ ] Optional YAML import/export behind the `[yaml]` extra
- [ ] Target re-resolution on load (handles change between sessions)
- [ ] Recent-profile list and unsaved-change prompts in the UI

## Phase 5 — Packaging and distribution

- [ ] PyInstaller builds for Windows, macOS and Linux
- [ ] macOS signing/notarisation notes and permission onboarding
- [ ] Versioned release artifacts and installation documentation

## Phase 6 — Advanced

- [ ] Mouse path interpolation strategies
- [ ] Configurable global hotkeys beyond the emergency stop
- [ ] Scroll and drag actions
- [ ] Recording mode, only behind an explicit user action and a visible indicator

## Out of scope

Anything framed as making automated input undetectable, or as bypassing
anti-bot, CAPTCHA or access controls.
