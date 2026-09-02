"""Run the verification harness on the current desktop session.

For Windows, macOS, and Linux desktops that already have a window manager.
(`run_x11_session.sh` is the isolated-X-server variant; it needs Xvfb and a
window manager, neither of which exists on Windows or macOS.)

    python tools/platform_verify/run_desktop_session.py --confirm

This **generates real keyboard and mouse input on the session you are sitting
in**. It types only into its own target window - the harness refuses to run
against any other application - but a window manager can always move focus, so
close anything you care about first. ``--confirm`` is required precisely so
this cannot happen by accident; without it only the checks that send no input
are run.

Pure Python, no shell: the same command works on all three platforms.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

TARGET_APP_ID = "automation-verify-target"
DECOY_APP_ID = "automation-verify-decoy"


def start(python: str, script: str, *arguments: str, log: Path) -> subprocess.Popen[bytes]:
    command = [python, str(HERE / script), *arguments]
    print(f"  $ {' '.join(command)}", flush=True)
    with log.open("wb") as handle:
        return subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=Path.cwd() / "verify-run")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="allow real keyboard and mouse input on this desktop session",
    )
    parser.add_argument("--seconds", type=float, default=900.0, help="how long the windows live")
    arguments = parser.parse_args(argv)

    workdir = arguments.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"Working directory: {workdir}")

    if not arguments.confirm:
        print(
            "\nRunning WITHOUT --confirm: only the checks that send no input will run.\n"
            "Add --confirm once you are ready for the harness to type into its own\n"
            "target window on this desktop.\n"
        )

    environment = dict(os.environ)
    environment["XDG_DATA_HOME"] = str(workdir / "data")
    environment["XDG_STATE_HOME"] = str(workdir / "state")
    os.environ.update(environment)

    processes: list[subprocess.Popen[bytes]] = []
    try:
        print("\n== target window")
        target = start(
            arguments.python,
            "target_app.py",
            "--events", str(workdir / "target.jsonl"),
            "--geometry", "40,40,800,600",
            "--seconds", str(arguments.seconds),
            log=workdir / "target.log",
        )
        processes.append(target)
        time.sleep(4)

        print("== decoy window")
        decoy = start(
            arguments.python,
            "target_app.py",
            "--events", str(workdir / "decoy.jsonl"),
            "--title", "Decoy Window",
            "--app-name", DECOY_APP_ID,
            "--geometry", "900,40,800,600",
            "--seconds", str(arguments.seconds - 5),
            log=workdir / "decoy.log",
        )
        processes.append(decoy)
        time.sleep(4)

        print("== verification\n")
        command = [
            arguments.python,
            str(HERE / "verify.py"),
            "--events", str(workdir / "target.jsonl"),
            "--decoy-events", str(workdir / "decoy.jsonl"),
            "--target-pid", str(target.pid),
            "--decoy-pid", str(decoy.pid),
            "--profiles", str(workdir / "profiles"),
            "--json", str(workdir / "report.json"),
        ]
        if not arguments.confirm:
            command.append("--skip-input")
        result = subprocess.run(command, check=False)
        print(f"\n== done (exit {result.returncode}); logs and report in {workdir}")
        return result.returncode
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - best effort
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
