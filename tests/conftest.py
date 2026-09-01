"""Shared fixtures.

Qt tests run on the ``offscreen`` platform plugin, so the whole suite works on a
headless CI runner with no display server. The environment variable is set here,
before any test imports PySide6.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app() -> Iterator[Any]:
    """A single QApplication for the whole session (Qt allows only one)."""
    pytest.importorskip("PySide6", reason="GUI extra not installed")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def pump(qt_app: Any) -> Callable[..., bool]:
    """Process queued Qt events until ``predicate`` holds or the timeout ends.

    Queued signals - which is how worker-thread events reach the UI - are only
    delivered while the event loop runs, so tests have to pump it explicitly.
    """
    import time

    def _pump(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qt_app.processEvents()
            if predicate():
                qt_app.processEvents()
                return True
            time.sleep(0.005)
        qt_app.processEvents()
        return predicate()

    return _pump
