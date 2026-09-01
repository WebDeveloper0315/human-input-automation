# Phase 3 — Platform verification report

This document records what was **actually executed**, on what, and what was
not. It is deliberately conservative: a capability is only marked `PASS` if a
test was run and observed. Everything else is `NOT TESTED`, `RESTRICTED` or
`UNKNOWN`.

Last updated: 2026-09-01.

## 1. Test environment

Only one machine was available for this phase.

| | |
| --- | --- |
| OS | Ubuntu 26.04 LTS, kernel 7.0.0-30-generic |
| Desktop | GNOME (`XDG_CURRENT_DESKTOP=ubuntu:GNOME`) |
| Session | **Wayland** (`XDG_SESSION_TYPE=wayland`, `WAYLAND_DISPLAY=wayland-0`) |
| XWayland | present (`DISPLAY=:0`) |
| Displays | 2 × 1920×1080 — HDMI-2 at (0,0), DP-1 at (1920,0) |
| Python | 3.14.6 |
| Libraries | pynput 1.8.2, pywinctl 0.4.1, pymonctl 0.92, python-xlib 0.33, PySide6 6.11.2 |

**No Windows, macOS or native X11 session was available.** Nothing in this
document claims otherwise.

### A deliberate limitation: no input was injected

Synthetic keyboard and mouse input was **not** sent on this machine. The only
session available is the user's live desktop, and injecting keystrokes or moving
the pointer there would type into whatever real window happened to hold focus.
Every check below is read-only: enumerate, resolve, read position, inspect
library internals.

Consequently **no end-to-end "input arrived in the target application" test has
been executed on any platform.** Section 7 gives the manual procedure for
someone with a suitable machine.

## 2. Evidence classes

Findings are labelled by how they were established:

* **E — Executed** on the machine above.
* **S — Source-verified**: read from the installed library's own code, so it
  holds for that version on every platform it ships.
* **F — Fake-verified**: covered by automated tests against injected fake
  platform modules; proves our logic, not the platform's behaviour.
* **A — Assumed** from documentation. Not verified. Treated as unknown.

## 3. Capability matrix

| Capability | Windows | macOS | Ubuntu X11 | Ubuntu Wayland |
| --- | --- | --- | --- | --- |
| Window enumeration | NOT TESTED | NOT TESTED | NOT TESTED | **RESTRICTED (E)** — XWayland clients only |
| Window activation | NOT TESTED | NOT TESTED | NOT TESTED | **RESTRICTED (E)** — refused by design |
| Focus verification | NOT TESTED | NOT TESTED | NOT TESTED | **PARTIAL (E)** — `_NET_ACTIVE_WINDOW` readable for X11 clients |
| Keyboard input | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED (no injection performed) |
| Mouse movement | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED (no injection performed) |
| Mouse click | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED (no injection performed) |
| Key down/up | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED (no injection performed) |
| Global emergency hotkey | NOT TESTED | NOT TESTED | NOT TESTED | **UNAVAILABLE (E)** — reported, not attempted |
| Process information | NOT TESTED | NOT TESTED | NOT TESTED | **PASS (E)** — PIDs and WM_CLASS read for X11 clients |
| Multi-monitor coordinates | NOT TESTED | NOT TESTED | NOT TESTED | **PASS (E)** — 2-monitor layout read correctly |
| Key-name translation | **PASS (S)** | **PASS (S)** | **PASS (E)** | **PASS (E)** |
| Backend absence handling | **PASS (F)** | **PASS (F)** | **PASS (F)** | **PASS (E)** |

What the application *reports* for each platform is a separate matter and is
fully unit tested — see `tests/test_platform_info.py`. That is the capability
model, not evidence that the platform behaves as modelled.

## 4. Findings from actual execution

### 4.1 pywinctl is broken on Ubuntu 26.04 GNOME (E)

```
>>> pywinctl.getAllWindows()
  File ".../pywinctl/_pywinctl_linux.py", line 117, in getAllWindows
    windows = [str(win["id"]) for win in windowsList]
KeyError: 'id'
```

It raises rather than returning an empty list, and `getActiveWindow()` returns a
phantom window (`left=-100, top=-100, width=1, height=1, title=None`).

**Consequences applied:** every pywinctl call is now wrapped so a failure
becomes an empty result or `False`/`None`, never an exception reaching the
engine or UI; and Linux no longer uses pywinctl for windows at all — a new
EWMH adapter (`adapters/x11_windows.py`) is selected instead. pywinctl remains
the Windows/macOS window backend, where it is untested by us.

### 4.2 pynput silently uses its X11 backend inside a Wayland session (E)

```
keyboard module: pynput.keyboard._xorg
mouse module:    pynput.mouse._xorg
```

