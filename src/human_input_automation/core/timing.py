"""Timing profiles and the timing service.

The goal is *natural, configurable* pacing for desktop automation, testing and
accessibility work: input that a normal application can keep up with and that a
person can follow on screen. It is explicitly not an attempt to imitate a person
or to defeat anti-bot, CAPTCHA or other security controls, and nothing here
should be described that way.

Everything is derived from a single seeded ``random.Random``, so a seed makes a
whole run reproducible - which is what the tests rely on.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .errors import ValidationError, ValidationIssue

DEFAULT_PUNCTUATION = ".,;:!?"


def _check(condition: bool, code: str, message: str) -> ValidationIssue | None:
    return None if condition else ValidationIssue(code, message, location="timing")


@dataclass(frozen=True)
class TimingProfile:
    """User-configurable timing parameters. All values are milliseconds.

    Delay composition for a typed character is::

        clamp(char_delay +- char_jitter, min_delay, max_delay)
          + word pause      (after whitespace, when configured)
          + punctuation pause (after ``punctuation_chars``, when configured)

    The bounds apply to the base delay; pauses are additive extras so that a
    tight ``max_delay`` cannot silently erase a configured sentence pause.
    """

    # Per-character typing.
    char_delay_ms: float = 80.0
    char_jitter_ms: float = 35.0
    min_delay_ms: float = 20.0
    max_delay_ms: float = 250.0

    # Extra pauses layered on top of the base character delay.
    word_pause_ms: float = 0.0
    word_pause_jitter_ms: float = 0.0
    punctuation_pause_ms: float = 0.0
    punctuation_pause_jitter_ms: float = 0.0
    punctuation_chars: str = DEFAULT_PUNCTUATION

    # Delay inserted between two actions (unless the action overrides it).
    action_delay_ms: float = 120.0
    action_jitter_ms: float = 40.0

    # Default duration of a pointer movement.
    mouse_move_duration_ms: float = 200.0
    mouse_move_jitter_ms: float = 50.0

    def __post_init__(self) -> None:
        numeric = {
            "char_delay_ms": self.char_delay_ms,
            "char_jitter_ms": self.char_jitter_ms,
            "min_delay_ms": self.min_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "word_pause_ms": self.word_pause_ms,
            "word_pause_jitter_ms": self.word_pause_jitter_ms,
            "punctuation_pause_ms": self.punctuation_pause_ms,
            "punctuation_pause_jitter_ms": self.punctuation_pause_jitter_ms,
            "action_delay_ms": self.action_delay_ms,
            "action_jitter_ms": self.action_jitter_ms,
            "mouse_move_duration_ms": self.mouse_move_duration_ms,
            "mouse_move_jitter_ms": self.mouse_move_jitter_ms,
        }
        issues = [
            ValidationIssue("timing.negative", f"{name} must be >= 0, got {value}", "timing")
            for name, value in numeric.items()
            if value < 0
        ]
        bound = _check(
            self.min_delay_ms <= self.max_delay_ms,
            "timing.bounds",
            f"min_delay_ms ({self.min_delay_ms}) must be <= max_delay_ms ({self.max_delay_ms})",
        )
        if bound is not None:
            issues.append(bound)
        if issues:
            raise ValidationError(issues)

    @classmethod
    def instant(cls) -> TimingProfile:
        """Zero-delay profile, for tests and for users who want maximum speed."""
        return cls(
            char_delay_ms=0.0,
            char_jitter_ms=0.0,
            min_delay_ms=0.0,
            max_delay_ms=0.0,
            action_delay_ms=0.0,
            action_jitter_ms=0.0,
            mouse_move_duration_ms=0.0,
            mouse_move_jitter_ms=0.0,
        )

    @property
    def is_instant_typing(self) -> bool:
        """True when typing has no per-character delay at all."""
        return (
            self.char_delay_ms == 0
            and self.char_jitter_ms == 0
            and self.min_delay_ms == 0
            and self.word_pause_ms == 0
            and self.word_pause_jitter_ms == 0
            and self.punctuation_pause_ms == 0
            and self.punctuation_pause_jitter_ms == 0
        )

    def with_changes(self, **changes: object) -> TimingProfile:
        """Return a copy with fields replaced (validated by ``__post_init__``)."""
        return replace(self, **changes)  # type: ignore[arg-type]


class TimingService:
    """Turns a :class:`TimingProfile` into concrete delays.

    Deterministic when constructed with a seed: the same seed and the same
    sequence of calls always produce the same delays.
    """

    def __init__(
        self,
        profile: TimingProfile | None = None,
        *,
        seed: int | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.profile = profile or TimingProfile()
        self._rng = rng if rng is not None else random.Random(seed)
        self._seed = seed

    @property
    def seed(self) -> int | None:
        return self._seed

    def _sample(self, base: float, jitter: float) -> float:
        if jitter <= 0:
            return base
        return self._rng.uniform(base - jitter, base + jitter)

    def _bounded(self, base: float, jitter: float) -> float:
        value = self._sample(base, jitter)
        return max(self.profile.min_delay_ms, min(self.profile.max_delay_ms, value))

    def _extra(self, base: float, jitter: float) -> float:
        if base <= 0 and jitter <= 0:
            return 0.0
        return max(0.0, self._sample(base, jitter))

    def char_delay_ms(self, char: str) -> float:
        """Delay to apply *after* typing ``char``.

        Word-boundary and punctuation pauses are added on top of the bounded
        base delay.
        """
        profile = self.profile
        delay = self._bounded(profile.char_delay_ms, profile.char_jitter_ms)
        if char.isspace():
            delay += self._extra(profile.word_pause_ms, profile.word_pause_jitter_ms)
        elif char in profile.punctuation_chars:
            delay += self._extra(
                profile.punctuation_pause_ms, profile.punctuation_pause_jitter_ms
            )
        return delay

    def action_delay_ms(self, override_ms: float | None = None) -> float:
        """Delay between two actions; an explicit override is used verbatim."""
        if override_ms is not None:
            return max(0.0, override_ms)
        profile = self.profile
        if profile.action_delay_ms == 0 and profile.action_jitter_ms == 0:
            return 0.0
        return max(0.0, self._sample(profile.action_delay_ms, profile.action_jitter_ms))

    def mouse_move_duration_ms(self, override_ms: float | None = None) -> float:
        """How long a pointer movement should take."""
        if override_ms is not None:
            return max(0.0, override_ms)
        profile = self.profile
        return max(0.0, self._sample(profile.mouse_move_duration_ms, profile.mouse_move_jitter_ms))

    def key_repeat_delay_ms(self) -> float:
        """Delay between repetitions of the same key press."""
        return self._bounded(self.profile.char_delay_ms, self.profile.char_jitter_ms)

    def key_hold_ms(self) -> float:
        """How long a key stays down during a press/release pair."""
        return max(0.0, min(self.profile.min_delay_ms, 20.0))
