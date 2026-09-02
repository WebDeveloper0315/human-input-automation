# Phase 7 — Windows report

## Status: NOT TESTED

**No Windows machine or VM was available.** Nothing in this document is a test
result. The findings below are *source-verified* — read from the installed
libraries' own code — which is enough to fix defects and to predict behaviour,
and is **not** enough to claim the platform works.

| | |
| --- | --- |
| Windows execution attempted | no |
| Artifact built | no — the `build` job for `windows-latest` has never run |
| Artifact launched | no |
| Real input executed | no |

The git remote is not authenticated from the development machine, so the CI
workflow that would build and test on a real Windows runner could not be
triggered either.

## Environment to record when this is run

Fill this in from the machine under test; do not infer any of it.

```
Windows version          (winver)
Architecture             x64 / arm64
Application version
Artifact                 …-windows-x64-setup.exe / …-windows-x64.zip
SHA256
pynput / pywinctl / PySide6 versions   (--diagnose prints these paths)
Display scaling          100% / 125% / 150% / 200%, per monitor
Monitor count and arrangement
Keyboard layout
```

## Source-verified findings (not executed)

Read from pywinctl 0.4.1 and pynput 1.8.2 as installed.

### 1. Window handles are stable — unlike macOS

`Win32Window.getHandle()` returns the `HWND` integer. Our adapter stringifies
it, which is stable across title changes and application state. **No change
needed**; recorded because the macOS equivalent is *not* stable (see the macOS
report) and the two must not be assumed alike.

### 2. `activate()` swallows the Win32 failure and reports via `isActive`

```python
def activate(self, wait=False, user=True) -> bool:
    try:
        win32gui.SetForegroundWindow(self._hWnd)
    except:
        pass
    return self.isActive
```

Two consequences:

* A failed `SetForegroundWindow` is **not** an exception; it surfaces as
  `isActive == False`, which our adapter turns into `activate() -> False`, which
  the engine turns into a failed run with **no input sent**. The safety gate
  holds.
* Windows restricts which process may take the foreground. A background
  application generally *cannot* steal focus, so activation may legitimately
  fail. Expected symptom: "Unable to activate the selected window", nothing
  typed. **This must be checked on a real machine**; if it is common, the fix is
  a documented capability note, not weakening the gate.

### 3. The hotkey character-key limitation probably does *not* apply

Phase 6 measured on X11 that pynput's `GlobalHotKeys` never matches character
keys once a modifier is held. `pynput/keyboard/_win32.py` **overrides
`canonical()`** to resolve a character from the key's scan code, which is
precisely the mechanism that was missing on X11:

```python
def canonical(self, key):
    scan = getattr(key, '_scan', None)
    if scan is not None:
        char = self._translator.char_from_scan(scan)
        if char is not None:
            return KeyCode.from_char(char)
    return super().canonical(key)
```

`_darwin` and `_xorg` have no such override. So the limitation is likely
X11/macOS-specific. The default `Ctrl+Shift+F9` avoids the question on every
platform, and must still be confirmed to fire on Windows.

### 4. Monitor scale is a percentage

`_pymonctl_win.scale` returns `GetScaleFactorForMonitor`, i.e. `100`, `125`,
`150`, `200`. Our adapter divides by 100 for values above 10, so 150 becomes
1.5. **Correct by inspection; unverified in practice.**

**Open risk — DPI awareness.** `GetScaleFactorForMonitor` reports the scale, but
whether the *coordinates* pynput uses are physical or virtualised depends on the
process's DPI awareness, which PySide6 sets. If a 150 % display puts the cursor
in the wrong place, that is the first thing to investigate — and the fix belongs
in the screen/input adapter, never in `core/`.

## Results matrix — to be filled in by whoever runs it

| Capability | Result | Notes |
| --- | --- | --- |
| Platform detection | NOT TESTED | |
| Packaged artifact builds | NOT TESTED | |
| Packaged artifact launches | NOT TESTED | |
| Window enumeration | NOT TESTED | |
| Target activation (decoy focused) | NOT TESTED | release-blocking |
| Activation failure → zero input | NOT TESTED | release-blocking |
| Focus re-verification | NOT TESTED | |
| Text input | NOT TESTED | |
| Named keys | NOT TESTED | |
| Modifiers and shortcuts | NOT TESTED | |
| Key hold/release cleanup | NOT TESTED | release-blocking |
| Mouse movement and duration | NOT TESTED | |
| Mouse clicks and drag | NOT TESTED | |
| Screen geometry | NOT TESTED | |
| Display scaling 125/150/200 % | NOT TESTED | |
| Keyboard layouts (US + non-US) | NOT TESTED | |
| Global hotkey `Ctrl+Shift+F9` | NOT TESTED | |
| Emergency stop matrix | NOT TESTED | release-blocking |
| Profile save/restart/re-resolve | NOT TESTED | |

## How to run it

```powershell
# 1. From a release artifact (preferred - tests what users get)
#    Install …-windows-x64-setup.exe, then:
&"$env:LOCALAPPDATA\Programs\human-input-automation\HumanInputAutomation.exe" --diagnose

# 2. From source, to run the automated harness
pip install -e ".[dev,desktop]"
python tools\platform_verify\run_desktop_session.py --confirm
```

The harness opens its own target and decoy windows, dry-runs first, then runs
~51 checks including typing, activation against a decoy, emergency stop and
profile re-resolution. It types **only** into its own target window. Paste the
resulting `report.json` into this document, replace every NOT TESTED with the
real result, and file an issue for each FAIL with the `--diagnose` output and
the log from `%APPDATA%\human-input-automation\logs`.

Then work through the Windows section of `docs/RELEASE-CHECKLIST.md`, which
covers what the harness cannot: installer behaviour, shortcuts, uninstall, and
display scaling.
