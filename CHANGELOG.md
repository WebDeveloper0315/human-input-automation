# Changelog

All notable changes to this project. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/).

The application version and the profile schema version are independent: this
release is 0.6.0 and writes profile **schema 1**, and a later application
version may still write schema 1.

## [0.7.1] - 2026-09-02

Windows and macOS verification was the goal; **no machine of either kind was
available**, so it did not happen. What did happen is a source-level audit of
those adapter paths against the installed libraries, which found three macOS
defects worth fixing before anyone tries.

### Fixed

- **macOS window control was attributed to the wrong permission.** pywinctl
  drives window enumeration, activation and focus verification through
  AppleScript to System Events, which macOS gates behind **Automation** — a
  different grant from Accessibility. A user with an empty window list would
  have been told to grant Accessibility, which would not have helped.
  Automation is now a distinct capability with its own settings-pane location
  and its own probe.
- **The macOS bundle did not declare `NSAppleEventsUsageDescription`.** Without
  it macOS refuses the Apple Event outright, so window control could never have
  worked in a packaged build. It is the only privacy key declared.
- **macOS window handles are `(application, title)`** — they change whenever the
  title does. Activation matched strictly by handle, so a saved document or a
  switched tab would have failed the run. The adapter now falls back to the
  window's process, and only when exactly one window matches; several
  candidates is still refused, as is a different process.

### Added

- `tools/platform_verify/run_desktop_session.py`: the verification harness now
  runs on any desktop session, so Windows and macOS testers use the same
  ~51 checks. It requires `--confirm` before generating real input.
- `docs/PHASE7-WINDOWS-REPORT.md` and `docs/PHASE7-MACOS-REPORT.md`: every
  source-verified finding, and a matrix of everything still NOT TESTED.

### Known limitations

- **Windows and macOS remain entirely unverified.** No artifact built, no
  application launched, no input sent, no permission granted. Their CI build
  jobs have never run.
- macOS signing and notarization: **NOT PERFORMED** — no credentials.
- Linux/X11 remains verified only against an isolated X server with a minimal
  window manager, not a full desktop.

## [0.7.0] - 2026-09-02

Real-platform verification: the adapters were finally run against a real X
server instead of fakes, and three genuine bugs came out of it.

### Added

- Platform verification harness (`tools/platform_verify/`): a safe target
  application that records the input it receives, a minimal EWMH window manager
  for bare X servers, a driver that runs 51 checks, and an isolated-session
  launcher. It types only into its own target and always dry-runs first.
- `adapters/x11_screens.py`: monitor layout read from RandR, which is
  authoritative for the display actually connected to.
- `problematic_combination()`: warns about global-hotkey shapes that pynput was
  measured never to match.
- CI job `verify-x11`: the real-input verification runs on every push against a
  private X server, so this configuration cannot silently regress.
- `docs/PHASE6-REAL-PLATFORM-REPORT.md` with the full evidence.

### Changed

- **The default emergency hotkey is now `Ctrl+Shift+F9`** (was `Ctrl+Alt+.`).
  Measured against a real X server, pynput never fires for combinations holding
  Ctrl and Alt together, nor for character keys once a modifier is held - the
  old default was both, so it could never have worked.
- Linux reads its monitor layout from RandR rather than pymonctl.
- `PynputHotkey.start()` waits for the listener backend to be ready, so a
  hotkey that failed asynchronously is reported as not registered instead of
  appearing active.

### Fixed

- **Window activation reported false failures.** Activation is a request to the
  window manager, which acts asynchronously; the adapter read the focus property
  immediately afterwards and saw the previous window. It now waits, bounded, for
  the request to be honoured.
- **Screen geometry could describe the wrong display.** pymonctl returned
  duplicated monitors plus monitors belonging to another display - a 1024×768
  screen was reported as a 3840×1080 desktop, which would have let coordinate
  validation accept points that are nowhere on screen.
- Duplicate monitors are collapsed on the platforms still using pymonctl.

### Known limitations

- Windows and macOS remain **entirely unverified**: no artifact has been built
  or run, and no permission has ever been granted or denied.
- Linux/X11 was verified against an isolated X server with a minimal window
  manager written for the harness - not GNOME, KDE or i3.
- No input has ever been injected into a Wayland session; its restrictions are
  reported, not worked around.
- Non-US keyboard layouts, display scaling above 100% and macOS Retina
  coordinates are all untested.

## [0.6.0] - 2026-09-01

