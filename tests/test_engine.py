from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.models import *

class FakeBackend:
    def __init__(self):
        self.calls = []
    def activate_target(self, target_id): self.calls.append(("activate", target_id))
    def type_text(self, text): self.calls.append(("type", text))
    def press_key(self, key): self.calls.append(("key", key))
    def move_mouse(self, x, y, duration_ms): self.calls.append(("move", x, y, duration_ms))
    def click(self, x, y): self.calls.append(("click", x, y))

def test_engine_types_text_and_can_stop():
    backend = FakeBackend()
    sleeps = []
    plan = AutomationPlan(
        TargetWindow("1", "Test"),
        [Action(ActionType.TEXT, value="abc")],
    )
    engine = AutomationEngine(backend, sleeps.append, seed=1)
    engine.run(plan, lambda: False)
    assert [c[0] for c in backend.calls] == ["activate", "type", "type", "type"]
    assert len(sleeps) == 3
