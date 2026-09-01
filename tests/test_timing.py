from human_input_automation.core.models import TimingProfile
from human_input_automation.core.timing import HumanTiming

def test_delay_is_bounded() -> None:
    profile = TimingProfile(base_delay_ms=80, jitter_ms=35, min_delay_ms=20, max_delay_ms=250)
    timing = HumanTiming(profile, seed=1)
    values = [timing.next_delay_ms() for _ in range(100)]
    assert all(20 <= value <= 250 for value in values)

def test_seed_is_reproducible() -> None:
    profile = TimingProfile()
    a = HumanTiming(profile, seed=42)
    b = HumanTiming(profile, seed=42)
    assert [a.next_delay_ms() for _ in range(10)] == [b.next_delay_ms() for _ in range(10)]
