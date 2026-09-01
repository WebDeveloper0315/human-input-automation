"""Platform-independent automation core.

Nothing in this package may import a GUI toolkit or a platform-specific
library; everything it needs arrives through ``human_input_automation.ports``.
"""

from .actions import (
    Action,
    KeyDown,
    KeyPress,
    KeyUp,
    MouseClick,
    MouseDown,
    MouseMove,
    MouseUp,
    Shortcut,
    TypeText,
    Wait,
)
from .control import RunControl, RunState
from .engine import ActionRegistry, AutomationEngine, ExecutionContext
from .errors import (
    AutomationError,
    Cancelled,
    LimitExceededError,
    TargetActivationError,
    UnsupportedActionError,
    ValidationError,
    ValidationIssue,
    ValidationResult,
)
from .events import RunEvent, RunReport, RunStatus
from .keys import Key, MouseButton, parse_shortcut
from .plan import AutomationPlan, ExecutionLimits, RunOptions
from .target import (
    DisplayServer,
    PlatformName,
    PlatformReport,
    TargetWindow,
    WindowCapabilities,
)
from .timing import TimingProfile, TimingService
from .validation import validate_plan

__all__ = [
    "Action",
    "ActionRegistry",
    "AutomationEngine",
    "AutomationError",
    "AutomationPlan",
    "Cancelled",
    "DisplayServer",
    "ExecutionContext",
    "ExecutionLimits",
    "Key",
    "KeyDown",
    "KeyPress",
    "KeyUp",
    "LimitExceededError",
    "MouseButton",
    "MouseClick",
    "MouseDown",
    "MouseMove",
    "MouseUp",
    "PlatformName",
    "PlatformReport",
    "RunControl",
    "RunEvent",
    "RunOptions",
    "RunReport",
    "RunState",
    "RunStatus",
    "Shortcut",
    "TargetActivationError",
    "TargetWindow",
    "TimingProfile",
    "TimingService",
    "TypeText",
    "UnsupportedActionError",
    "ValidationError",
    "ValidationIssue",
    "ValidationResult",
    "Wait",
    "WindowCapabilities",
    "parse_shortcut",
    "validate_plan",
]