So on a Wayland desktop pynput does not fail loudly — it quietly targets
XWayland. Input can therefore reach X11 clients and silently do nothing for
native Wayland windows. This is why the capability matrix reports Wayland +
XWayland as **restricted** rather than available or unavailable.

### 4.3 The X11/EWMH adapter works here (E)

Run against the live X server, read-only:

```
enumerated 2 window(s):
    0x01800004 | code | pid 7446 | screen.py - human-input-automation - Visual Studio Code
    0x01800024 | code | pid 7446 | backend.env.example - CompanyInOutManagement - ...
active handle: 0x01800004
find(handle) round-trip: True
activate(...): False        # refused: capability matrix says Wayland cannot activate
```

Both listed windows are XWayland (X11) clients. Native Wayland windows — the
GNOME shell, Wayland-native apps — are invisible to `_NET_CLIENT_LIST`, exactly
as expected. Titles, PIDs and WM_CLASS values were correct.

### 4.4 Multi-monitor geometry is readable; scaling is not (E)

```
HDMI-2: pos=(0,0)    size=1920x1080  scale=None  dpi=(92, 91)
DP-1:   pos=(1920,0) size=1920x1080  scale=None  dpi=(102,102)
```

Virtual desktop: 3840×1080 in physical pixels. `scale` is `None`, so per-monitor
scaling is reported as **unknown** rather than assumed to be 1.0.

### 4.5 Named keys must be translated before pynput sees them (S, E)

`pynput.keyboard.Controller._resolve` (pynput 1.8.2, `_base.py`):

```python
if isinstance(key, six.string_types):
    if len(key) != 1:
        raise ValueError(key)
```

Confirmed at runtime: `_resolve("enter")` raises `ValueError: enter`;
`_resolve("a")` returns a `KeyCode`. Passing a key *name* straight to pynput is
therefore an error, not merely wrong behaviour. (The Phase 1 audit described
this as producing a bad multi-character `KeyCode`; the actual mechanism is a
`ValueError`. The conclusion — a translation layer is required — is unchanged.)

All 32 of our `Key` members resolve on the X11 backend (E).

### 4.6 pynput's key table differs per platform (S)

Extracted from the installed backends' `Key` enums:

| Backend | Members | Missing relative to the union |
| --- | --- | --- |
| `_win32` | 65 | `media_eject` |
| `_darwin` | 55 | `insert`, `menu`, `num_lock`, `pause`, `print_screen`, `scroll_lock`, `f21`–`f24`, `media_stop` |
| `_xorg` | 60 | `f21`–`f24`, `media_eject`, `media_stop` |

Of the keys this application exposes, exactly one is affected: **`Key.INSERT`
cannot be sent on macOS.** It is now reported as a platform key gap on the host
report and rejected by validation *before* a run starts, instead of raising
part-way through a plan.

Mouse buttons: `left`, `right` and `middle` exist on all three backends (S);
the X11 backend generates its `Button` enum dynamically and also exposes
scroll and extended buttons (E).

## 5. What changed as a result

| Change | Driven by |
| --- | --- |
| `adapters/x11_windows.py` (EWMH) added and selected on Linux | 4.1, 4.3 |
| Every pywinctl call wrapped; failures become data | 4.1 |
| Capability matrix with available/restricted/denied/unknown/unavailable | 4.2 |
| Wayland+XWayland modelled as *restricted*, not unavailable | 4.2, 4.3 |
| `adapters/keymap.py`: single translation point, per-platform key gaps | 4.5, 4.6 |
| Validation rejects platform-unsupported keys before a run | 4.6 |
| Screen geometry, coordinate space, off-screen coordinate validation | 4.4 |
| Scaling reported as unknown rather than assumed | 4.4 |
| Mid-run focus re-verification (stop rather than redirect) | safety review |
| Movement interpolation is deadline-based and interruptible | §10 of the brief |
| `--diagnose` read-only report | §15 of the brief |

## 6. Emergency-stop latency

The emergency stop sets a `threading.Event`; every wait in the engine is an
`Event.wait`, so pending delays end immediately. Two bounded exceptions:

1. **Mouse movement.** `PynputMouse.move_to` interpolates in ~8 ms steps and
   checks the cancel token between them, and the sleep between steps is itself
   interruptible. Worst case ≈ one step (~8 ms) plus one position write.
2. **`type_text` with a zero-delay timing profile.** The whole string is handed
   to pynput in one call, which cannot be interrupted. Worst case is the time
   the OS takes to deliver that string. Any non-zero per-character delay makes
   typing interruptible between characters.

Neither is zero. Both are documented rather than glossed over.

## 7. Manual verification procedure (not yet executed)

