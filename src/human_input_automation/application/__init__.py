"""Application layer: orchestration between the UI and the core."""

from .runner import AutomationRunner, EventCollector
from .service import AutomationService

__all__ = ["AutomationRunner", "AutomationService", "EventCollector"]
