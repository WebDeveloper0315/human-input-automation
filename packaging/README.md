# Packaging

One packaging system: **PyInstaller**. See `docs/ARCHITECTURE.md` for why.

```
packaging/
├── human-input-automation.spec   one spec, branches per platform
├── build.py                      build + verify + checksum driver
├── common/
│   ├── launcher.py               frozen entry point
│   └── make_icons.py             generates the icons (no network)
├── windows/installer.iss         Inno Setup, per-user, no admin
├── macos/entitlements.plist      hardened-runtime entitlements
├── macos/sign_and_notarize.sh    signs only when credentials exist
└── linux/{AppRun,*.desktop}      AppImage integration
```

## Build

```bash
pip install -e ".[dev,desktop]" pyinstaller
python packaging/build.py
```

The driver runs PyInstaller, verifies the result with `--smoke-test` (which
opens the real window and round-trips a profile but **sends no input**), then
produces the platform artifact and `SHA256SUMS`.

| Platform | Artifact | Extra tool |
| --- | --- | --- |
| Linux | `.AppImage` (falls back to `.zip`) | `appimagetool` on `PATH` |
| Windows | application directory + `.zip`; `.exe` installer via Inno Setup | `iscc` for the installer |
| macOS | `.app` inside a `.dmg` | `hdiutil` (built in) |

## Build environment

Artifacts are built on **native runners** — a Linux AppImage from Ubuntu, a
`.exe` from Windows, a `.app` from macOS. Nothing is cross-compiled.

| | Pinned in CI |
| --- | --- |
| Python | 3.12 |
| PyInstaller | `>=6.10,<7` |
| PySide6 | `>=6.7` |
| Ubuntu image | `ubuntu-22.04` (oldest glibc we support, so the AppImage runs on newer systems too) |
| Windows image | `windows-latest`, x64 |
| macOS image | `macos-14` (arm64) |

The Linux build deliberately uses the older Ubuntu image: glibc is
backwards-compatible, so a binary built against an older one runs on newer
distributions, but not the other way round.

## Signing

* **Windows** — unsigned. Authenticode signing needs a purchased certificate;
  add it to the release workflow when one exists.
* **macOS** — `sign_and_notarize.sh` signs and notarises **only** when the
  credentials are present in the environment. With no credentials the build is
  produced unsigned and is labelled unsigned in the release notes. Credentials
  come from CI secrets and never from the repository, the spec or the logs.