For each platform, on a machine you are willing to have typed into. Use a
scratch text editor as the target — never a terminal or anything destructive.

```bash
pip install -e ".[dev,desktop]"
python -m human_input_automation --diagnose     # expect a matrix with no surprises
python -m human_input_automation                # the GUI
```

1. **Discovery** — press *Refresh windows*. Confirm at least three different
   applications appear (e.g. a text editor, a browser, a terminal) with correct
   titles, application names and PIDs.
2. **Activation (the critical test)** — select target A, then manually focus a
   *different* window B, then Start with a 3 s countdown and a
   `Type text: "hello"` action. **The text must appear in A, and nothing must
   appear in B.** If A cannot be activated, the run must fail with
   "Unable to activate the selected window" and type nothing anywhere.
3. **Focus loss** — start a plan with a 10 s wait followed by typing, then click
   another window during the wait. The run must fail with "no longer focused"
   and must not type into the window you switched to.
4. **Keyboard** — verify: lowercase, uppercase, digits, punctuation, `enter`,
   `tab`, `esc`, `backspace`, arrows, `key down`/`key up` of `shift`, and the
   shortcuts `ctrl+c`, `ctrl+v`, `ctrl+shift+p`. On macOS additionally check
   that `cmd` is Command and *not* Ctrl (`cmd+a` must select all).
5. **Keyboard layouts** — repeat step 4 with a non-US layout (German QWERTZ or
   French AZERTY). Record which of `TypeText`, `KeyPress` and `Shortcut` behave
   as expected; see §8 below for what is guaranteed.
6. **Mouse** — absolute move to a known point, movement duration (set 2000 ms
   and confirm it visibly takes ~2 s), left/right/middle click, and
   down/up drag.
7. **Multi-monitor** — move to a point on a secondary monitor, including one
   positioned left of or above the primary (negative coordinates). Confirm an
   off-desktop coordinate is rejected by validation rather than moving somewhere
   unexpected.
8. **Display scaling** — repeat on a display with non-100% scaling (Windows
   150%, macOS Retina). Record whether the coordinates behave as physical or
   logical pixels.
9. **Emergency stop** — trigger it during the countdown, during a long wait,
   during a long movement, and while paused. Confirm held keys are released.
10. **Global hotkey** — press `Ctrl+Alt+.` during a run. On macOS confirm the
    Input Monitoring prompt appears and that the hotkey works only after it is
    granted *and* the app is restarted.

Record results in the matrix in §3, using PASS / FAIL / PARTIAL / RESTRICTED /
UNKNOWN / NOT TESTED. Do not mark PASS for a step you did not run.

## 8. Keyboard layout guarantees

Not verified on any non-US layout. What the design guarantees, and what it does
not:

| Path | Behaviour | Layout dependence |
| --- | --- | --- |
| `TypeText` | `pynput.Controller.type()` — types characters | Intended to be layout-independent; on X11 pynput remaps unmapped characters onto a spare keycode. **Unverified here.** |
| `KeyPress`/`KeyDown`/`KeyUp` with a single character | `KeyCode.from_char` | Layout-dependent: it presses the *physical key* that produces that character on the active layout. |
| `KeyPress` with a named key (`enter`, `f5`, …) | Backend `Key` member | Layout-independent. |
| `Shortcut` (`ctrl+shift+p`) | Modifiers held, final key tapped | The modifier part is layout-independent; the final character key is layout-dependent (e.g. `ctrl+z` lands on a different physical key under AZERTY). |

Until step 5 of §7 has been run, the application should not be described as
layout-independent.

## 9. Coordinate system

* The application passes coordinates through unchanged to pynput. It does no
  DPI conversion of its own.
* The coordinate space is *reported*, never assumed: `physical` on Windows and
  X11, `logical` on macOS, `unknown` elsewhere (`core/screen.py`).
* Per-monitor scale is `None` (unknown) on this machine's X11 backend, and is
  displayed as "scale unknown".
* Validation rejects absolute coordinates that fall on no monitor, including
  the gap between two non-adjacent monitors, and accepts negative coordinates
  for monitors left of or above the primary.
* **Untested:** Windows display scaling, macOS Retina point-vs-pixel behaviour.
  Until step 8 of §7 has been run, treat coordinates on scaled displays as
  unverified.

## 10. Summary

* One platform configuration was exercised: Ubuntu 26.04 GNOME **Wayland** with
  XWayland — read-only.
* Two real library defects were found and worked around (pywinctl crash,
  pynput's silent X11 fallback), plus one real platform key gap
  (`Key.INSERT` on macOS).
* No synthetic input was sent anywhere, so no "input reached the target"
  claim is made for any platform.
* Windows, macOS and native X11 remain **NOT TESTED**.
