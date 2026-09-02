# Platform verification harness

Runs the **real** adapters — real pynput, real window control, real screen
geometry — against a dedicated target application, and reports what actually
happened. This is the only part of the project that generates real keyboard and
mouse input without a user pressing Start.

It lives in `tools/` and is never imported by the application.

```
target_app.py         a harmless window that records the input it receives
mini_wm.py            a minimal EWMH window manager, for bare X servers only
verify.py             the driver: runs the checks and prints the results
run_x11_session.sh    starts Xvfb + window manager + target + decoy, then verifies
```

## Running it

### Isolated (recommended, and what CI uses)

Nothing touches your own desktop: every window lives on a private X server.

```bash
tools/platform_verify/run_x11_session.sh /tmp/verify python
```

Needs `Xvfb` on `PATH`. On a machine without it:
`conda create -p ./xenv -c conda-forge xorg-xvfb-server` installs one without
root.

### On a real desktop session

```bash
python tools/platform_verify/target_app.py --events /tmp/e.jsonl &
python tools/platform_verify/verify.py --events /tmp/e.jsonl
```

Real input **will** be generated on that session. Close anything you care
about first; the harness types only into its own target window, but a window
manager can always steal focus.

## Safety rules the harness enforces on itself

* **It only types into its own target.** Before any input is generated the
  resolved window's application identity must equal the verification target's.
  Anything else aborts — it will not type into a browser, editor or terminal,
  whatever the window list contains.
* **Dry run first.** Every session proves that a dry run reached the report and
  *not* the target before sending anything for real.
* **Harmless actions only.** Literal text, arrow keys, a click inside the
  target. Nothing it types can act on anything, and there is no code path here
  that executes a command.
* The target application records events and nothing else: no shell, no network,
  no file access beyond its own event log, no system settings.

## What the results do and do not prove

`mini_wm.py` is a ~150-line EWMH window manager, not GNOME, KDE or i3. Results
obtained with it are evidence about **our adapters against a real X server**,
and must be reported as "verified against a minimal EWMH window manager on
Xvfb" — never as "verified on a native X11 desktop". Verification on a real
desktop session, on Windows and on macOS is still the manual checklist in
`docs/RELEASE-CHECKLIST.md`.

Results are recorded in `docs/PHASE6-REAL-PLATFORM-REPORT.md`.


## Running it without root

`run_x11_session.sh` needs `Xvfb`. Where the packages cannot be installed
system-wide, extract them into a prefix and put that on `PATH`:

```bash
mkdir -p /tmp/xvfb && cd /tmp/xvfb
apt-get download xvfb xserver-common x11-xkb-utils xkb-data
for d in *.deb; do dpkg -x "$d" root; done

mkdir -p bin && cat > bin/Xvfb <<'EOF'
#!/bin/bash
export PATH="/tmp/xvfb/root/usr/bin:$PATH"
exec /tmp/xvfb/root/usr/bin/Xvfb -xkbdir /tmp/xvfb/root/usr/share/X11/xkb "$@"
EOF
chmod +x bin/Xvfb

PATH=/tmp/xvfb/bin:$PATH bash tools/platform_verify/run_x11_session.sh /tmp/run
```

The `-xkbdir` matters: without it the server cannot find its keymaps and every
key check fails for a reason that has nothing to do with the application.
