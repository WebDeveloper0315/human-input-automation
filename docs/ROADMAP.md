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

## Phase 3 — Platform adapters (partially done; verification incomplete)

Done:

- [x] Capability matrix with available / restricted / denied / unknown /
      unavailable, per platform **and** display server
- [x] macOS Accessibility and Input Monitoring modelled as separate
      permissions, each naming its settings pane and the restart requirement
- [x] Centralised key translation (`adapters/keymap.py`) with per-platform key
      gaps; `Key.INSERT` on macOS is rejected by validation before a run starts
- [x] EWMH/X11 window adapter, replacing pywinctl on Linux (pywinctl raises
      `KeyError: 'id'` on Ubuntu 26.04 GNOME)
- [x] Every pywinctl and Xlib call wrapped: backend failures become data
- [x] Window backend chosen from capabilities, not the OS name
- [x] Screen geometry, coordinate space, and off-screen coordinate validation
- [x] Deadline-accurate, interruptible mouse movement
- [x] Mid-run focus re-verification (stop rather than silently redirect)
- [x] Target lifecycle handling: closed, renamed, restarted, replaced, recycled
      window ids
- [x] Adapter resource lifecycle (`AdapterSet.close`)
- [x] `--diagnose` read-only diagnostics
- [x] Platform-marked tests (`windows`/`macos`/`linux`/`x11`/`wayland`/`manual`),
      excluded from the default run

Still open — these need physical machines:

- [ ] Execute the manual checklist in `docs/PHASE3-PLATFORM-REPORT.md` §7 on
      Windows 10/11, macOS and a native X11 session
- [ ] Verify window activation actually focuses the selected window on each
      platform (the critical test; not executed anywhere yet)
- [ ] Verify synthetic keyboard and mouse input end to end (no input has been
      injected on any platform)
- [ ] Verify non-US keyboard layouts (QWERTZ, AZERTY)
- [ ] Verify Windows display scaling and macOS Retina coordinate behaviour
- [ ] Verify the global hotkey, including the macOS Input Monitoring prompt
- [ ] Consider `pywin32` behind the ports if `SetForegroundWindow` edge cases
      require it
- [ ] Investigate Wayland portals (`xdg-desktop-portal` RemoteDesktop) as a
      sanctioned input path, without circumventing any restriction

## Phase 4 — Profiles and persistence (done)

- [x] Versioned schema (`"schema": 1`), never inferred, newer versions rejected
      explicitly; migration registry in place for a future version 2
- [x] Pure serialization: no filesystem, Qt or OS access; lossless generic
      encoding with strict explicit decoding
- [x] Unknown action types and unknown fields rejected with named errors
- [x] Persistent `TargetIdentity` (platform, app id, process name, title,
      pattern) separated from transient handles, pids and capabilities
- [x] Deterministic target resolver; ambiguity reported, never guessed; the
      focused window is never a fallback
- [x] Explicit states: `PROFILE_VALID`, `PROFILE_INVALID`, `TARGET_RESOLVED`,
      `TARGET_UNRESOLVED`, `TARGET_AMBIGUOUS`, `TARGET_CAPABILITY_BLOCKED`
- [x] Atomic JSON repository in the platform data directory; ids as filenames,
      so profile names can never reach the filesystem
- [x] Corrupt, empty and unreadable files surfaced in listings, not fatal
- [x] UI: profile picker, New/Save/Save As/Duplicate/Delete/Import/Export,
      target status with a Resolve action, unsaved-changes indicator and
      Save/Discard/Cancel prompt (including on close)
- [x] `--profiles` and `--validate-profile`, neither of which sends input
- [x] Loading, importing, resolving and validating proven inert
- [x] 217 profile tests (serialization, repository, resolver, service, UI)

Deliberately not done here: YAML profiles, a profile database, cloud sync.

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
