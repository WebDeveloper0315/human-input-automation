"""Reading what a terminal shows.

``expect output contains "COPY 30"`` checks what a command printed, and the
exact answer is in the terminal's own text, not in a picture of it: no OCR,
nothing to misread, and nothing that goes stale when the window moves.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.target import TargetWindow


@runtime_checkable
class TerminalPort(Protocol):
    """The text of the terminal that has focus."""

    def read_text(self, window: TargetWindow) -> str | None:
        """Everything the terminal in ``window`` holds, scrollback included.

        ``window`` is the terminal the script is working in, and it has focus
        when this is called - the runner checks that before every step. Returns
        ``None`` when the text cannot be read: an application this adapter
        does not know, a permission not granted, a backend that is missing.
        ``None`` is "cannot tell", never "empty".
        """
        ...
