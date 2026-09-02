#!/usr/bin/env bash
# Run the verification harness against an isolated X server.
#
# Starts Xvfb on a spare display, the minimal window manager, a target window
# and a decoy window, then runs verify.py against them. Nothing touches the
# tester's own desktop session: every window lives on the private display.
#
#   tools/platform_verify/run_x11_session.sh /path/to/workdir [python]
#
# Requires: Xvfb (any X server) and a Python with the project installed.
set -uo pipefail

WORKDIR="${1:?usage: run_x11_session.sh WORKDIR [PYTHON]}"
PYTHON="${2:-python}"
DISPLAY_NUMBER="${VERIFY_DISPLAY:-:99}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$WORKDIR"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null
  done
  wait 2>/dev/null
}
trap cleanup EXIT

start() {  # start LOGFILE COMMAND... in the background; prints its pid
  local log="$1"; shift
  "$@" >"$log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  echo "$pid"
}

echo "== X server on $DISPLAY_NUMBER"
if ! command -v Xvfb >/dev/null; then
  echo "Xvfb not found. Install it, or run the harness on a real X11 session." >&2
  exit 2
fi
start "$WORKDIR/xvfb.log" Xvfb "$DISPLAY_NUMBER" -screen 0 1920x1080x24 >/dev/null
sleep 2

# An X11-only environment. Platform detection is environment-based, so an
# inherited WAYLAND_DISPLAY from the tester's own session would otherwise make
# these X11 processes report themselves as running under Wayland.
unset WAYLAND_DISPLAY
export XDG_SESSION_TYPE=x11
export DISPLAY="$DISPLAY_NUMBER"
export QT_QPA_PLATFORM=xcb
export XDG_DATA_HOME="$WORKDIR/data"
export XDG_STATE_HOME="$WORKDIR/state"

echo "== window manager"
start "$WORKDIR/wm.log" "$PYTHON" "$HERE/mini_wm.py" --seconds 900 >/dev/null
sleep 2

echo "== target window"
TARGET_PID=$(start "$WORKDIR/target.log" "$PYTHON" "$HERE/target_app.py" \
  --events "$WORKDIR/target.jsonl" --geometry 40,40,800,600 --seconds 880)
sleep 3

echo "== decoy window"
DECOY_PID=$(start "$WORKDIR/decoy.log" "$PYTHON" "$HERE/target_app.py" \
  --events "$WORKDIR/decoy.jsonl" --title "Decoy Window" \
  --app-name automation-verify-decoy --geometry 1000,40,800,600 --seconds 875)
sleep 3

echo "== verification"
"$PYTHON" "$HERE/verify.py" \
  --events "$WORKDIR/target.jsonl" \
  --target-pid "$TARGET_PID" \
  --decoy-events "$WORKDIR/decoy.jsonl" \
  --decoy-pid "$DECOY_PID" \
  --profiles "$WORKDIR/profiles" \
  --json "$WORKDIR/report.json" \
  "${@:3}"
STATUS=$?
echo "== done (exit $STATUS); logs in $WORKDIR"
exit $STATUS
