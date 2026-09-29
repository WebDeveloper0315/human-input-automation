"""What an AutoScript document means, once it has been read.

The parser turns Markdown text into these; the validator checks them; a runner
will one day perform them. Every node carries the line it came from, because
the only useful answer to "what went wrong?" in a 500-line script is a line
number.

All of it is plain frozen data: no behaviour, no I/O, nothing that could run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from ..keys import KeyLike

#: ``{{name}}`` - and nothing else - is a substitution.
VARIABLE = re.compile(r"(?<!\\)\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


# ---------------------------------------------------------------------------
# Text with substitutions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    """Text that may contain ``{{name}}`` substitutions.

    Kept as the original text plus the names it refers to. Substitution is the
    runner's job; the validator only needs to know which names must exist.
    """

    text: str

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(VARIABLE.findall(self.text)))

    @property
    def is_constant(self) -> bool:
        return not self.names

    def render(self, values: dict[str, str]) -> str:
        """Substitute ``values``; ``\\{{`` stays a literal ``{{``."""
        rendered = VARIABLE.sub(lambda match: values[match.group(1)], self.text)
        return rendered.replace("\\{{", "{{")

    def __str__(self) -> str:
        return self.text


# ---------------------------------------------------------------------------
# What a step can point at
# ---------------------------------------------------------------------------


class Role(StrEnum):
    """What kind of thing a label names, to tell two of the same name apart."""

    BUTTON = "button"
    MENU = "menu"
    ITEM = "item"
    FIELD = "field"
    CHECKBOX = "checkbox"
    TAB = "tab"
    ICON = "icon"
    TEXT = "text"
    WINDOW = "window"


@dataclass(frozen=True)
class Locator:
    """A description of something on screen: ``[role] "label" [in window "T"]``."""

    label: Template
    role: Role | None = None
    window: Template | None = None
    #: Match part of a label rather than the whole of it.
    containing: bool = False

    def describe(self) -> str:
        parts = [self.role.value] if self.role else []
        parts.append(f'containing "{self.label}"' if self.containing else f'"{self.label}"')
        if self.window is not None:
            parts.append(f'in window "{self.window}"')
        return " ".join(parts)


@dataclass(frozen=True)
class Point:
    """A position written out as ``x,y``."""

    x: int
    y: int


@dataclass(frozen=True)
class PositionVariable:
    """A position held in a variable by an earlier ``find``."""

    name: str


#: Where ``move to`` can go.
MoveTarget = Point | PositionVariable | Locator


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """Base for every step. ``line`` is 1-based, in the document."""

    line: int


class Button(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


@dataclass(frozen=True)
class UseApp(Step):
    """``App: Name`` - the application the following steps are for."""

    name: str
    #: Declared a terminal with ``App: Warp (terminal)``.
    declared_terminal: bool = False


@dataclass(frozen=True)
class MoveTo(Step):
    target: MoveTarget


@dataclass(frozen=True)
class Click(Step):
    button: Button
    count: int = 1


@dataclass(frozen=True)
class PressButton(Step):
    button: Button


@dataclass(frozen=True)
class ReleaseButton(Step):
    button: Button


@dataclass(frozen=True)
class Scroll(Step):
    direction: str  # "up", "down", "left" or "right"
    notches: int


@dataclass(frozen=True)
class TypeText(Step):
    text: Template


@dataclass(frozen=True)
class TypeBlock(Step):
    block: str


@dataclass(frozen=True)
class TypeTable(Step):
    table: str


@dataclass(frozen=True)
class KeyClick(Step):
    keys: tuple[KeyLike, ...]
    written: str


@dataclass(frozen=True)
class KeyDown(Step):
    key: KeyLike


@dataclass(frozen=True)
class KeyUp(Step):
    key: KeyLike


@dataclass(frozen=True)
class Run(Step):
    """Sugar: exactly ``type`` the command, then ``key-click enter``."""

    command: Template


@dataclass(frozen=True)
class Wait(Step):
    milliseconds: float


@dataclass(frozen=True)
class WaitFor(Step):
    """Take screenshots until ``locator`` is there, or give up."""

    locator: Locator
    timeout_s: float = 10.0


@dataclass(frozen=True)
class WaitForWindow(Step):
    title: Template
    timeout_s: float = 10.0


@dataclass(frozen=True)
class Screenshot(Step):
    pass


@dataclass(frozen=True)
class Find(Step):
    locator: Locator
    variable: str


#: ``read output as x`` reads the terminal, not a screenshot.
OUTPUT = "output"


@dataclass(frozen=True)
class Read(Step):
    """``read "label" as x``, or ``read output as x`` when ``source`` is None."""

    source: Locator | None
    variable: str


@dataclass(frozen=True)
class Record(Step):
    """``record a={{x}}, b="text" into "Table"`` - one row, named columns."""

    columns: tuple[tuple[str, Template], ...]
    table: str


class Comparison(StrEnum):
    CONTAINS = "contains"
    NOT_CONTAINS = "does not contain"
    EXISTS = "exists"
    NOT_EXISTS = "does not exist"
    MATCHES = "matches"
    EQUAL = "=="
    NOT_EQUAL = "!="
    GREATER = ">"
    GREATER_EQUAL = ">="
    LESS = "<"
    LESS_EQUAL = "<="

    @property
    def is_numeric(self) -> bool:
        return self in (
            Comparison.GREATER,
            Comparison.GREATER_EQUAL,
            Comparison.LESS,
            Comparison.LESS_EQUAL,
        )


@dataclass(frozen=True)
class Expect(Step):
    """Every form in §5.9. ``subject`` is ``output``, a variable, or a locator."""

    subject: str | Locator  # OUTPUT, a variable name, or something on screen
    comparison: Comparison
    #: What it is compared with: text, a pattern or a number. None for exists.
    value: Template | float | None = None


@dataclass(frozen=True)
class Call(Step):
    """``do "routine" with a="x", b="y"``."""

    routine: str
    arguments: tuple[tuple[str, Template], ...] = ()


@dataclass(frozen=True)
class ForEach(Step):
    table: str
    body: tuple[Step, ...] = ()


@dataclass(frozen=True)
class Repeat(Step):
    times: int
    body: tuple[Step, ...] = ()


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    name: str
    line: int
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def row_values(self, index: int) -> dict[str, str]:
        return dict(zip(self.columns, self.rows[index], strict=True))


@dataclass(frozen=True)
class Block:
    name: str
    line: int
    text: str


@dataclass(frozen=True)
class Stage:
    heading: str
    line: int
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True)
class Routine:
    name: str
    line: int
    parameters: tuple[str, ...]
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True)
class Note:
    """A ``> CHECK:`` or ``> UNSUPPORTED:`` line left by whoever converted it."""

    kind: str  # "CHECK" or "UNSUPPORTED"
    line: int
    text: str


@dataclass(frozen=True)
class Script:
    title: str
    platform: str | None
    stages: tuple[Stage, ...]
    routines: dict[str, Routine] = field(default_factory=dict)
    tables: dict[str, Table] = field(default_factory=dict)
    blocks: dict[str, Block] = field(default_factory=dict)
    notes: tuple[Note, ...] = ()

    @property
    def step_count(self) -> int:
        """Steps as written, counting loop bodies once."""
        return sum(_count(stage.steps) for stage in self.stages) + sum(
            _count(routine.steps) for routine in self.routines.values()
        )


def _count(steps: tuple[Step, ...]) -> int:
    total = 0
    for step in steps:
        total += 1
        if isinstance(step, (ForEach, Repeat)):
            total += _count(step.body)
    return total


def walk(steps: tuple[Step, ...]) -> list[Step]:
    """Every step, loop bodies included, in the order they are written."""
    found: list[Step] = []
    for step in steps:
        found.append(step)
        if isinstance(step, (ForEach, Repeat)):
            found.extend(walk(step.body))
    return found
