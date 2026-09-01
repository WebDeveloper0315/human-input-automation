"""Thread bridge between the automation worker and the Qt main thread.

The engine calls its listener on the worker thread. Qt widgets may only be
touched from the thread that owns them. The bridge is the single, auditable
place where that boundary is crossed:

    worker thread -> RunEvent -> bridge.__call__ -> Qt signal (queued)
                                                 -> slot on the main thread
                                                 -> widgets

Because the bridge object is created on the main thread, ``Signal.emit`` from
another thread uses a queued connection, so slots always execute on the main
thread. Nothing else in ``ui/`` may be called from a worker thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.events import RunEvent


class RunEventBridge(QObject):
    """Callable event listener that re-emits run events as Qt signals."""

    #: Emitted on the main thread for every run event. Payload: ``RunEvent``.
    #: Named ``run_event`` rather than ``event``: ``QObject.event`` is Qt's own
    #: event handler and must not be shadowed by a signal.
    run_event = Signal(object)
    #: Emitted when the global emergency-stop hotkey fires (also cross-thread).
    hotkey_triggered = Signal()

    def __call__(self, event: RunEvent) -> None:
        """Listener entry point. Runs on the worker thread - no widgets here."""
        self.run_event.emit(event)

    def notify_hotkey(self) -> None:
        """Hotkey listener entry point. Runs on the pynput listener thread."""
        self.hotkey_triggered.emit()
