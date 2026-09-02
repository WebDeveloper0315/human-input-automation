# Phase 7 — macOS report

## Status: NOT TESTED

**No Mac was available.** Nothing here is a test result. The findings below are
*source-verified* — read from the installed libraries' own code — and they
changed the product, but they are not evidence that macOS works.

| | |
| --- | --- |
| macOS execution attempted | no |
| Artifact built | no — the `build` job for `macos-14` has never run |
| Artifact launched | no |
| Real input executed | no |
| Signing | NOT PERFORMED — no Developer ID credentials |
| Notarization | NOT PERFORMED — no credentials |

## Environment to record when this is run

```
macOS version            (sw_vers)
Chip                     Apple Silicon / Intel
Application version
Artifact                 …-macos-arm64.dmg
SHA256
pynput / pywinctl / PySide6 versions
Displays                 Retina? scale factor? arrangement?
Keyboard layout
Permissions granted at the time of each test
```

## Source-verified findings (not executed)

### 1. macOS needs **three** permissions, not two — and we had the attribution wrong

pywinctl's macOS backend drives window control through AppleScript. From
`_pywinctl_macos.py` as installed:

```python
def activate(self, wait=False, user=True) -> bool:
    ...
    cmd = """on run {arg1, arg2}
                tell application "System Events" to tell application process appName
                    set frontmost to true
    ...
    proc = subprocess.Popen(['osascript', '-', self._appName, self._winTitle], ...)
```

`getAllWindows()` (via `_getWindowTitles`) and `getActiveWindow()` do the same —
61 `osascript` / "System Events" references in that one file. Talking to System
Events is an **Apple Event**, which macOS gates behind the *Automation*
permission: a different pane, and a different grant, from Accessibility.

So the correct attribution is:

| Capability | Permission |
| --- | --- |
| Keyboard input, key hold, mouse move, mouse click | **Accessibility** |
| Window enumeration, activation, focus verification | **Automation (System Events)** |
| Global emergency hotkey | **Input Monitoring** |
| Monitor layout | none (pymonctl uses Quartz — no `osascript`) |

Before this phase the application attributed *window control to Accessibility*.
A user whose window list was empty would have been told to grant Accessibility,
which would not have fixed it.

**Fixed**: `MACOS_AUTOMATION` is now a distinct permission in the capability
matrix, with its own settings-pane location, and window capabilities are gated
on it. `macos_automation_trusted()` probes it via PyObjC where available and
reports **unknown** otherwise — it never guesses, and never prompts.

**Also fixed**: the macOS bundle now declares `NSAppleEventsUsageDescription`.
Without that key macOS refuses the Apple Event outright rather than prompting,
so window control could never have worked in a packaged build. It is the only
privacy key declared, and it describes exactly what the application does with
it.

### 2. The macOS "window handle" is the window title

```python
def getHandle(self) -> Tuple[str, str]:
    """:return: window handle (app:title) as string"""
    return self._appName, title
```

The identifier is `(application, title)`. The whole target model assumes titles
change and handles do not, so on macOS:

* a saved document, a switched browser tab, or an edit marker changes the
  "handle";
* `isActive` also compares titles (`active.title == self._winTitle`);
* two windows of one application with the same title are indistinguishable.

Profiles were already safe — the resolver matches on application identity and
treats a saved handle only as a hint — but *activation* matched strictly by
handle, so a title change between selecting a target and pressing Start would
have failed the run.

**Fixed**: when the exact handle has gone, the adapter falls back to the window's
process, and **only** when exactly one window matches. Several candidates is
ambiguous and is refused; a different process is refused. Regression tests
cover all three cases.

### 3. `Key.INSERT` does not exist on macOS

Established in Phase 3 and unchanged: pynput's `_darwin` backend has no
`insert` member. Validation rejects a plan using it *before* the run starts, so
it cannot fail halfway through. Verify on a real Mac that the error appears at
validation time, not mid-run.

### 4. The hotkey character-key limitation probably *does* apply

`_darwin` has no `canonical()` override, so it inherits the same base
implementation as `_xorg`, where Phase 6 measured that character-key hotkeys
never match. The default `Ctrl+Shift+F9` avoids that shape; whether Ctrl+Alt
also fails on macOS is unknown, and pynput's hotkey listener additionally needs
Input Monitoring.

### 5. Retina coordinates are reported as a percentage

`_pymonctl_macos._scale` returns `(value, value)` where value is
`(native height / current mode height) * 100` — 200 on a Retina display. Our
adapter divides by 100, giving 2.0. Whether pynput's Quartz event posting then
expects **points** or **pixels** is exactly the question a Retina test must
answer; the screen port already declares macOS coordinates as `logical`.

## Results matrix — to be filled in by whoever runs it

| Capability | Result | Notes |
| --- | --- | --- |
| Platform detection | NOT TESTED | |
| Packaged `.app` / `.dmg` builds | NOT TESTED | |
| Artifact launches (unsigned → right-click Open) | NOT TESTED | |
| Accessibility state before granting | NOT TESTED | expect denied/unknown |
| Accessibility after granting + restart | NOT TESTED | |
| Input Monitoring reported separately | NOT TESTED | |
| Automation (System Events) prompt appears | NOT TESTED | new in this phase |
| Window enumeration | NOT TESTED | needs Automation |
| Target activation (decoy focused) | NOT TESTED | release-blocking |
| Activation failure → zero input | NOT TESTED | release-blocking |
| Focus re-verification | NOT TESTED | |
| Text and Unicode input | NOT TESTED | needs Accessibility |
| Named keys; `Key.INSERT` rejected at validation | NOT TESTED | |
| `META` is Command, not Control (`cmd+a`) | NOT TESTED | release-blocking |
| Key hold/release cleanup | NOT TESTED | release-blocking |
| Mouse movement, duration, clicks | NOT TESTED | |
| Retina coordinates (points vs pixels) | NOT TESTED | |
| Multi-monitor geometry | NOT TESTED | |
| Keyboard layouts (US + non-US) | NOT TESTED | |
| Global hotkey `Ctrl+Shift+F9` | NOT TESTED | needs Input Monitoring |
| Emergency stop matrix | NOT TESTED | release-blocking |
| Profile save/restart/re-resolve | NOT TESTED | |
| Code signing | NOT PERFORMED | no credentials |
| Notarization | NOT PERFORMED | no credentials |

## How to run it

```bash
# 1. Diagnostics first, before granting anything - the states should be
#    denied or unknown, and they should name three different permissions.
/Applications/HumanInputAutomation.app/Contents/MacOS/HumanInputAutomation --diagnose

# 2. Grant one permission at a time, quitting and reopening between each,
#    and re-run --diagnose. Confirm that granting Accessibility does NOT
#    make the window list work, and that Automation does.

# 3. The automated harness (from a source checkout)
pip install -e ".[dev,desktop]"
python tools/platform_verify/run_desktop_session.py --confirm
```

Paste `report.json` into this document, replace every NOT TESTED, and file an
issue per FAIL with `--diagnose` output and the log from
`~/Library/Logs/human-input-automation`. Then work through the macOS section of
`docs/RELEASE-CHECKLIST.md` for what the harness cannot cover: the DMG, the
permission prompts themselves, and Gatekeeper behaviour on an unsigned build.