First distributable release: the application can now be installed on a machine
that has no Python, which is what the remaining platform verification needs.

### Added

- **Packaged builds** for Windows, macOS and Linux, produced by PyInstaller
  from a single spec on native runners (nothing is cross-compiled).
  - Linux: `.AppImage` (falls back to a `.zip` when `appimagetool` is absent)
  - macOS: `.app` inside a `.dmg`
  - Windows: application directory, `.zip`, and a per-user Inno Setup installer
    that requires no administrator rights
- `packaging/build.py`: builds, **verifies** and checksums the artifact in one
  command. Verification runs the real application, not a file-exists check.
- `--smoke-test`: starts the application, opens its window, round-trips a
  profile and exits. Sends no keyboard or mouse input; used to check artifacts.
- `--version`.
- Application icons generated reproducibly from `packaging/common/make_icons.py`
  (PNG, ICO, ICNS; no network access needed).
- Per-user data and log directories following platform conventions, with
  first-run initialisation. Profiles and logs are stored **outside** the
  installation directory.
- File logging with rotation, plus a redaction filter that keeps automated text
  out of the log.
- First-run briefing and permission onboarding. macOS Accessibility and Input
  Monitoring are shown as **separate** grants, each naming what it blocks, the
  System Settings pane that grants it and whether a restart is needed.
- Actionable start-up failures for a missing GUI, no display, an unloadable Qt
  platform plugin and an unwritable data directory - no raw tracebacks.
- Release pipeline (`.github/workflows/release.yml`): test → quality → build →
  verify → draft release, triggered by a `v*` tag, with `SHA256SUMS`.
- macOS signing/notarisation support that runs **only** when credentials are
  configured; unsigned builds are labelled unsigned.
- `docs/RELEASE-CHECKLIST.md` with the manual per-platform verification
  procedure, and a safe verification profile that only types into a scratch
  text editor.

### Changed

- Version 0.5.0 → 0.6.0. Deliberately **not** 1.0.0: real keyboard, mouse and
  window automation has still not been executed on Windows, macOS or a native
  X11 session, and calling that 1.0 would overstate what has been verified.
- The platform data directory has one implementation (`paths.py`); the profile
  repository now uses it instead of its own copy.
- Bundles exclude Qt Quick/QML, the GTK platform theme and all development
  tooling, cutting the Linux bundle from 217 MB to 185 MB (66 MB compressed).

### Fixed

- Bundled resources resolved to the wrong path inside a PyInstaller bundle, so
  the application icon was missing in packaged builds. Found by the packaged
  smoke test.

### Known limitations

- **Real input is unverified on every platform.** No synthetic keyboard or
  mouse input has been executed on Windows, macOS or a native X11 session, and
  none was injected during packaging. `docs/PHASE3-PLATFORM-REPORT.md` records
  exactly what was executed.
- **Windows and macOS artifacts have not been built or run.** Their
  configuration exists and is reviewed, but no Windows or macOS machine was
  available; the CI jobs that build them have not been executed.
- **Windows artifacts are unsigned**; SmartScreen will warn.
- **macOS artifacts are unsigned and un-notarised** unless release credentials
  are configured; Gatekeeper will warn.
- macOS permission detection needs PyObjC to give a definite answer; without it
  the state is reported as unknown, never as denied.
- Wayland restricts window enumeration, activation and global hotkeys. The
  packaged application reports this and does not work around it.
- Non-US keyboard layouts are unverified.
- Only one architecture is built per platform (x86_64 Linux, arm64 macOS, x64
  Windows). No universal binaries.

## [0.5.0] - 2026-09-01

### Added

- Versioned JSON profiles (schema 1) with atomic storage, strict validation,
  deterministic target re-resolution, import/export and unsaved-change
  handling. See `docs/PROFILE-FORMAT.md`.

## [0.4.0] - 2026-09-01

### Added

- Capability matrix (available / restricted / denied / unknown / unavailable),
  X11/EWMH window adapter, centralised key mapping with per-platform key gaps,
  screen geometry and coordinate validation, mid-run focus re-verification and
  `--diagnose`. See `docs/PHASE3-PLATFORM-REPORT.md`.

## [0.3.0] - 2026-09-01

### Added

- PySide6 desktop UI: target picker, action editor, timing panel with live
  preview, run controls, countdown, dry-run panel, run log, capability banner
  and an always-available emergency stop.

## [0.2.0] - 2026-09-01

### Added

- Layered architecture (core / ports / adapters / application), action model,
  timing service, cancellation, dry run and execution limits.
