"""How faithfully text is typed.

The engine's default is to reproduce a string exactly: every character once, in
order. That is right for filling in a form, and wrong for a demonstration, a
screen recording, or a test that needs to exercise an application's editing and
undo paths - real typing arrives unevenly and is sometimes wrong before it is
right.

This module describes that second mode. A :class:`TypingStyle` says how often a
character is mistyped and how long the typist hesitates; :func:`plan_typing`
turns a string plus a seeded ``random.Random`` into the exact sequence of
keystrokes that produces it.

Two properties are guaranteed by construction, and both are tested:

* **The result is always the requested text.** Every slip is followed by exactly
  enough backspaces to remove it, and the intended characters are then typed
  again. A run that is not interrupted leaves the target holding the text that
  was asked for, character for character.
* **A correction never crosses a line boundary.** Newlines are never mistyped
  and never backspaced over, so a correction cannot join two lines of the user's
  document together.

This is *not* a way to make automation look human to a detection system, and it
must not be described or used as one. It changes what is typed and when, not
what the operating system reports about where the input came from - synthetic
input stays plainly synthetic on every platform this application supports.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .errors import ValidationError, ValidationIssue

#: Physical neighbours on a QWERTY keyboard, which is where substitution slips
#: come from: a finger lands one key off, not on a random letter. Non-letters
#: are deliberately absent - see ``_UNDOABLE`` for why.
NEIGHBOURS: dict[str, str] = {
    "q": "wa",
    "w": "qeasd",
    "e": "wrsdf",
    "r": "etdfg",
    "t": "ryfgh",
    "y": "tughj",
    "u": "yihjk",
    "i": "uojkl",
    "o": "ipkl",
    "p": "ol",
    "a": "qwszx",
    "s": "qweadzxc",
    "d": "wersfxcv",
    "f": "ertdgcvb",
    "g": "rtyfhvbn",
    "h": "tyugjbnm",
    "j": "yuihknm",
    "k": "uiojlm",
    "l": "iopk",
    "z": "asx",
    "x": "zsdc",
    "c": "xdfv",
    "v": "cfgb",
    "b": "vghn",
    "n": "bhjm",
    "m": "njk",
}

#: Characters a slip is allowed to type and then remove. Brackets and quotes are
#: excluded because a code editor inserts a partner for them: typing one and
#: backspacing over it later is no longer a one-key/one-backspace trade, and the
#: count that guarantees the text comes out right would be wrong.
_NOT_UNDOABLE = frozenset("()[]{}<>\"'`")


@dataclass(frozen=True)
class TypeChars:
    """Send these characters, one at a time, with the usual per-character delay.

    ``intended`` is ``False`` for a slip - characters typed only so they can be
    taken back again. The distinction exists so a dry run and the run log can
    show a mistake as a mistake.
    """

    text: str
    intended: bool = True


@dataclass(frozen=True)
class Undo:
    """Press backspace ``count`` times, pausing ``pause_ms`` after each."""

    count: int
    pause_ms: float = 0.0


@dataclass(frozen=True)
class Hesitate:
    """Pause without typing anything."""

    duration_ms: float


#: One step of a typing plan.
TypingStep = TypeChars | Undo | Hesitate


@dataclass(frozen=True)
class TypingStyle:
    """How imperfectly to type. The default is perfectly.

    ``typo_rate`` and ``hesitation_rate`` are probabilities per eligible
    character, so 0.02 is "about one in fifty". Everything else is milliseconds.
    """

    #: Probability that a letter is mistyped. 0 disables mistakes entirely.
    typo_rate: float = 0.0
    #: How many further characters may be typed before the mistake is noticed.
    typo_notice_chars: int = 2
    #: Pause between making a mistake and starting to correct it.
    notice_pause_ms: float = 220.0
    notice_pause_jitter_ms: float = 140.0
    #: Pause after each backspace, and before typing resumes.
    correction_pause_ms: float = 90.0
    correction_pause_jitter_ms: float = 45.0
    #: Probability of a longer pause before a character, as if thinking.
    hesitation_rate: float = 0.0
    hesitation_ms: float = 450.0
    hesitation_jitter_ms: float = 250.0

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        for name in ("typo_rate", "hesitation_rate"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                issues.append(
                    ValidationIssue(
                        "typing.rate",
                        f"{name} must be between 0 and 1, got {value}",
                        "typing",
                    )
                )
        for name in (
            "notice_pause_ms",
            "notice_pause_jitter_ms",
            "correction_pause_ms",
            "correction_pause_jitter_ms",
            "hesitation_ms",
            "hesitation_jitter_ms",
        ):
            value = float(getattr(self, name))
            if value < 0:
                issues.append(
                    ValidationIssue(
                        "typing.negative", f"{name} must be >= 0, got {value}", "typing"
                    )
                )
        if not 0 <= self.typo_notice_chars <= 8:
            issues.append(
                ValidationIssue(
                    "typing.notice_chars",
                    f"typo_notice_chars must be between 0 and 8, got {self.typo_notice_chars}",
                    "typing",
                )
            )
        if issues:
            raise ValidationError(issues)

    @classmethod
    def natural(cls, *, typo_rate: float = 0.02, hesitation_rate: float = 0.02) -> TypingStyle:
        """A starting point for typing that is uneven and occasionally wrong."""
        return cls(typo_rate=typo_rate, hesitation_rate=hesitation_rate)

    @property
    def is_exact(self) -> bool:
        """True when the style types the text once, straight through."""
        return self.typo_rate <= 0 and self.hesitation_rate <= 0

    def with_changes(self, **changes: object) -> TypingStyle:
        return replace(self, **changes)  # type: ignore[arg-type]


def plan_typing(
    text: str, style: TypingStyle, rng: random.Random | None = None
) -> tuple[TypingStep, ...]:
    """Turn ``text`` into the keystrokes that produce it.

    Deterministic for a given ``rng``: the same seed and the same text always
    give the same plan, which is what makes a seeded run reproducible and these
    steps testable.
    """
    if style.is_exact or not text:
        return (TypeChars(text),) if text else ()
    return _Planner(style, rng or random.Random()).plan(text)


def replay(steps: tuple[TypingStep, ...]) -> str:
    """The text a step sequence leaves behind. Used by the tests as an oracle."""
    buffer: list[str] = []
    for step in steps:
        if isinstance(step, TypeChars):
            buffer.extend(step.text)
        elif isinstance(step, Undo):
            del buffer[len(buffer) - step.count :]
    return "".join(buffer)


class _Planner:
    """Builds the step list. One instance per :func:`plan_typing` call."""

    def __init__(self, style: TypingStyle, rng: random.Random) -> None:
        self._style = style
        self._rng = rng

    def plan(self, text: str) -> tuple[TypingStep, ...]:
        steps: list[TypingStep] = []
        pending: list[str] = []
        # Lines are planned separately so that no slip, and no backspace that
        # takes one back, can ever reach across a newline.
        for index, line in enumerate(text.split("\n")):
            if index:
                pending.append("\n")
            self._plan_line(line, steps, pending)
        _flush(steps, pending)
        return tuple(steps)

    def _plan_line(self, line: str, steps: list[TypingStep], pending: list[str]) -> None:
        index = 0
        correcting = False
        while index < len(line):
            char = line[index]
            if self._hesitates():
                _flush(steps, pending)
                steps.append(Hesitate(self._sample(
                    self._style.hesitation_ms, self._style.hesitation_jitter_ms
                )))
            if not correcting and self._mistypes(char):
                slip = self._slip(line, index)
                if slip is not None:
                    _flush(steps, pending)
                    steps.extend(self._correction(slip))
                    # The next character is typed correctly, so a stubborn seed
                    # cannot mistype the same position over and over.
                    correcting = True
                    continue
            pending.append(char)
            index += 1
            correcting = False

    def _correction(self, slip: str) -> list[TypingStep]:
        style = self._style
        return [
            TypeChars(slip, intended=False),
            Hesitate(self._sample(style.notice_pause_ms, style.notice_pause_jitter_ms)),
            Undo(
                len(slip),
                self._sample(style.correction_pause_ms, style.correction_pause_jitter_ms),
            ),
        ]

    def _slip(self, line: str, index: int) -> str | None:
        """The characters typed by mistake at ``index``, or ``None`` for none.

        Whatever is returned is removed again by exactly ``len`` backspaces, and
        typing then resumes at ``index``, so the intended text is unaffected.
        """
        char = line[index]
        choices = ["substitute", "double"]
        following = line[index + 1] if index + 1 < len(line) else ""
        if _can_mistype(following) and following != char:
            choices.append("transpose")
        kind = self._rng.choice(choices)

        if kind == "substitute":
            wrong = self._neighbour(char)
            if wrong is None:
                return None
            return wrong + self._continues(line, index + 1)
        if kind == "double":
            return char + char + self._continues(line, index + 1)
        return following + char + self._continues(line, index + 2)

    def _continues(self, line: str, index: int) -> str:
        """Characters typed after the slip, before it is noticed."""
        limit = self._rng.randint(0, self._style.typo_notice_chars)
        taken: list[str] = []
        for char in line[index : index + limit]:
            if char in _NOT_UNDOABLE:
                break
            taken.append(char)
        return "".join(taken)

    def _neighbour(self, char: str) -> str | None:
        keys = NEIGHBOURS.get(char.lower())
        if not keys:
            return None
        wrong = self._rng.choice(keys)
        return wrong.upper() if char.isupper() else wrong

    def _mistypes(self, char: str) -> bool:
        return _can_mistype(char) and self._rng.random() < self._style.typo_rate

    def _hesitates(self) -> bool:
        return (
            self._style.hesitation_rate > 0 and self._rng.random() < self._style.hesitation_rate
        )

    def _sample(self, base: float, jitter: float) -> float:
        if jitter <= 0:
            return max(0.0, base)
        return max(0.0, self._rng.uniform(base - jitter, base + jitter))


def _can_mistype(char: str) -> bool:
    """Only letters are mistyped.

    Punctuation, whitespace and newlines are left alone: a stray bracket or
    quote is not a one-for-one trade in an editor that closes pairs, and a stray
    newline in a code editor drags the auto-indent along with it.
    """
    return bool(char) and char.isalpha() and char.lower() in NEIGHBOURS


def _flush(steps: list[TypingStep], pending: list[str]) -> None:
    if pending:
        steps.append(TypeChars("".join(pending)))
        pending.clear()


__all__ = [
    "NEIGHBOURS",
    "Hesitate",
    "TypeChars",
    "TypingStep",
    "TypingStyle",
    "Undo",
    "plan_typing",
    "replay",
]
