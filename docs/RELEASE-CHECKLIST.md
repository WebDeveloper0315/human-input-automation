# Release checklist

Two halves: what CI proves automatically, and what a person must still do on a
real machine. The second half is the one that matters — packaging makes
verification *possible*, it does not perform it.

## Vocabulary

Used throughout the documentation, and never collapsed into "supported":

| Term | Means |
| --- | --- |
| **Implemented** | The code path exists and is unit tested. |
| **Packaged** | A distributable artifact is produced for that platform. |
| **Smoke-tested** | The artifact launches, opens its window and stores a profile. No input was sent. |
| **Platform-verified** | Real keyboard, mouse and window behaviour was executed on that platform by a person. |

## Automated verification first

Before any manual testing, run the harness - it covers a large part of the
checklist automatically and needs no desktop session:

```bash
# Linux, isolated X server (needs Xvfb; cannot touch your desktop)
tools/platform_verify/run_x11_session.sh /tmp/verify python

# Windows, macOS, or a Linux desktop session (generates real input on it)
python tools/platform_verify/run_desktop_session.py --confirm
```

51 checks including real typing, activation against a decoy window, emergency
stop and profile re-resolution. It runs on an isolated X server, so it cannot
touch your desktop. See `tools/platform_verify/README.md`. The manual checklist
below still matters: the harness uses a minimal window manager, and says nothing
about Windows, macOS or a real desktop session.

## Before tagging

- [ ] `pytest`, `ruff check .`, `mypy src`, `mypy src tests` all pass
- [ ] `python -m human_input_automation --check` and `--diagnose` work headless
- [ ] `python -m build` produces a wheel containing `py.typed` and the icons
- [ ] `CHANGELOG.md` has an entry for the version, including known limitations
- [ ] The version in `pyproject.toml` matches `__init__.py` (a test enforces this)
- [ ] `python packaging/build.py` succeeds locally on at least one platform
- [ ] `tools/platform_verify/run_x11_session.sh` reports 0 failures

## Tagging

```bash
git tag v0.6.0
git push origin v0.6.0
```

The release workflow runs tests on all three platforms, builds on native
runners, verifies each artifact, and opens a **draft** release. Review the
draft — in particular whether macOS signing actually ran — before publishing.

## Getting the artifacts for manual verification

From the draft release or the workflow's artifacts:

| Platform | File | Install |
| --- | --- | --- |
| Windows | `HumanInputAutomation-<version>-windows-x64-setup.exe` | Run it. Per-user; no administrator rights. |
| Windows | `…-windows-x64.zip` | Unzip and run `HumanInputAutomation.exe`. |
| macOS | `…-macos-arm64.dmg` | Open, drag to Applications. Unsigned builds need right-click → Open. |
| Linux | `…-linux-x86_64.AppImage` | `chmod +x` and run. |

Verify the download first:

```bash
sha256sum -c SHA256SUMS
```

## Safe verification profile

**Always start with a dry run.** Only then send real input, and only into a
scratch text editor — never a terminal, a browser form, a messaging app, or
anything that can act on what is typed.

The verification plan is deliberately harmless:

```
1. Type text   "AUTOMATION_TEST"
2. Key press   enter
3. Type text   "second line"
4. Mouse move  to a point inside the editor window
5. Mouse click left
6. Wait        2000 ms
```

Never build a verification profile that deletes files, runs commands, submits a
form, sends a message, buys anything or changes a system setting. Profiles
cannot execute commands by design — keep the manual tests just as harmless.

## Per-platform checklist

Record every result as PASS / FAIL / PARTIAL / NOT TESTED in
`docs/PHASE3-PLATFORM-REPORT.md`. **Do not mark PASS for a step you did not
run.**

### Windows 10/11

- [ ] Installer runs without an administrator prompt
- [ ] Start Menu shortcut launches the application
- [ ] Optional desktop shortcut works
- [ ] `HumanInputAutomation.exe --diagnose` reports the platform correctly
- [ ] Window list shows Notepad, a browser and Windows Terminal with correct
      titles, application names and PIDs
- [ ] **Activation:** select Notepad, focus a *different* window, Start with a
      3 s countdown → the text appears in Notepad and nowhere else
- [ ] Activation failure types nothing anywhere
- [ ] Keyboard: lowercase, uppercase, digits, punctuation, `enter`, `tab`,
      `esc`, `backspace`, arrows
