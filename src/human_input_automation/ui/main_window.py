"""Placeholder main window.

The full interface (target picker, action editor, timing controls, run log,
Start/Pause/Stop and the emergency stop) is Phase 2. What this window already
demonstrates is the contract every future widget must follow:

* it talks only to :class:`~..application.service.AutomationService`;
* it never runs automation on the UI thread - the service owns a worker thread;
* it shows the host's real capabilities instead of assuming they exist.
"""

from __future__ import annotations

from typing import Any

from ..application.service import AutomationService


def build_status_text(service: AutomationService) -> str:
    """Summarise host capabilities. Pure function, so it is testable without Qt."""
    host = service.host
    capabilities = host.capabilities
    lines = [
        f"Platform: {host.platform.value} ({host.display_server.value})",
        f"Send input: {'yes' if capabilities.can_send_synthetic_input else 'no'}",
        f"Enumerate windows: {'yes' if capabilities.can_enumerate else 'no'}",
        f"Activate windows: {'yes' if capabilities.can_activate else 'no'}",
        f"Verify focus: {'yes' if capabilities.can_verify_focus else 'no'}",
    ]
    if host.missing_permissions:
        lines.append("Missing permissions: " + ", ".join(host.missing_permissions))
    for warning in host.warnings:
        lines.append(f"Note: {warning}")
    for problem in service.problems:
        lines.append(f"Adapter: {problem}")
    lines.append("")
    lines.append("Phase 2 adds the target picker, action editor, timing controls and run log.")
    return "\n".join(lines)


def create_main_window(service: AutomationService) -> Any:
    """Create the Qt main window. Imports PySide6 lazily so the core stays GUI-free."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QMainWindow

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Human Input Automation")
            self.resize(900, 600)
            label = QLabel(build_status_text(service))
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            label.setMargin(16)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.setCentralWidget(label)

    return MainWindow()
