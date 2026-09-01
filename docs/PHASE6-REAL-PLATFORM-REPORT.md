# Phase 6 — Real-platform verification report

What was **executed**, on what, and what remains unverified. Nothing here is
inferred: every PASS corresponds to a check that ran and was observed.

Last updated: 2026-09-02. Application version 0.7.0.

## 1. Vocabulary

| Term | Means |
| --- | --- |
| **Implemented** | The code path exists and is unit tested against fakes. |
| **Packaged** | A distributable artifact is produced. |
| **Smoke-tested** | The artifact launches, opens its window and stores a profile. No input sent. |
| **Real-platform-verified** | Real keyboard/mouse/window behaviour was executed and observed on that platform. |

Fake adapters are never evidence of real OS behaviour. A passing unit test says
our logic is right; only this report says the operating system agreed.

## 2. What was actually tested

One configuration was exercised with real input:

| | |
| --- | --- |
| Host | Ubuntu 26.04 LTS, kernel 7.0.0-30-generic, x86_64 |
| Display server | **X11** — `Xvfb` 21.1.24, private display `:99`, 1920×1080 |
| Window manager | `tools/platform_verify/mini_wm.py` — a ~150-line EWMH window manager written for this harness |
| Desktop environment | none (bare X server) |
| Keyboard layout | X server default (US QWERTY) |
| Monitors | 1 (a second, 2-monitor host display was used for the geometry checks) |
| Python | 3.14.6 |
| Backends | pynput 1.8.2 (`_xorg`), python-xlib 0.33, PySide6 6.11.2, pywinctl 0.4.1, pymonctl 0.92 |
| Harness | `tools/platform_verify/run_x11_session.sh` |
| Result | **51 checks, 51 passed, 0 failed** |

**This is an isolated X server with a purpose-built window manager, not a
desktop session.** It proves the adapters work against a real X server, real
XTEST input and real EWMH window management. It is *not* evidence about GNOME,
KDE, i3, or any real-world window manager, and it says nothing at all about
Windows or macOS.

The user's own GNOME/Wayland session was **not** used as a target: injecting
input into a live desktop could type into whatever window happened to hold
focus.

## 3. Platform matrix

| Platform | OS version | Arch | Window enum | Activation | Keyboard | Mouse | Hotkey | Emergency stop | Scaling | Profiles |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Linux X11 (Xvfb + mini EWMH WM)** | Ubuntu 26.04 | x86_64 | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** | PARTIAL | **PASS** |
| Linux X11 (real desktop session) | — | — | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED |
| Linux Wayland (GNOME) | Ubuntu 26.04 | x86_64 | RESTRICTED (XWayland only) | NOT APPLICABLE | NOT TESTED | NOT TESTED | NOT APPLICABLE | NOT TESTED | PASS (read-only) | NOT TESTED |
| Windows | — | — | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED |
| macOS | — | — | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED |

"Scaling: PARTIAL" — multi-monitor layout and coordinate validation were
verified against two real monitors, but no display with a non-100% scale factor
was available. X11 reports no per-monitor scale, so the application reports it
as unknown.

## 4. Real-input results (Linux X11, isolated)

Every line below was executed and observed.

### Keyboard
* Literal text arrived intact: sent `AUTOMATION_TEST`, target received `AUTOMATION_TEST`.
* Named keys arrived as keys, not text: `enter`, `tab`, `left`, `backspace`,
  `home`, `page_down` each produced the expected Qt key code.
* `ctrl+a` arrived **with the modifier applied** (`Key_A` with `ControlModifier`),
  not as two separate keystrokes.

### Mouse
* Absolute movement landed exactly: asked (600, 400), ended (600, 400).
* Duration honoured: asked 400 ms, measured 401 ms — movement is interpolated,
  not a teleport.
* Click arrived: `mouse_press` and `mouse_release` recorded inside the target,
  preceded by ~50 interpolated `mouse_move` events.

### Activation — the critical test
1. Target and decoy windows, placed apart, with **different** application
   identities.
2. Decoy focused.
3. Run started against the target.

Result: **the target received `TARGET_ONLY`; the decoy received nothing.**

### Emergency stop
| Scenario | Result |
| --- | --- |
| During a 60 s wait | Stopped in **1 ms**; no further action ran |
| While a modifier was held | Press and release balanced; typing afterwards produced `after`, not `AFTER` — the key was genuinely released |
| While a mouse button was held | Reported `emergency_stopped`, button released |
| While paused | Stopped safely |
| Global hotkey during a run | Stopped in **195 ms** |
| Global hotkey while idle | Did **not** start anything |

### Timing
Configured 60–200 ms per character (seed 7); **measured 96–132 ms** across the
gaps between keystrokes as received by the target. Seeded timing reproduced
identical delays across services.

### Safety gates (every row produced **zero input**)
| Condition | Result |
| --- | --- |
| Target missing | Run FAILED, no input |
| Target capability blocked | Run INVALID, no input |
| Dry run | Completed, 0 events reached the target |
| Profile unresolved (absent application) | `TARGET_UNRESOLVED`, no plan produced |
| Activation failure | Run FAILED, no input |

### Profiles
Saved → new service with fresh adapters (a restart) → reloaded → re-resolved by
application identity → ran, and its input arrived. A profile whose saved handle
was replaced with `0xdeadbeef` still resolved *through the application
identity*; a profile naming an absent application did not resolve.

### Adapter lifecycle
Repeated enumeration stable, geometry re-readable, **no threads leaked** across
a build → use → close cycle, adapters rebuildable afterwards.

## 5. Bugs found and fixed

All three were found by running the real adapters. None was visible to the
fake-based suite, and each now has regression tests.

