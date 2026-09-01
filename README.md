# Human Input Automation

Cross-platform desktop automation for keyboard and mouse input, inspired by
AutoIt. Windows, macOS and Ubuntu/Linux.

**Status:** Phase 5 — installable builds for Windows, macOS and Linux, on top of
the automation core, desktop UI, capability model and saved profiles. **Real
end-to-end input has still not been verified on any platform**; see
"Implemented, packaged, verified" below.

## What it does

- Pick a **target window** from a live list and send input to it — never a
  silent fallback to whatever happens to be focused
- Build an action sequence: type text, key presses, key down/up, shortcuts,
  mouse move/click/down/up, waits, with per-action delay overrides
- Configure natural timing: bounded jitter, min/max, word and punctuation
  pauses, action delays, mouse movement duration, optional fixed seed — with a
  live preview sampled from the same timing service the engine uses
- Start / Pause / Resume / Stop, a cancellable pre-run countdown, and an
  always-visible emergency stop (`Ctrl+.`, plus a global `Ctrl+Alt+.` hotkey
  where the platform allows it)
- Dry-run preview that reports every action and the estimated duration without
  sending any input
- A run log of structured events, and a capability banner that says what this
  machine can actually do
- **Saved profiles**: store a plan and its target, reload it after a restart,
  duplicate, import and export. Profiles remember *which application* they
  target, not a window handle, so they still find it after the app restarts —
  and when they cannot, they say so instead of typing somewhere else

### What it deliberately does not do

It does not claim to make generated input indistinguishable from a person's, and
it is not designed to bypass anti-bot, CAPTCHA or access controls. "Natural
timing" here means pacing that applications and users can follow, for testing,
accessibility and productivity work.

## Install

### From a release (no Python needed)

| Platform | Download | Install |
| --- | --- | --- |
| Windows | `HumanInputAutomation-<version>-windows-x64-setup.exe` | Run it. Installs per-user; **no administrator rights**. |
| macOS | `HumanInputAutomation-<version>-macos-arm64.dmg` | Open and drag to Applications. Unsigned builds need right-click → Open. |
| Linux | `HumanInputAutomation-<version>-linux-x86_64.AppImage` | `chmod +x` and run. |

Check your download first: `sha256sum -c SHA256SUMS`.

Profiles and logs are stored in your user directory, never inside the
installation, and uninstalling does not delete them.

### From source

```bash
python -m venv .venv
# activate the environment
pip install -e ".[dev]"               # core + pytest/ruff/mypy (no desktop needed)
pip install -e ".[dev,gui]"           # adds PySide6, enough to run the UI and its tests
pip install -e ".[dev,desktop]"       # adds PySide6 + pynput + pywinctl (real input)
```

### Building the packages

```bash
pip install -e ".[dev,desktop]" pyinstaller
python packaging/build.py             # build, verify and checksum for this platform
```

See `packaging/README.md` for the build environment and signing.

The core has **no runtime dependencies**. Everything that touches a real desktop
lives behind the `gui`, `input` and `windows` extras (`desktop` installs all
three).

## Run

```bash
python -m human_input_automation             # desktop UI (needs the gui extra)
python -m human_input_automation --check     # short capability summary, headless
python -m human_input_automation --diagnose  # full platform report, sends no input
python -m human_input_automation --profiles  # list saved profiles
python -m human_input_automation --validate-profile p.json   # validate, never run
python -m human_input_automation --verbose   # add diagnostic logging
```

`--diagnose` is the one to run when something does not work. It never sends
keyboard or mouse input; it only inspects:

```
Human Input Automation Diagnostics

OS: Linux
Display server: wayland
Window backend: x11

Capabilities:
  window_enumeration  restricted
  window_activation   unavailable
  keyboard_input      restricted
  global_hotkey       unavailable
  multi_monitor       restricted
...
Displays:
  2 monitor(s), virtual desktop 3840x1080 from (0, 0), physical coordinates
  - HDMI-2 (primary): 1920x1080 at (0, 0), scale unknown

No input was generated.
```

`--check` needs no display and no GUI extra. Exit code 0 means automation can be
attempted (possibly with restrictions), 1 means it is unavailable or a
permission is missing:

