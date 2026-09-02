# Guide: running, using and deploying

A practical walkthrough. For the architecture see `docs/ARCHITECTURE.md`; for
what has actually been verified on which platform, see the reports listed at the
end.

---

## 1. Run it

### From source (any platform)

```bash
git clone <repository>
cd human-input-automation

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev,desktop]"    # everything, including real input

human-input-automation             # the desktop application
```

**Note the two spellings.** The package installs as `human-input-automation`
(hyphens) and that is also the command. The *module* name uses underscores, so
if you prefer `python -m` it is:

```bash
python -m human_input_automation   # underscores, not hyphens
```

`python -m human-input-automation` fails with `No module named
human-input-automation`; use the command above instead.

On macOS, if the command is not found or Python reports the module missing,
check you are on the virtual environment's interpreter:

```bash
which python && python -c "import sys; print(sys.prefix)"
# both should point inside .venv; if not, run: hash -r && source .venv/bin/activate
```

Extras, if you want less than everything:

| Extra | Gives you |
| --- | --- |
| *(none)* | The core and the CLI. No desktop libraries at all. |
| `gui` | PySide6 — the window. |
| `input` | pynput — real keyboard and mouse. |
| `windows` | pywinctl — window control on Windows/macOS. |
| `x11` | python-xlib — window control on Linux. |
| `desktop` | All four. |
| `dev` | pytest, ruff, mypy. |

### Check the machine first

Before anything else, ask the application what this computer allows:

```bash
human-input-automation --diagnose
```

It sends no input; it only inspects. Read the capability list before wondering
why something does not work — most "it doesn't type" questions are answered
there.

Other headless commands: `--check` (short summary), `--profiles` (list saved
profiles), `--validate-profile FILE`, `--version`, `--verbose`.

### From a packaged build

| Platform | File | Install |
| --- | --- | --- |
| Linux | `…-linux-x86_64.AppImage` | `chmod +x` and run |
| Windows | `…-windows-x64-setup.exe` | Run it; per-user, no admin rights |
| macOS | `…-macos-arm64.dmg` | Open, drag to Applications |

Verify the download first: `sha256sum -c SHA256SUMS`.

---

## 2. Use it

1. **Read the banner.** The strip at the top says what this machine allows.
   `OK` means everything works; `LIMITED` means something is restricted and the
   detail line says what; `DENIED` means a permission is missing.
2. **Pick a target.** *Refresh windows*, then click the window you want to
   automate. The bold line underneath always shows the current target. There is
   no "just use whatever is focused" mode — that is deliberate.
3. **Build the plan.** *Add* actions: type text, key presses, shortcuts, mouse
   moves and clicks, waits. Each action can override the delay that follows it.
4. **Set the timing.** Base delay and jitter, plus word and punctuation pauses.
   The preview shows the delays your settings actually produce. Tick *Use fixed
   seed* to make a run reproducible.
5. **Dry run first.** Always. It reports every action and the estimated duration
   and sends nothing at all.
6. **Start.** A countdown runs first (3 s by default) so you can get out of the
   way; the target is activated only after it finishes. The window minimises
   during the run, leaving a small always-on-top **EMERGENCY STOP** on screen,
   and comes back when the run ends. Untick *Minimise while running* if you
   would rather it stayed.
7. **Stopping.** The emergency stop is always available — on the main window, on
   the overlay, or with `Ctrl+.`. Where the platform allows it, `Ctrl+Shift+F9`
   works as a global hotkey even when the application is not focused. Stopping
   is immediate and always releases any keys or mouse buttons being held.

### Profiles

*Save As* stores the plan and the target's **identity** — the application, not a
window handle — so it still finds the right window after either program
restarts. On load you get one of:

```
OK  Target resolved             Editor — ready to run
!   Target not found            that application is not running
!   Multiple matching windows   pick which one you meant
X   Required capability unavailable
```

Only a resolved target enables Start. If several windows match, the application
asks; it never picks for you and never falls back to the focused window.
Profiles are plain JSON in your user directory (`docs/PROFILE-FORMAT.md`), and
contain no commands or scripts — they cannot execute anything.

---

## 3. Platform notes

Read this before concluding something is broken.

### Linux — Wayland (Ubuntu's default)

Wayland deliberately stops applications from driving other windows. With
XWayland running — which it usually is — the position is mixed, and the
application reports it honestly:

| | Works? |
| --- | --- |
| Listing windows | X11/XWayland applications only. Wayland-native windows are invisible. |
| Focusing a window | **Yes**, for X11/XWayland windows. Measured on GNOME/Wayland. |
| Typing | **Yes**, into the focused X11 window. |
| Mouse move and click | **No.** The compositor ignores requests to move the pointer, so a click cannot be aimed. Plans containing clicks are refused rather than fired blindly. |
| Global hotkey | No. Use the on-screen emergency stop. |

Practical consequence: on Wayland you can automate **keyboard** input into
XWayland applications (VS Code, most Electron apps, anything started with
`QT_QPA_PLATFORM=xcb` or `GDK_BACKEND=x11`) and you cannot automate the mouse.
For full functionality, log into an **X11 session** ("Ubuntu on Xorg" on the
login screen).