### 5.1 Window activation reported false failures (X11)

* **Symptom** — `could not activate target window` for a window that was
  activated successfully moments later.
* **Root cause** — activation is a *request* to the window manager, which acts
  asynchronously. The adapter read `_NET_ACTIVE_WINDOW` immediately afterwards
  and saw the previous focus.
* **Fix** — `X11Windows.activate` now waits, bounded (1 s, 20 ms polls), for the
  window manager to honour the request. Unverifiable focus is still treated as
  "unknown", and a window manager that ignores the request still reports failure.
* **Regression tests** — `test_x11_windows.py`: a window manager that lags,
  one that never honours the request, and one that cannot verify focus.

### 5.2 Screen geometry described the wrong display

* **Symptom** — with `DISPLAY` pointing at a 1024×768 X server, the application
  reported **seven** monitors and a 3840×1080 desktop.
* **Root cause** — `pymonctl.getAllMonitors()` returned the real monitor three
  times *plus the two monitors of a different display twice each*. Coordinate
  validation would then have accepted points that are nowhere on screen.
* **Fix** — a new `adapters/x11_screens.py` reads RandR directly, which is
  authoritative for the display actually connected to, with the X screen size as
  a pre-RandR fallback; Linux now uses it. `PyMonCtlScreens` (still used on
  Windows and macOS) deduplicates identical monitors.
* **Verified after the fix** — isolated display reports 1 monitor 1024×768;
  the host display reports HDMI-2 (primary) + DP-1 at (1920, 0).
* **Regression tests** — `test_x11_screens.py` (9 tests), plus a duplicate-monitor
  test for pymonctl.

### 5.3 The default global hotkey could never fire

* **Symptom** — the UI reported "Global emergency-stop hotkey active", and the
  hotkey did nothing.
* **Root cause** — measured against a real X server, pynput's `GlobalHotKeys`
  never fires for two shapes, and the old default `Ctrl+Alt+.` was **both**:

  | Combination | Fires |
  | --- | --- |
  | `<f9>`, `<ctrl>+<f9>`, `<alt>+<f9>`, `<shift>+<f9>` | yes |
  | `<ctrl>+<shift>+<f9>`, `<ctrl>+<shift>+<f10>` | yes |
  | `<ctrl>+<alt>+<f9>`, `<ctrl>+<alt>+<f10>`, `<ctrl>+<alt>+.` | **no** |
  | `<ctrl>+.`, `<ctrl>+<alt>+q` | **no** |

  Ctrl and Alt held together never matched, and character keys did not match
  once any modifier was held.
* **Fix** — the default is now `Ctrl+Shift+F9` (measured to fire);
  `problematic_combination()` warns about both known-bad shapes; and
  `PynputHotkey.start()` now calls `listener.wait()`, so a backend that fails
  asynchronously is reported as *not* registered instead of appearing active.
* **Verified after the fix** — the hotkey stopped a running plan in 195 ms and
  did not start anything when pressed while idle.
* **Regression tests** — `test_hotkeys.py`: the default is clean, and both bad
  shapes plus five verified-good shapes are asserted.

## 6. Third-party behaviour worth knowing

| Library | Confirmed behaviour | Consequence |
| --- | --- | --- |
| pynput 1.8.2 | Loads its **X11** backend inside a Wayland session whenever `DISPLAY` is set | Input reaches XWayland clients only; reported as *restricted*, not available |
| pynput 1.8.2 | `GlobalHotKeys` does not match Ctrl+Alt combinations or character keys (X11) | Default hotkey changed; bad shapes warned about |
| pynput 1.8.2 | `Controller.press("enter")` raises `ValueError` — only single characters are accepted as strings | All named keys are translated in `adapters/keymap.py` |
| pynput 1.8.2 | The macOS backend has no `Key.insert` | Rejected by validation before a run starts |
| pywinctl 0.4.1 | `getAllWindows()` raises `KeyError: 'id'` on Ubuntu GNOME; `getActiveWindow()` returns a phantom 1×1 window | Not used on Linux; every call wrapped |
| pymonctl 0.92 | Returns duplicated monitors, and monitors belonging to another display | Replaced by RandR on Linux; deduplicated elsewhere |
| python-xlib 0.33 | RandR `get_monitors` is accurate on both a bare Xvfb and a real 2-monitor display | Used as the Linux geometry source |
| Qt 6.11.2 | Delivers one key event to the focus widget and each parent | Harness-side only: deduplicate on the event timestamp |

## 7. What remains unverified

* **Windows and macOS: nothing has been executed.** Not the packaged artifact,
  not the adapters, not the permission flow. Their build jobs have never run.
* **A real X11 desktop session** (GNOME/KDE/i3 on X11) — only a bare Xvfb with
  a purpose-built window manager was available.
* **Wayland**: capability reporting and read-only enumeration were exercised;
  no input was ever injected into the live session.
* **Non-US keyboard layouts** — untested on every platform.
* **Display scaling** other than 100%; macOS Retina point-vs-pixel behaviour.
* **Windows display scaling** and per-monitor DPI.
* macOS Accessibility / Input Monitoring: the model is implemented and unit
  tested, but no permission has ever actually been granted or denied.

## 8. Reproducing this

```bash
conda create -p ./xenv -c conda-forge xorg-xvfb-server    # or apt install xvfb
pip install -e ".[dev,desktop]"
PATH="./xenv/bin:$PATH" tools/platform_verify/run_x11_session.sh /tmp/verify python
```

The same harness runs in CI (`verify-x11` job), so this configuration is
re-verified on every push. Windows, macOS and real desktop sessions remain the
manual checklist in `docs/RELEASE-CHECKLIST.md`.
