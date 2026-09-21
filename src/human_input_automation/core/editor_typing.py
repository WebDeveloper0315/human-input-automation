"""Deciding which keystrokes type a block of code into an editor.

An editor that indents new lines and closes brackets is doing part of the
typing for you. The cheapest way through it - and the way a person actually
works - is to let it: keep the indentation it has just inserted when that is
already the right one, add or remove only the difference when it is not, and
walk over the closing bracket it wrote instead of deleting it and typing the
same character again a few lines later.

Doing that means knowing what the editor did without being able to look. Two
facts are enough for the common case, and both are inputs rather than guesses:
how wide one level of indentation is, and whether the editor closes brackets.
From those, this module predicts the state the caret is in after every Enter
and plans the keystrokes that turn it into the next line of the source.

The planning is a pure function of the text, which is what makes it testable:
:func:`plan_code_typing` returns the whole keystroke sequence, and the handler
that executes it holds no logic of its own.

**Where a prediction is wrong**, the result is a line indented differently from
the source. That is visible and it is recoverable; no text of the user's is
removed to achieve it. An editor whose indentation rules cannot be predicted -
or a source this module reads wrongly - is what :attr:`IndentMode.RECLAIM` is
for: it types over whatever the editor inserted and assumes nothing, at the
cost of a chord and an indent on every line.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd

from .actions import AUTO_CLOSED_PAIRS, IndentMode, PairMode, TypeCode
from .keys import Key

#: Characters that, at the end of a line, make an editor indent the next one.
#: The brackets cover the C family; the colon covers Python and YAML.
INDENT_AFTER = "([{:"

#: Fallback when a block's own indentation says nothing about how wide a level
#: is - a single line, or no indentation at all.
DEFAULT_INDENT_WIDTH = 4

#: Where an editor stops closing brackets for you: inside a string, and after a
#: comment marker. Both are conventions rather than rules, which is why reading
#: too few is the failure the scanner below is built to prefer.
_QUOTES = "\"'`"
_LINE_COMMENTS = ("//", "#")


@dataclass(frozen=True)
class Emit:
    """Type these characters, through whatever typing style the run has."""

    text: str


@dataclass(frozen=True)
class Press:
    """Press and release a named key, ``count`` times."""

    key: Key
    count: int = 1


@dataclass(frozen=True)
class Chord:
    """Send a shortcut in ``"shift+home"`` notation."""

    shortcut: str


#: One planned keystroke, or one run of typed characters.
EditorStep = Emit | Press | Chord


# ---------------------------------------------------------------------------
# Reading the source
# ---------------------------------------------------------------------------


def open_brackets(line: str) -> str:
    """The brackets ``line`` opens and leaves open, outermost first.

    That is exactly what an editor has sitting to the right of the caret at the
    end of the line: the ones we close ourselves are typed over as we go, and
    only the outstanding ones survive.

    Brackets inside a string or after a comment marker are skipped, because an
    editor configured by language does not close those either. Where the guess
    is wrong it is wrong downwards - an unterminated quote stops the scan - so
    the reading comes out short and a bracket is left behind, rather than long,
    which would spend a Delete press on a character belonging to the user.
    """
    stack: list[str] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char in _QUOTES:
            index = _skip_string(line, index)
            continue
        if any(line.startswith(marker, index) for marker in _LINE_COMMENTS):
            break
        if char in AUTO_CLOSED_PAIRS:
            stack.append(char)
        elif stack and char == AUTO_CLOSED_PAIRS[stack[-1]]:
            stack.pop()
        index += 1
    return "".join(stack)


def unclosed_pairs(line: str) -> int:
    """How many closing brackets the editor is holding at the end of ``line``."""
    return len(open_brackets(line))


def auto_closers(line: str) -> str:
    """What the editor has written to the right of the caret at the end of ``line``.

    The innermost bracket was opened last, so its partner sits nearest the
    caret: ``foo({`` leaves ``})``.
    """
    return "".join(AUTO_CLOSED_PAIRS[bracket] for bracket in reversed(open_brackets(line)))


def infer_indent_width(lines: tuple[str, ...] | list[str]) -> int:
    """How wide one level of indentation is in this block of text.

    The greatest common divisor of the indentations present, which gives 4 for
    a file indented in fours and 2 for one indented in twos, and survives a
    level being skipped. It describes the *source*; the editor's own tab size
    is what actually lands on screen, so ``TypeCode.indent_width`` exists for
    the case where the two differ.
    """
    widths = [len(leading_space(line)) for line in lines if line.strip()]
    step = 0
    for width in widths:
        step = gcd(step, width)
    return step or DEFAULT_INDENT_WIDTH


def leading_space(line: str) -> str:
    """The whitespace a line begins with."""
    return line[: len(line) - len(line.lstrip())]


def _skip_string(line: str, start: int) -> int:
    """Index just past the string starting at ``start``, or the end of the line."""
    quote = line[start]
    index = start + 1
    while index < len(line):
        if line[index] == "\\":
            index += 2
            continue
        if line[index] == quote:
            return index + 1
        index += 1
    return len(line)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReusePlan:
    """Which closing brackets the editor writes, and which we let it keep."""

    #: Line index -> the text the editor will already have put there.
    written: dict[int, str]
    #: Lines whose open brackets are answered by one of those, so the closers
    #: the editor is holding must *not* be deleted at the end of them.
    answered: frozenset[int]

    @property
    def is_empty(self) -> bool:
        return not self.written


def reusable_closer_lines(lines: tuple[str, ...] | list[str]) -> ReusePlan:
    """Which source lines the editor will already have written for us.

    Pressing Enter with brackets open moves them onto a line of their own,
    indented to match the line that opened them. When a later source line
    starts with exactly that, there is nothing to type: the line is already
    there, and the caret only has to walk down onto it.

    The search is a stack, so brackets pair the way they nest. A line is only
    claimed when there is a body between it and its opener: an empty ``{}``
    spread over two lines would mean deleting the blank line the editor leaves
    behind, which is not a saving. Everything unclaimed is deleted as before -
    reusing where the source allows it never means leaving a bracket behind.
    """
    stack: list[tuple[int, str]] = []
    written: dict[int, str] = {}
    answered: set[int] = set()
    for index, line in enumerate(lines):
        if stack:
            opener, expected = stack[-1]
            if index >= opener + 2 and line.startswith(expected):
                written[index] = expected
                answered.add(opener)
                stack.pop()
                continue
        closers = auto_closers(line)
        if closers:
            stack.append((index, leading_space(line) + closers))
    return ReusePlan(written, frozenset(answered))


def plan_code_typing(action: TypeCode) -> tuple[EditorStep, ...]:
    """The keystrokes that type ``action`` into an editor."""
    return _Planner(action).plan()


class _Planner:
    """Walks the source, keeping a model of what the editor has done so far."""

    def __init__(self, action: TypeCode) -> None:
        self.action = action
        self.lines = action.lines
        self.unit = " " * (action.indent_width or infer_indent_width(self.lines))
        # Reuse needs the editor to put a closing bracket on a line of its own,
        # which is an auto-indent behaviour as much as an auto-close one; with
        # the indentation left alone there is no predictable line to walk onto.
        self.reuse = (
            reusable_closer_lines(self.lines)
            if action.pairs is PairMode.REUSE
            and action.indent in (IndentMode.MATCH, IndentMode.RECLAIM)
            else ReusePlan({}, frozenset())
        )
        self.steps: list[EditorStep] = []

    def plan(self) -> tuple[EditorStep, ...]:
        #: The line as the editor now holds it - which is not always the source
        #: line: a blank source line keeps the indentation the editor gave it.
        written = ""

        for index, line in enumerate(self.lines):
            if index:
                self._finish_line(written, index - 1)

            if index in self.reuse.written:
                written = self._walk_onto_closer(index, line)
                continue

            caret_indent = ""
            if index:
                self.steps.append(Press(Key.ENTER))
                caret_indent = self._auto_indent(written)
            written = self._type_line(line, index, caret_indent)

        self._finish_line(written, len(self.lines) - 1)
        return tuple(self.steps)

    # -- one line ----------------------------------------------------------
    def _type_line(self, line: str, index: int, caret_indent: str) -> str:
        """Type ``line`` and return the text the editor now holds for it."""
        if index == 0 or self.action.indent is IndentMode.OFF:
            # The first line is typed where the caret already is: there is no
            # indentation of the editor's there to reconcile, only - possibly -
            # text of the user's that must not be touched.
            self._emit(line)
            return line

        if self.action.indent is IndentMode.EDITOR:
            body = line.lstrip()
            self._emit(body)
            return caret_indent + body

        if self.action.indent is IndentMode.RECLAIM:
            if line.strip():
                self.steps.append(Chord(self.action.line_start_chord))
                self._emit(line)
                return line
            return caret_indent

        return self._match_indent(line, caret_indent)

    def _match_indent(self, line: str, caret_indent: str) -> str:
        """Reconcile the editor's indentation with the source's, then type."""
        body = line.lstrip()
        if not body:
            # Nothing to type, and nothing worth spending keystrokes on: the
            # editor's indentation on an otherwise blank line is trailing
            # whitespace, which is what a person leaves there too.
            return caret_indent

        desired = leading_space(line)
        if desired == caret_indent:
            pass  # the editor already did it - the point of this whole mode
        elif desired.startswith(caret_indent):
            self._emit(desired[len(caret_indent) :])
        else:
            # Less indentation than the editor chose, or a different mixture of
            # tabs and spaces. Outdenting would assume the editor's tab size
            # matches ours; selecting the line's indentation and typing over it
            # assumes nothing, and this is the uncommon case.
            self.steps.append(Chord(self.action.line_start_chord))
            self._emit(desired)
        self._emit(body)
        return line

    def _walk_onto_closer(self, index: int, line: str) -> str:
        """Step down onto a closing bracket the editor has already written."""
        expected = self.reuse.written[index]
        self.steps.append(Press(Key.DOWN))
        self.steps.append(Press(Key.END))
        self._emit(line[len(expected) :])
        return line

    def _finish_line(self, written: str, index: int) -> None:
        """Clear up after a line, before leaving it.

        The Escape comes before every Enter *and* before every walk downwards:
        a completion popup swallows both, accepting a suggestion where a new
        line or a movement was meant.
        """
        if self.action.pairs is not PairMode.OFF and index not in self.reuse.answered:
            outstanding = unclosed_pairs(written)
            if outstanding:
                self.steps.append(Press(Key.DELETE, outstanding))
        self._dismiss()

    # -- the editor's half --------------------------------------------------
    def _auto_indent(self, previous: str) -> str:
        """Where the editor puts the caret on the line after ``previous``."""
        if self.action.indent in (IndentMode.OFF, IndentMode.EDITOR):
            return ""
        content = previous.rstrip()
        if content and content[-1] in INDENT_AFTER:
            return leading_space(previous) + self.unit
        return leading_space(previous)

    # -- emitting ----------------------------------------------------------
    def _emit(self, text: str) -> None:
        if text:
            self.steps.append(Emit(text))

    def _dismiss(self) -> None:
        if self.action.dismiss_suggestions:
            self.steps.append(Press(Key.ESC))


def keystroke_count(steps: tuple[EditorStep, ...]) -> int:
    """How many key presses a plan is, counting one per typed character."""
    total = 0
    for step in steps:
        if isinstance(step, Emit):
            total += len(step.text)
        elif isinstance(step, Press):
            total += step.count
        else:
            total += len(step.shortcut.split("+"))
    return total


__all__ = [
    "DEFAULT_INDENT_WIDTH",
    "INDENT_AFTER",
    "Chord",
    "EditorStep",
    "Emit",
    "Press",
    "auto_closers",
    "infer_indent_width",
    "keystroke_count",
    "leading_space",
    "open_brackets",
    "plan_code_typing",
    "reusable_closer_lines",
    "unclosed_pairs",
]