```
⚠ LIMITED: linux/wayland restricts window control; input can be sent but windows
cannot be listed or focused.

Platform: linux (wayland)
Send input: yes
Enumerate windows: no
Activate windows: no
Verify focus: no
Emergency hotkey: Wayland does not let applications observe global key presses;
use the on-screen emergency stop.
```

## The window

```
┌───────────────────────────────────────────────────────────────┐
│ ⚠ LIMITED / ✓ OK / ✗ UNAVAILABLE  capability + permission     │
├──────────────────────────┬────────────────────────────────────┤
│ TARGET                   │ ACTIONS                            │
│ [Refresh windows]        │ 1. type 'Hello' (5 chars)          │
│ Title | App | PID | Plat │ 2. press enter                     │
│ Active target: ...       │ [Add][Edit][Delete][Up][Down]      │
├──────────────────────────┼────────────────────────────────────┤
│ TIMING                   │ DRY RUN - NO INPUT WILL BE SENT    │
│ base/jitter/min/max      │ Estimated duration: 1.2 s          │
│ word/punctuation/action  │ 1. type 'Hello' ...                │
│ Next delays: 78 104 65   │ Completed 2 action(s).             │
├──────────────────────────┴────────────────────────────────────┤
│ RUN LOG   21:55:08  Run started: desktop plan, 2 action(s)    │
├───────────────────────────────────────────────────────────────┤
│ State: Running   [Start][Pause][Resume][Stop][Dry run] [3 s]   │
│ ███████████████ EMERGENCY STOP (Ctrl+.) ███████████████        │
└───────────────────────────────────────────────────────────────┘
```

While a run is in flight the target list, action editor and timing fields lock,
so the plan cannot change under a running engine. The emergency stop stays
enabled in every state, including during the countdown and while paused.

## Profiles

Profiles are JSON files in your platform's application data directory
(`%APPDATA%`, `~/Library/Application Support`, or `$XDG_DATA_HOME`), one file
per profile, written atomically.

A profile stores the plan plus a **durable identity** for its target — platform,
application id, process name and window title — never a window handle, process
id or capability snapshot, because those expire the moment the application
closes. When you load a profile the app looks for that application again and
tells you exactly what it found:

```
OK  Target resolved            Editor - Notes  (Start enabled)
!   Target not found           org.example.editor is not currently running.
!   Multiple matching windows  3 windows match. Select the intended window.
X   Required capability unavailable
```

Only a resolved target enables Start. If several windows match, the app asks —
it never picks one for you, and it never falls back to whatever window happens
to be focused. Loading, importing, validating and resolving a profile never send
input; only pressing Start does.

Profiles are pure data: there is no command, script or shell field, and unknown
action types are rejected rather than ignored. See `docs/PROFILE-FORMAT.md` for
the schema, the matching rules and the security model.

## Using the core directly

```python
from human_input_automation.application import AutomationService
from human_input_automation.core import (
    AutomationPlan, KeyPress, RunOptions, Shortcut, TimingProfile, TypeText,
)

service = AutomationService()
listing = service.discover_targets()        # .targets, plus .reason when empty
target = listing.targets[0]

plan = AutomationPlan(
    target=target,
    actions=[
        TypeText(text="Hello, world."),
        KeyPress(key="enter"),
        Shortcut.parse("ctrl+s"),
    ],
    timing=TimingProfile(char_delay_ms=70, word_pause_ms=120, punctuation_pause_ms=250),
    options=RunOptions(seed=42),            # reproducible timing
    name="demo",
)

print(service.dry_run(plan).performed)      # inspect before running for real
service.start(plan, countdown_seconds=3)    # runs on a worker thread
service.emergency_stop()                    # returns immediately, releases held keys
```

## Platform support

Capabilities are reported in five states — **available**, **restricted**,
**denied** (a permission is missing), **unavailable**, and **unknown**. Unknown
is never shown as "no".

| | Windows | macOS | Linux/X11 | Linux/Wayland |
| --- | --- | --- | --- | --- |
| Enumerate windows | available | Accessibility permission | available | restricted — XWayland (X11) clients only |
| Activate window | available | Accessibility permission | available | unavailable |
| Verify focus | available | Accessibility permission | available | unavailable |
| Synthetic input | available | Accessibility permission | available | restricted — reaches X11 clients only |
| Global stop hotkey | available | **Input Monitoring** permission | available | unavailable |
| Multi-monitor | available | restricted (logical points) | restricted (scale unreported) | restricted |