- [ ] Named key and key down/up (hold `shift`, type, release)
- [ ] Shortcuts: `ctrl+c`, `ctrl+v`, `ctrl+shift+p`
- [ ] Mouse: absolute move, movement duration (set 2000 ms — it should visibly
      take ~2 s), left/right/middle click, down/up drag
- [ ] Emergency stop during a long wait, and during a movement
- [ ] Global hotkey `Ctrl+Shift+F9` stops a run
- [ ] After any stop: no stuck modifier, no stuck mouse button
- [ ] Profile save, load, and reload after restarting the application
- [ ] Uninstall removes the application and **keeps** `%APPDATA%\human-input-automation`

### macOS

- [ ] DMG opens; the application copies to Applications
- [ ] Note whether the build is signed/notarised, or whether Gatekeeper warns
- [ ] First launch shows the briefing with **Accessibility** and **Input
      Monitoring** listed separately
- [ ] Before granting: `--diagnose` reports the permissions as denied or
      unknown, and window control is unavailable
- [ ] Grant Accessibility → quit and reopen → window enumeration and activation
      become available
- [ ] Grant Input Monitoring → quit and reopen → the global hotkey works
- [ ] Grant **Automation** (System Events) when prompted → quit and reopen →
      the window list works. Confirm it is a *separate* prompt from Accessibility
- [ ] Confirm granting one permission does **not** silently enable the others
- [ ] With Accessibility granted but Automation denied: the window list is empty
      and the banner names Automation, not Accessibility
- [ ] **Activation:** target A selected, B focused, Start → input lands in A
- [ ] Keyboard, including `cmd` being Command and **not** Ctrl (`cmd+a` selects
      all; if it triggers "select all" via Ctrl the mapping is wrong)
- [ ] Mouse move/click/down/up, and movement duration
- [ ] Emergency stop during a wait and while paused
- [ ] Profiles save and reload
- [ ] Coordinates behave sensibly on a Retina display (note points vs pixels)

### Linux / X11

- [ ] `echo $XDG_SESSION_TYPE` reports `x11`
- [ ] AppImage runs without any development environment installed
- [ ] `--diagnose` reports x11 and the `x11` window backend
- [ ] Window enumeration lists several applications with correct PIDs
- [ ] **Activation:** target A selected, B focused, Start → input lands in A
- [ ] Keyboard, named keys, key down/up, shortcuts
- [ ] Mouse move/click/down/up, movement duration
- [ ] Emergency stop during a wait, a movement and while paused
- [ ] Global hotkey stops a run
- [ ] Profiles save to `~/.local/share/human-input-automation/profiles` and
      reload after a restart
- [ ] Multi-monitor: move to a point on a second monitor, including one placed
      left of or above the primary; an off-desktop coordinate is rejected

### Linux / Wayland

The point here is that restrictions are *reported*, not circumvented.

- [ ] `--diagnose` reports wayland, and marks window activation, focus
      verification and the global hotkey unavailable
- [ ] With XWayland present, enumeration is reported as **restricted** and
      lists X11 clients only
- [ ] The capability banner explains the restriction in the UI
- [ ] Selecting an XWayland target and pressing Start fails with "Unable to
      activate the selected window" and types nothing
- [ ] Nothing in the application forces X11 or works around the compositor
- [ ] Profiles still save, load and resolve (or report unresolved) correctly

## Emergency-stop verification (every platform)

Run each of these and confirm the run ends promptly, the UI returns to an
idle-like state, and the report says stopped:

- [ ] Stop during normal action execution
- [ ] Stop during a long `Wait`
- [ ] Stop while paused
- [ ] Stop during a long mouse movement (set 5000 ms)
- [ ] Stop while a key is held (`key down shift`, long wait, stop) → **shift
      must not remain held**; check by typing in an editor afterwards
- [ ] Stop during the pre-run countdown → no window was activated, nothing typed
- [ ] Global hotkey during each of the above, where the hotkey is available

## After verification

- [ ] Update the matrix in `docs/PHASE3-PLATFORM-REPORT.md` with real results
- [ ] File issues for every FAIL, with `--diagnose` output and the log file
      (`~/.local/state/human-input-automation/logs`, `~/Library/Logs/…`, or
      `%APPDATA%\human-input-automation\logs`)
- [ ] Publish the draft release once the results are recorded
