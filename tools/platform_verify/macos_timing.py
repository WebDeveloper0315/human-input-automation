"""How long each desktop question takes on this Mac. Sends no input.

A script run asks the desktop the same few questions over and over: which
process is in front, which windows exist, what a terminal shows. On macOS some
of these go through Accessibility or AppleScript and cost far more than on
Linux, so they are measured here rather than guessed.

    python tools/platform_verify/macos_timing.py

Have one Terminal window open. Nothing is typed, clicked or focused; the only
side effect is macOS asking, once, whether this program may control Terminal.
"""

from __future__ import annotations

import statistics
import subprocess
import time
from collections.abc import Callable
from typing import Any


def measure(name: str, call: Callable[[], Any], repeat: int = 5) -> None:
    times: list[float] = []
    result: Any = None
    error = ""
    for _ in range(repeat):
        started = time.perf_counter()
        try:
            result = call()
        except Exception as exc:  # report, keep measuring the rest
            error = f"{type(exc).__name__}: {exc}"
        times.append((time.perf_counter() - started) * 1000)
    shown = error or _summary(result)
    median = statistics.median(times)
    print(f"{name:<44} median {median:8.1f} ms   max {max(times):8.1f} ms   {shown}")


def _summary(result: Any) -> str:
    if isinstance(result, str):
        return f"{len(result)} characters, {result.count(chr(10)) + 1} lines"
    if isinstance(result, list | tuple):
        return f"{len(result)} item(s)"
    return repr(result)[:60]


def osascript(script: str) -> str:
    done = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"exit {done.returncode}")
    return done.stdout


def main() -> None:
    from human_input_automation.adapters.registry import build_adapters

    adapters = build_adapters()
    windows: Any = adapters.windows
    print(f"window backend: {adapters.window_backend}; host: {adapters.host.platform.value}\n")

    measure("front process (fast path, per keystroke)", windows.active_process_id, repeat=20)
    measure("focused window (full lookup)", windows.active_window)
    measure("list every window (App: step)", adapters.discovery.list_windows, repeat=3)
    measure(
        "Terminal text: whole history",
        lambda: osascript(
            'tell application "Terminal" to get history of selected tab of front window'
        ),
    )
    measure(
        "Terminal text: visible contents",
        lambda: osascript(
            'tell application "Terminal" to get contents of selected tab of front window'
        ),
    )
    measure("osascript that does nothing (start-up cost)", lambda: osascript("return 1"))
    adapters.close()
    print("\nNo input was sent.")


if __name__ == "__main__":
    main()
