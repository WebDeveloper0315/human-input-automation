"""Timing service: bounds, determinism and the individual delay sources."""

from __future__ import annotations

import pytest

from human_input_automation.core.errors import ValidationError
from human_input_automation.core.timing import TimingProfile, TimingService


def test_character_delays_stay_within_configured_bounds() -> None:
    profile = TimingProfile(char_delay_ms=80, char_jitter_ms=500, min_delay_ms=20, max_delay_ms=250)
    timing = TimingService(profile, seed=1)
    values = [timing.char_delay_ms("a") for _ in range(500)]
    assert all(20 <= value <= 250 for value in values)


def test_jitter_actually_varies_the_delay() -> None:
    timing = TimingService(TimingProfile(char_jitter_ms=30), seed=7)
    values = {timing.char_delay_ms("a") for _ in range(50)}
    assert len(values) > 1


def test_zero_jitter_is_exact() -> None:
    timing = TimingService(TimingProfile(char_delay_ms=50, char_jitter_ms=0), seed=1)
    assert timing.char_delay_ms("a") == 50


def test_same_seed_reproduces_the_same_sequence() -> None:
    profile = TimingProfile()
    first = TimingService(profile, seed=42)
    second = TimingService(profile, seed=42)
    assert [first.char_delay_ms("a") for _ in range(20)] == [
        second.char_delay_ms("a") for _ in range(20)
    ]


def test_different_seeds_produce_different_sequences() -> None:
    profile = TimingProfile()
    first = [TimingService(profile, seed=1).char_delay_ms("a") for _ in range(10)]
    second = [TimingService(profile, seed=2).char_delay_ms("a") for _ in range(10)]
    assert first != second


def test_word_boundary_adds_a_pause_on_top_of_the_base_delay() -> None:
    profile = TimingProfile(char_delay_ms=50, char_jitter_ms=0, word_pause_ms=200, max_delay_ms=60)
    timing = TimingService(profile, seed=1)
    assert timing.char_delay_ms("a") == 50
    assert timing.char_delay_ms(" ") == 250


def test_punctuation_adds_a_pause() -> None:
    profile = TimingProfile(char_delay_ms=40, char_jitter_ms=0, punctuation_pause_ms=300)
    timing = TimingService(profile, seed=1)
    assert timing.char_delay_ms(".") == 340
    assert timing.char_delay_ms("a") == 40


def test_punctuation_set_is_configurable() -> None:
    profile = TimingProfile(
        char_delay_ms=10,
        char_jitter_ms=0,
        min_delay_ms=0,
        punctuation_pause_ms=100,
        punctuation_chars="#",
    )
    timing = TimingService(profile, seed=1)
    assert timing.char_delay_ms("#") == 110
    assert timing.char_delay_ms(".") == 10


def test_action_delay_uses_the_override_verbatim() -> None:
    timing = TimingService(TimingProfile(), seed=1)
    assert timing.action_delay_ms(0) == 0
    assert timing.action_delay_ms(1234) == 1234


def test_action_delay_is_bounded_by_its_own_jitter() -> None:
    timing = TimingService(TimingProfile(action_delay_ms=100, action_jitter_ms=20), seed=3)
    values = [timing.action_delay_ms() for _ in range(200)]
    assert all(80 <= value <= 120 for value in values)


def test_mouse_move_duration_honours_override_and_jitter() -> None:
    timing = TimingService(
        TimingProfile(mouse_move_duration_ms=200, mouse_move_jitter_ms=50), seed=5
    )
    assert timing.mouse_move_duration_ms(0) == 0
    assert timing.mouse_move_duration_ms(300) == 300
    values = [timing.mouse_move_duration_ms() for _ in range(100)]
    assert all(150 <= value <= 250 for value in values)


def test_delays_are_never_negative_even_with_large_jitter() -> None:
    profile = TimingProfile(
        char_delay_ms=10,
        char_jitter_ms=1000,
        min_delay_ms=0,
        max_delay_ms=1000,
        word_pause_ms=5,
        word_pause_jitter_ms=500,
        action_delay_ms=5,
        action_jitter_ms=500,
        mouse_move_duration_ms=5,
        mouse_move_jitter_ms=500,
    )
    timing = TimingService(profile, seed=11)
    for _ in range(200):
        assert timing.char_delay_ms(" ") >= 0
        assert timing.action_delay_ms() >= 0
        assert timing.mouse_move_duration_ms() >= 0


def test_instant_profile_reports_instant_typing() -> None:
    assert TimingProfile.instant().is_instant_typing
    assert not TimingProfile().is_instant_typing


def test_invalid_profiles_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TimingProfile(char_delay_ms=-1)
    with pytest.raises(ValidationError):
        TimingProfile(min_delay_ms=300, max_delay_ms=100)


def test_with_changes_revalidates() -> None:
    profile = TimingProfile()
    assert profile.with_changes(char_delay_ms=10).char_delay_ms == 10
    with pytest.raises(ValidationError):
        profile.with_changes(char_delay_ms=-10)
