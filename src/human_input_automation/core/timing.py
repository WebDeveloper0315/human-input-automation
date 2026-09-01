import random
from .models import TimingProfile

class HumanTiming:
    """Generate bounded, configurable timing variation.

    This is intentionally simple and testable. It does not attempt to model
    or claim biological/human behavior.
    """

    def __init__(self, profile: TimingProfile, seed: int | None = None) -> None:
        self.profile = profile
        self.rng = random.Random(seed)

    def next_delay_ms(self) -> int:
        p = self.profile
        value = p.base_delay_ms + self.rng.randint(-p.jitter_ms, p.jitter_ms)
        return max(p.min_delay_ms, min(p.max_delay_ms, value))