### Linux — X11

Everything works: enumeration, activation, focus verification, keyboard, mouse,
global hotkey. This is the best-supported configuration and the one covered by
automated verification on every push.

### Windows

Implemented but **not yet verified on real hardware**. Expect window handles and
input to work; note that Windows restricts which process may take the
foreground, so activation can legitimately fail — in which case the run stops
and nothing is typed.

### macOS

Implemented but **not yet verified on real hardware**. macOS needs **three**
separate permissions, and the application names each one:

| Permission | Unlocks | Granted in |
| --- | --- | --- |
| Accessibility | keyboard and mouse input | Privacy & Security → Accessibility |
| Automation (System Events) | listing, focusing and checking windows | Privacy & Security → Automation |
| Input Monitoring | the global emergency hotkey | Privacy & Security → Input Monitoring |

Granting one does not grant the others, and macOS usually needs the application
quit and reopened afterwards.

---

## 4. Troubleshooting

**"Unable to activate the selected window."**
The run stopped before typing anything — that is the safety gate working. On
Wayland, check the target is an XWayland application (native Wayland windows
cannot be focused by us). Elsewhere, refresh the window list: the window may
have closed or been replaced.

**"the target window cannot be focused programmatically" / "focus cannot be
verified on this platform"**
Warnings from the capability model. If they appear on Wayland with a
Wayland-native target, that target cannot be automated; pick an XWayland window
or switch to an X11 session.

**A click is refused with "cannot be performed on this system"**
Wayland ignores pointer warping. Keyboard actions still run; remove the mouse
actions or switch to X11.

**Nothing appears in the window list**
`--diagnose` will say why: a Wayland session without XWayland, a missing macOS
Automation permission, or an unavailable adapter.

**The global hotkey does nothing**
Unavailable on Wayland, and on macOS it needs Input Monitoring. The on-screen
emergency stop always works.

**Where are the logs?**

| Platform | Location |
| --- | --- |
| Linux | `~/.local/state/human-input-automation/logs/` |
| macOS | `~/Library/Logs/human-input-automation/` |
| Windows | `%APPDATA%\human-input-automation\logs\` |

Typed text is redacted from logs on purpose. Run with `--verbose` for detail.

---

## 5. Verify a machine

The harness runs the real adapters against its own throwaway window — it never
types into your applications.

```bash
# Any desktop session (Windows, macOS, Linux). Generates real input.
python tools/platform_verify/run_desktop_session.py --confirm

# Linux with an isolated X server; cannot touch your desktop at all.
tools/platform_verify/run_x11_session.sh /tmp/verify python
```

About 50 checks: typing, named keys, shortcuts, mouse, activation with a decoy
window focused, emergency stop, timing bounds, profile re-resolution. Results
land in `report.json`. Without `--confirm` only the checks that send no input
run. See `tools/platform_verify/README.md`.

---

## 6. Deploy

### Build the artifact for this platform

```bash
pip install -e ".[dev,desktop]" pyinstaller
python packaging/build.py
```

That runs PyInstaller, **verifies the result by running it** (`--smoke-test`
opens the real window and round-trips a profile without sending input), then
produces the platform artifact and `SHA256SUMS` in `dist/`.

| Platform | Produces | Extra tool |
| --- | --- | --- |
| Linux | `.AppImage` (else `.zip`) | `appimagetool` on `PATH` |
| Windows | app directory + `.zip`; installer via `iscc packaging\windows\installer.iss` | Inno Setup |
| macOS | `.app` inside a `.dmg` | `hdiutil` (built in) |

### Release

```bash
git tag v0.8.0
git push origin v0.8.0
```

The workflow runs the tests on all three platforms, builds on **native
runners**, verifies each artifact, and opens a **draft** release with checksums.
Review the draft — in particular whether macOS signing ran — before publishing.
`docs/RELEASE-CHECKLIST.md` is the pre-flight list.

### Signing

* **Windows** — unsigned; SmartScreen will warn. Add a certificate to the
  workflow when you have one.
* **macOS** — `packaging/macos/sign_and_notarize.sh` signs and notarises **only**
  when credentials are present in the environment; otherwise the build is
  produced unsigned and labelled as such. Credentials come from CI secrets,
  never from the repository.

### Where user data lives

Profiles and logs are stored in the per-user directory, never inside the
installation, and uninstalling does not remove them.

---

## Further reading

| Document | Contents |
| --- | --- |
| `docs/ARCHITECTURE.md` | Layering, the Qt threading rule, design decisions |
| `docs/PROFILE-FORMAT.md` | Profile schema, target identity, security model |
| `docs/PHASE6-REAL-PLATFORM-REPORT.md` | What was executed on Linux, and the bugs it found |
| `docs/PHASE7-WINDOWS-REPORT.md` | Windows: audit findings, everything still untested |
| `docs/PHASE7-MACOS-REPORT.md` | macOS: the three-permission model and untested items |
| `docs/RELEASE-CHECKLIST.md` | Manual verification before a release |
| `packaging/README.md` | Build environment and packaging layout |
