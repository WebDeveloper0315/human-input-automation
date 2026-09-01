from typing import Protocol
from .models import AutomationPlan
from .timing import HumanTiming

class InputBackend(Protocol):
    def activate_target(self, target_id: str) -> None: ...
    def type_text(self, text: str) -> None: ...
    def press_key(self, key: str) -> None: ...
    def move_mouse(self, x: int, y: int, duration_ms: int) -> None: ...
    def click(self, x: int, y: int) -> None: ...

class AutomationEngine:
    def __init__(self, backend: InputBackend, sleeper, seed: int | None = None) -> None:
        self.backend = backend
        self.sleeper = sleeper
        self.seed = seed

    def run(self, plan: AutomationPlan, stop_requested) -> None:
        timing = HumanTiming(plan.timing, self.seed)
        self.backend.activate_target(plan.target.backend_id)
        for action in plan.actions:
            if stop_requested():
                return
            if action.type.value == "text" and action.value is not None:
                for char in action.value:
                    if stop_requested():
                        return
                    self.backend.type_text(char)
                    self.sleeper(timing.next_delay_ms() / 1000)
            elif action.type.value == "key" and action.value is not None:
                self.backend.press_key(action.value)
                self.sleeper(timing.next_delay_ms() / 1000)
            elif action.type.value == "move" and action.x is not None and action.y is not None:
                self.backend.move_mouse(action.x, action.y, action.duration_ms or 200)
                self.sleeper(timing.next_delay_ms() / 1000)
            elif action.type.value == "click" and action.x is not None and action.y is not None:
                self.backend.click(action.x, action.y)
                self.sleeper(timing.next_delay_ms() / 1000)
            elif action.type.value == "wait":
                self.sleeper((action.duration_ms or 0) / 1000)
