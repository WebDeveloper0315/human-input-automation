from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

class ActionType(str, Enum):
    TEXT = "text"
    KEY = "key"
    CLICK = "click"
    MOVE = "move"
    WAIT = "wait"

@dataclass(frozen=True)
class TimingProfile:
    # Bounded jitter around a base delay; values are milliseconds.
    base_delay_ms: int = 80
    jitter_ms: int = 35
    min_delay_ms: int = 20
    max_delay_ms: int = 250

@dataclass(frozen=True)
class TargetWindow:
    backend_id: str
    title: str
    process_name: str | None = None

@dataclass(frozen=True)
class Action:
    type: ActionType
    value: str | None = None
    x: int | None = None
    y: int | None = None
    duration_ms: int | None = None

@dataclass
class AutomationPlan:
    target: TargetWindow
    actions: list[Action] = field(default_factory=list)
    timing: TimingProfile = field(default_factory=TimingProfile)
