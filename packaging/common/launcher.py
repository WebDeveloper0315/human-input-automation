"""PyInstaller entry point.

A packaged build starts here rather than at ``__main__``: PyInstaller needs a
plain script, and freezing wants ``multiprocessing.freeze_support`` called
before anything else. The real work stays in ``human_input_automation.app``.
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from human_input_automation.app import run

    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