### Implemented, packaged, verified

These are different claims, and the project keeps them apart:

* **Implemented** — the code path exists and is unit tested.
* **Packaged** — a distributable artifact is produced.
* **Smoke-tested** — the artifact launches, opens its window and stores a
  profile. No input was sent.
* **Platform-verified** — real keyboard, mouse and window behaviour was
  executed on that platform by a person.

| Platform | Implemented | Packaged | Artifact built | Smoke-tested | Real input verified |
| --- | --- | --- | --- | --- | --- |
| Linux (Wayland + XWayland) | yes | yes | **yes** | **yes** | **no** |
| Linux X11 | yes | yes | yes (same artifact) | no | **no** |
| Windows | yes | yes | **no** | no | **no** |
| macOS | yes | yes | **no** | no | **no** |

Only the Linux AppImage has actually been built and run — on Ubuntu 26.04
GNOME/Wayland, where it launches, loads the real Qt platform plugin from inside
the bundle, and round-trips a profile. The Windows and macOS build
configurations exist and are reviewed but have never been executed, because no
such machine was available.

No synthetic keyboard or mouse input has been executed on **any** platform.
`docs/PHASE3-PLATFORM-REPORT.md` records exactly what was run;
`docs/RELEASE-CHECKLIST.md` is the procedure for verifying a platform you do
have.

`docs/PHASE3-PLATFORM-REPORT.md` records exactly what was run, what was found
(including two real library defects), and a manual checklist for verifying a
platform you do have.

**Supported** = the capability is modelled, wired and unit tested.
**Best effort** = implemented but not executed on that OS.
**Restricted by the OS security model** = Wayland window control and global
input, and anything on macOS before its permission is granted. Those are not
worked around.

macOS requires **two** permissions: Accessibility (for input and window
control) and Input Monitoring (for the global emergency-stop hotkey). Holding
one does not grant the other, so the app reports them separately, tells you
which settings pane grants each, and tells you a restart is needed afterwards.

### Keyboard layouts

Typing text is intended to be layout-independent; pressing a *character* key
and the final key of a shortcut are layout-dependent (they press the physical
key that produces that character on the active layout). Named keys (`enter`,
`f5`, …) are layout-independent. None of this has been verified on a non-US
layout yet — see the report, §8.

### Coordinates

Coordinates are passed to the OS unchanged; the app performs no DPI conversion.
The coordinate space is reported (`physical` on Windows/X11, `logical` on
macOS) rather than assumed, per-monitor scaling is shown as unknown when the
backend will not report it, and coordinates that land on no monitor are
rejected before a run instead of moving the pointer somewhere unexpected.
Behaviour on scaled displays (Windows 150%, macOS Retina) is unverified.

## Development

```bash
pytest                                     # 672 tests with the gui extra, 565 without
pytest -m manual                           # host-dependent checks, opt-in
ruff check .
mypy src
mypy src tests
python -m human_input_automation --check
python -m human_input_automation --diagnose
python -m human_input_automation --profiles
python -m human_input_automation --smoke-test   # starts the UI, stores a profile, no input
python packaging/build.py                       # build and verify this platform's artifact
```

Qt tests use the `offscreen` platform plugin (set automatically in
`tests/conftest.py`), so the whole suite runs headless; without PySide6 the
three Qt modules skip themselves. No test needs a real desktop, display server
or OS permission.

Tests that need a real desktop are marked (`manual`, `windows`, `macos`,
`linux`, `x11`, `wayland`) and excluded from the default run.

See `docs/ARCHITECTURE.md` for the layering, the Qt threading rule and the
design decisions, `packaging/README.md` for how the packages are built,
`docs/RELEASE-CHECKLIST.md` for the manual verification procedure,
`CHANGELOG.md` for release notes, `docs/PROFILE-FORMAT.md` for the profile schema,
`docs/PHASE3-PLATFORM-REPORT.md` for what has actually been verified on real
hardware, and `docs/ROADMAP.md` for what comes next.
