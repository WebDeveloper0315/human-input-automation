"""A deliberately harmless target application for real-input verification.

Real automation testing needs something to type into. Typing into the tester's
own editor, terminal or browser is unacceptable - a stray keystroke could do
anything - so verification targets this instead: a window that records what it
receives and does nothing else.

What it does:

* shows a text field, a button and a status area
* records every key and mouse event it receives, with timestamps
* appends those events to a JSON-lines file so a harness can assert on them
* writes down the contents of its text field when F8 is pressed

What it deliberately cannot do: run commands, read or write files other than
its own event log, open network connections, change any system setting, or
touch another application. There is no code path here that executes anything.

    python tools/platform_verify/target_app.py --events /tmp/events.jsonl

This lives in ``tools/`` and is never imported by the application.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

APP_NAME = "automation-verify-target"
WINDOW_TITLE = "Automation Verification Target"


class EventRecorder:
    """Appends events to a JSON-lines file, flushed immediately.

    Flushing on every event lets the harness read the file while the target is
    still running, which is what makes "did this keystroke arrive?" answerable
    without shutting anything down.
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def record(self, kind: str, **fields: Any) -> dict[str, Any]:
        event = {"kind": kind, "at": time.time(), **fields}
        self.events.append(event)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event) + "\n")
                handle.flush()
        return event


def build_window(recorder: EventRecorder, title: str) -> Any:
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import (
        QLabel,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(title)
            self.resize(720, 420)

            self.status = QLabel("Waiting for input...")
            self.status.setAccessibleName("Verification status")
            self.counter = QLabel("keys: 0   mouse: 0")
            self.editor = QPlainTextEdit()
            self.editor.setAccessibleName("Verification text field")
            self.editor.setPlaceholderText("Automated text appears here")
            self.button = QPushButton("Verification button")
            self.button.setAccessibleName("Verification button")
            self.button.clicked.connect(self._on_clicked)

            layout = QVBoxLayout()
            layout.addWidget(QLabel(f"{title}\n\nThis window only records input."))
            layout.addWidget(self.editor)
            layout.addWidget(self.button)
            layout.addWidget(self.counter)
            layout.addWidget(self.status)
            central = QWidget()
            central.setLayout(layout)
            self.setCentralWidget(central)

            self.keys = 0
            self.mouse = 0

        def _on_clicked(self) -> None:
            recorder.record("button_clicked")
            self.status.setText("Button clicked")

        def note(self, kind: str) -> None:
            if kind.startswith("key"):
                self.keys += 1
            else:
                self.mouse += 1
            self.counter.setText(f"keys: {self.keys}   mouse: {self.mouse}")
            self.status.setText(f"Last event: {kind}")

    class Filter(QObject):
        """Records events for the whole application, not one widget."""

        def __init__(self, window: Window) -> None:
            super().__init__()
            self.window = window
            # Qt delivers an unhandled event to the focus widget and then to
            # each parent, so one keystroke reaches this filter several times.
            # Deduplicate on the OS event timestamp plus the key: object
            # identity is useless here because CPython reuses addresses.
            self._last_signature: tuple[Any, ...] = ()

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            kind = event.type()
            signature = self._signature(kind, event)
            if signature is not None:
                if signature == self._last_signature:
                    return False
                self._last_signature = signature
            if kind == QEvent.Type.KeyPress:
                recorder.record(
                    "key_press",
                    key=int(event.key()),
                    text=event.text(),
                    modifiers=int(event.modifiers().value),
                )
                self.window.note("key_press")
                if event.key() == int(Qt.Key.Key_F8):
                    # A harness cannot read another process's widget. F8 asks
                    # the target to write down what its editor actually holds,
                    # which is how "did the text arrive intact?" is answered
                    # for a whole block rather than key by key.
                    recorder.record("content", text=self.window.editor.toPlainText())
            elif kind == QEvent.Type.KeyRelease:
                recorder.record("key_release", key=int(event.key()))
                self.window.note("key_release")
            elif kind == QEvent.Type.MouseButtonPress:
                position = event.globalPosition()
                recorder.record(
                    "mouse_press",
                    button=int(event.button().value),
                    x=int(position.x()),
                    y=int(position.y()),
                )
                self.window.note("mouse_press")
            elif kind == QEvent.Type.WindowActivate:
                recorder.record("focus_in")
            elif kind == QEvent.Type.WindowDeactivate:
                recorder.record("focus_out")
            elif kind == QEvent.Type.MouseButtonRelease:
                recorder.record("mouse_release", button=int(event.button().value))
                self.window.note("mouse_release")
            elif kind == QEvent.Type.MouseMove:
                position = event.globalPosition()
                recorder.record("mouse_move", x=int(position.x()), y=int(position.y()))
            return False

        @staticmethod
        def _signature(kind: Any, event: QEvent) -> tuple[Any, ...] | None:
            """Identity of one physical input event, stable across propagation."""
            if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                return (int(kind), event.key(), event.timestamp())
            if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                return (int(kind), int(event.button().value), event.timestamp())
            return None

    window = Window()
    window.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
    return window, Filter(window)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, help="write recorded events to this JSON-lines file")
    parser.add_argument("--title", default=WINDOW_TITLE, help="window title to use")
    parser.add_argument(
        "--app-name",
        default=APP_NAME,
        help="application identity (WM_CLASS); the decoy uses a different one so the "
        "harness can tell the two windows apart by identity, not by title",
    )
    parser.add_argument("--seconds", type=float, default=0.0, help="exit after this long")
    parser.add_argument(
        "--geometry",
        default="",
        help="place the window at X,Y,WIDTH,HEIGHT so clicks land predictably",
    )
    arguments = parser.parse_args(argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    application = QApplication(sys.argv[:1])
    # A predictable WM_CLASS, so the harness can identify this window by
    # application identity rather than by its title.
    application.setApplicationName(arguments.app_name)
    application.setDesktopFileName(arguments.app_name)
    application.setOrganizationName(arguments.app_name)

    recorder = EventRecorder(arguments.events)
    window, event_filter = build_window(recorder, arguments.title)
    application.installEventFilter(event_filter)
    if arguments.geometry:
        x, y, width, height = (int(part) for part in arguments.geometry.split(","))
        window.setGeometry(x, y, width, height)
    window.show()
    window.raise_()
    window.activateWindow()
    geometry = window.geometry()
    recorder.record(
        "ready",
        title=arguments.title,
        pid=os.getpid(),
        geometry=[geometry.x(), geometry.y(), geometry.width(), geometry.height()],
    )

    if arguments.seconds > 0:
        QTimer.singleShot(int(arguments.seconds * 1000), application.quit)
    return int(application.exec())


if __name__ == "__main__":
    raise SystemExit(main())
