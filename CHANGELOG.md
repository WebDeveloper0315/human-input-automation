# Changelog

All notable changes to this project. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/).

The application version and the profile schema version are independent: this
release is 0.6.0 and writes profile **schema 1**, and a later application
version may still write schema 1.

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
