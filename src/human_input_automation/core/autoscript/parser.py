"""Reading AutoScript: Markdown text in, a :class:`~.model.Script` out.

The rules are ``docs/AUTOSCRIPT.md`` §5. Two things shape how this is written:

* **Every problem is reported, with its line.** Scripts are long and are often
  written by an assistant; a parser that stops at the first mistake turns one
  review into twenty. Problems are collected, the step that caused one is kept
  as an :class:`Unparsed` placeholder, and reading carries on.
* **Nothing is guessed.** An unknown verb is an error with a suggestion, never
  a best-effort interpretation. What a line is - step, directive, table, block
  or prose - is decided by its shape alone, never by whether its content
  happens to parse.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..errors import Severity, ValidationError, ValidationIssue
from ..keys import KeyLike, normalize_key, parse_shortcut
from .model import (
    OUTPUT,
    Block,
    Button,
    Call,
    Click,
    Comparison,
    Expect,
    Find,
    ForEach,
    KeyClick,
    KeyDown,
    KeyUp,
    Locator,
    MoveTarget,
    MoveTo,
    Note,
    Point,
    PositionVariable,
    PressButton,
    Read,
    Record,
    ReleaseButton,
    Repeat,
    Role,
    Routine,
    Run,
    Screenshot,
    Script,
    Scroll,
    Stage,
    Step,
    Table,
    Template,
    TypeBlock,
    TypeTable,
    TypeText,
    UseApp,
    Wait,
    WaitFor,
    WaitForWindow,
)

#: Every verb a step can start with. Used for "did you mean" suggestions.
VERBS = (
    "App:",
    "move to",
    "left-click",
    "right-click",
    "middle-click",
    "press-button",
    "release-button",
    "scroll",
    "type",
    "key-click",
    "key-down",
    "key-up",
    "run",
    "wait",
    "screenshot",
    "find",
    "read",
    "record",
    "expect",
    "do",
    "for each",
    "repeat",
)

#: Platforms a script may declare.
PLATFORMS = {"macos": "macOS", "windows": "Windows", "linux": "Linux"}

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_LIST_ITEM = re.compile(r"^(\s*)[-*]\s+(.*?)\s*$")
_EMPTY_LIST_ITEM = re.compile(r"^(\s*)[-*]\s*$")
_DIRECTIVE = re.compile(r"^(App|Platform|Table|Block):\s*(.*?)\s*$")
_ROUTINE = re.compile(r"^Routine:\s*(?P<name>.+?)\s*\((?P<params>[^()]*)\)\s*$")
_APP = re.compile(r"^(?P<name>.+?)(?:\s*\((?P<terminal>terminal)\))?$")
_NOTE = re.compile(r"^\s*>\s*(?P<kind>CHECK|UNSUPPORTED):\s*(?P<text>.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Unparsed(Step):
    """A step that could not be read. Kept so later problems are not caused by
    it: whatever name it looked like it was assigning is still treated as
    assigned, so one typo does not become a cascade of unknown variables."""

    text: str
    assigns: str | None = None


@dataclass(frozen=True)
class ParseResult:
    script: Script
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def ok(self) -> bool:
        return not self.errors


class StepSyntaxError(Exception):
    """One step does not parse. Carries a message written for the author."""


def error(code: str, line: int, message: str) -> ValidationIssue:
    return ValidationIssue(code, message, f"line {line}", Severity.ERROR)


def warning(code: str, line: int, message: str) -> ValidationIssue:
    return ValidationIssue(code, message, f"line {line}", Severity.WARNING)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str  # "string", "literal", "var", "op", "punct", "word"
    value: str


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<string>"(?:\\.|[^"\\])*")
      | (?P<literal>``\s?(?:(?!``).)*?\s?``|`[^`]*`)
      | (?P<var>\{\{[A-Za-z_][A-Za-z0-9_]*\}\})
      | (?P<op>==|!=|>=|<=|>|<)
      | (?P<punct>[,=:])
      | (?P<word>[^\s",=:`<>!]+)
    )""",
    re.VERBOSE,
)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            remainder = text[position:].lstrip()
            if remainder.startswith('"'):
                raise StepSyntaxError('a quoted string is never closed - add the missing `"`')
            if remainder.startswith("`"):
                raise StepSyntaxError("a backticked literal is never closed - add the missing `")
            raise StepSyntaxError(f"cannot read {remainder[:20]!r} here")
        kind = match.lastgroup or "word"
        raw = match.group(kind)
        tokens.append(Token(kind, _decode(kind, raw)))
        position = match.end()
    return tokens


def _decode(kind: str, raw: str) -> str:
    if kind == "string":
        # Only \" and \\ are escapes. Anything else keeps its backslash, which
        # is what lets a regular expression like "\d+" be written as it reads.
        return re.sub(
            r"\\(.)", lambda m: m.group(1) if m.group(1) in '"\\' else m.group(0), raw[1:-1]
        )
    if kind == "literal":
        if raw.startswith("``"):
            inner = raw[2:-2]
            return inner[1:-1] if inner.startswith(" ") and inner.endswith(" ") else inner
        return raw[1:-1]
    if kind == "var":
        return raw[2:-2]
    return raw


class _Cursor:
    """Walks a step's tokens, with errors that say what was expected."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self, offset: int = 0) -> Token | None:
        position = self.index + offset
        return self.tokens[position] if position < len(self.tokens) else None

    def next(self, what: str) -> Token:
        token = self.peek()
        if token is None:
            raise StepSyntaxError(f"expected {what}, but the step ends here")
        self.index += 1
        return token

    def word(self, *expected: str) -> str:
        token = self.next(" or ".join(repr(word) for word in expected) or "a word")
        if token.kind != "word" or (expected and token.value not in expected):
            options = " or ".join(repr(word) for word in expected)
            raise StepSyntaxError(f"expected {options}, found {_show(token)}")
        return token.value

    def at_word(self, *words: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == "word" and token.value in words

    def text(self, what: str, *, allow_var: bool = False, allow_literal: bool = True) -> Template:
        token = self.next(what)
        kinds = (
            {"string"}
            | ({"literal"} if allow_literal else set())
            | ({"var"} if allow_var else set())
        )
        if token.kind not in kinds:
            raise StepSyntaxError(f"expected {what} in double quotes, found {_show(token)}")
        return Template("{{" + token.value + "}}" if token.kind == "var" else token.value)

    def name(self, what: str) -> str:
        token = self.next(what)
        if token.kind != "word" or not _IDENTIFIER.match(token.value):
            raise StepSyntaxError(
                f"expected {what} - letters, digits and underscores - found {_show(token)}"
            )
        return token.value

    def number(self, what: str) -> float:
        token = self.next(what)
        if token.kind != "word" or not _NUMBER.match(token.value):
            raise StepSyntaxError(f"expected {what}, found {_show(token)}")
        return float(token.value)

    def punct(self, symbol: str) -> None:
        token = self.next(repr(symbol))
        if token.kind != "punct" or token.value != symbol:
            raise StepSyntaxError(f"expected {symbol!r}, found {_show(token)}")

    def at_punct(self, symbol: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == "punct" and token.value == symbol

    def done(self) -> None:
        token = self.peek()
        if token is not None:
            raise StepSyntaxError(f"unexpected {_show(token)} at the end of the step")


def _show(token: Token) -> str:
    if token.kind == "string":
        return f'"{token.value}"'
    if token.kind == "literal":
        return f"`{token.value}`"
    if token.kind == "var":
        return "{{" + token.value + "}}"
    return repr(token.value)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def parse_step(text: str, line: int) -> Step:
    """Read one step. Raises :class:`StepSyntaxError` with an author's message."""
    app = re.match(r"^App:\s*(.*)$", text)
    if app:
        return _use_app(app.group(1), line)

    cursor = _Cursor(tokenize(text))
    first = cursor.peek()
    if first is None:
        raise StepSyntaxError("the step is empty")
    if first.kind != "word":
        raise StepSyntaxError(f"a step starts with a verb, not {_show(first)}")
    verb = cursor.next("a verb").value
    parser = _VERBS.get(verb)
    if parser is None:
        raise StepSyntaxError(_unknown_verb(verb, text))
    step = parser(cursor, line)
    cursor.done()
    return step


def _unknown_verb(verb: str, text: str) -> str:
    words = [candidate.split()[0] for candidate in VERBS]
    close = difflib.get_close_matches(verb, words, n=1, cutoff=0.6)
    if verb in ("click", "double-click"):
        close = ["left-click"]
    hint = f" Did you mean {close[0]!r}?" if close else ""
    return (
        f"unknown verb {verb!r}.{hint} A list item is always a step - if "
        f"this line is a note, write it without the leading '-', or as a '> ' quote"
    )


def _use_app(rest: str, line: int) -> UseApp:
    match = _APP.match(rest.strip())
    if not rest.strip() or match is None:
        raise StepSyntaxError("App: needs the name of an application")
    return UseApp(line, match.group("name").strip(), bool(match.group("terminal")))


def _locator(cursor: _Cursor) -> Locator:
    role: Role | None = None
    token = cursor.peek()
    if token is not None and token.kind == "word" and token.value in Role._value2member_map_:
        role = Role(cursor.next("a role").value)
    containing = False
    if cursor.at_word("containing"):
        cursor.next("containing")
        containing = True
    label = cursor.text("a label", allow_var=True)
    window: Template | None = None
    if cursor.at_word("in"):
        cursor.next("in")
        cursor.word("window")
        window = cursor.text("a window title", allow_var=True)
    return Locator(label, role, window, containing)


def _timeout(cursor: _Cursor, default: float = 10.0) -> float:
    if not cursor.at_word("up"):
        return default
    cursor.next("up")
    cursor.word("to")
    amount = cursor.number("a number of seconds")
    unit = cursor.word("s", "ms")
    seconds = amount / 1000 if unit == "ms" else amount
    if not 0 < seconds <= 600:
        raise StepSyntaxError(f"a wait may last up to 600 s, not {seconds:g}")
    return seconds


def _step_move(cursor: _Cursor, line: int) -> Step:
    cursor.word("to")
    token = cursor.peek()
    target: MoveTarget
    if token is not None and token.kind == "var":
        target = PositionVariable(cursor.next("a position").value)
    elif token is not None and token.kind == "word" and _NUMBER.match(token.value):
        x = cursor.number("x")
        cursor.punct(",")
        y = cursor.number("y")
        if x != int(x) or y != int(y):
            raise StepSyntaxError("a position is whole pixels, x,y")
        target = Point(int(x), int(y))
    else:
        target = _locator(cursor)
    return MoveTo(line, target)


def _clicker(button: Button) -> Callable[[_Cursor, int], Step]:
    def parse(cursor: _Cursor, line: int) -> Step:
        count = 1
        if cursor.at_word("twice"):
            cursor.next("twice")
            count = 2
        return Click(line, button, count)

    return parse


def _step_press_button(cursor: _Cursor, line: int) -> Step:
    return PressButton(line, Button(cursor.word("left", "right", "middle")))


def _step_release_button(cursor: _Cursor, line: int) -> Step:
    return ReleaseButton(line, Button(cursor.word("left", "right", "middle")))


def _step_scroll(cursor: _Cursor, line: int) -> Step:
    direction = cursor.word("up", "down", "left", "right")
    notches = cursor.number("a number of notches")
    if notches != int(notches) or not 1 <= notches <= 100:
        raise StepSyntaxError("scroll takes a whole number of notches from 1 to 100")
    return Scroll(line, direction, int(notches))


def _step_type(cursor: _Cursor, line: int) -> Step:
    if cursor.at_word("block"):
        cursor.next("block")
        return TypeBlock(line, str(cursor.text("a block name", allow_literal=False)))
    if cursor.at_word("table"):
        cursor.next("table")
        return TypeTable(line, str(cursor.text("a table name", allow_literal=False)))
    return TypeText(line, cursor.text("the text to type", allow_var=True))


def _keys_rest(cursor: _Cursor) -> str:
    rest = cursor.tokens[cursor.index :]
    cursor.index = len(cursor.tokens)
    written = "".join(token.value for token in rest)
    if not written:
        raise StepSyntaxError("expected a key or a chord such as cmd+space")
    return written


def _checked_keys(written: str) -> tuple[KeyLike, ...]:
    try:
        return tuple(parse_shortcut(written, location="key"))
    except ValidationError as problem:
        raise StepSyntaxError(problem.issues[0].message) from None


def _step_key_click(cursor: _Cursor, line: int) -> Step:
    written = _keys_rest(cursor)
    return KeyClick(line, _checked_keys(written), written)


def _single_key(cursor: _Cursor) -> KeyLike:
    written = _keys_rest(cursor)
    try:
        return normalize_key(written, location="key")
    except ValidationError as problem:
        raise StepSyntaxError(problem.issues[0].message) from None


def _step_key_down(cursor: _Cursor, line: int) -> Step:
    return KeyDown(line, _single_key(cursor))


def _step_key_up(cursor: _Cursor, line: int) -> Step:
    return KeyUp(line, _single_key(cursor))


def _step_run(cursor: _Cursor, line: int) -> Step:
    return Run(line, cursor.text("the command", allow_var=False))


def _step_wait(cursor: _Cursor, line: int) -> Step:
    if not cursor.at_word("for"):
        amount = cursor.number("how long, e.g. 300 ms or 2 s")
        unit = cursor.word("ms", "s")
        milliseconds = amount if unit == "ms" else amount * 1000
        if not 0 <= milliseconds <= 600_000:
            raise StepSyntaxError("a wait lasts between 0 ms and 600 s")
        return Wait(line, milliseconds)
    cursor.next("for")
    if (
        cursor.at_word("window")
        and (following := cursor.peek(1)) is not None
        and following.kind
        in (
            "string",
            "var",
        )
    ):
        cursor.next("window")
        title = cursor.text("a window title", allow_var=True)
        return WaitForWindow(line, title, _timeout(cursor))
    locator = _locator(cursor)
    return WaitFor(line, locator, _timeout(cursor))


def _step_screenshot(cursor: _Cursor, line: int) -> Step:
    return Screenshot(line)


def _as_name(cursor: _Cursor) -> str:
    cursor.word("as")
    return cursor.name("a variable name")


def _step_find(cursor: _Cursor, line: int) -> Step:
    locator = _locator(cursor)
    return Find(line, locator, _as_name(cursor))


def _step_read(cursor: _Cursor, line: int) -> Step:
    if cursor.at_word(OUTPUT):
        cursor.next(OUTPUT)
        return Read(line, None, _as_name(cursor))
    locator = _locator(cursor)
    return Read(line, locator, _as_name(cursor))


def _value(cursor: _Cursor, what: str) -> Template:
    token = cursor.next(what)
    if token.kind in ("string", "literal"):
        return Template(token.value)
    if token.kind == "var":
        return Template("{{" + token.value + "}}")
    if token.kind == "word" and _NUMBER.match(token.value):
        return Template(token.value)
    raise StepSyntaxError(
        f"expected {what} - quoted, {{{{name}}}} or a number - found {_show(token)}"
    )


def _assignments(cursor: _Cursor, what: str) -> tuple[tuple[str, Template], ...]:
    pairs: list[tuple[str, Template]] = []
    while True:
        name = cursor.name(f"a {what} name")
        cursor.punct("=")
        pairs.append((name, _value(cursor, f"the value of {name}")))
        if not cursor.at_punct(","):
            break
        cursor.next(",")
    names = [name for name, _ in pairs]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise StepSyntaxError(f"{what} {', '.join(duplicates)} given more than once")
    return tuple(pairs)


def _step_record(cursor: _Cursor, line: int) -> Step:
    columns = _assignments(cursor, "column")
    cursor.word("into")
    table = str(cursor.text("a table name", allow_literal=False))
    return Record(line, columns, table)


def _step_expect(cursor: _Cursor, line: int) -> Step:
    subject: str | Locator
    token = cursor.peek()
    if token is not None and token.kind == "word" and token.value == OUTPUT:
        cursor.next(OUTPUT)
        subject = OUTPUT
    elif token is not None and token.kind == "var":
        subject = cursor.next("a variable").value
    else:
        subject = _locator(cursor)

    comparison = _comparison(cursor)
    is_screen = isinstance(subject, Locator)
    if comparison in (Comparison.EXISTS, Comparison.NOT_EXISTS):
        if not is_screen:
            raise StepSyntaxError("only something on screen can exist - write it in quotes")
        return Expect(line, subject, comparison)
    if is_screen:
        raise StepSyntaxError(
            f"something on screen can only be checked with 'exists' or 'does not exist', "
            f"not {comparison.value!r}; to check its text, read it first"
        )
    if subject == OUTPUT and comparison not in (
        Comparison.CONTAINS,
        Comparison.NOT_CONTAINS,
        Comparison.MATCHES,
    ):
        raise StepSyntaxError(
            "output supports 'contains', 'does not contain' and 'matches'; "
            "to compare it, 'read output as' a name first"
        )
    if comparison.is_numeric:
        return Expect(line, subject, comparison, cursor.number("a number"))
    if comparison in (Comparison.EQUAL, Comparison.NOT_EQUAL):
        following = cursor.peek()
        if following is not None and following.kind == "word" and _NUMBER.match(following.value):
            return Expect(line, subject, comparison, cursor.number("a number"))
    value = _value(cursor, "what to compare with")
    if comparison is Comparison.MATCHES and value.is_constant:
        try:
            re.compile(str(value))
        except re.error as problem:
            raise StepSyntaxError(
                f"the pattern is not a valid regular expression: {problem}"
            ) from None
    return Expect(line, subject, comparison, value)


def _comparison(cursor: _Cursor) -> Comparison:
    token = cursor.next("a comparison such as contains, exists or ==")
    if token.kind == "op":
        return Comparison(token.value)
    if token.kind == "word":
        if token.value in ("contains", "exists", "matches"):
            return Comparison(token.value)
        if token.value == "does":
            cursor.word("not")
            follow = cursor.word("contain", "exist")
            return Comparison.NOT_CONTAINS if follow == "contain" else Comparison.NOT_EXISTS
    raise StepSyntaxError(
        f"expected contains, does not contain, exists, does not exist, matches "
        f"or a comparison (== != > >= < <=), found {_show(token)}"
    )


def _step_do(cursor: _Cursor, line: int) -> Step:
    routine = str(cursor.text("a routine name", allow_literal=False))
    arguments: tuple[tuple[str, Template], ...] = ()
    if cursor.at_word("with"):
        cursor.next("with")
        arguments = _assignments(cursor, "parameter")
    return Call(line, routine, arguments)


def _step_for(cursor: _Cursor, line: int) -> Step:
    cursor.word("each")
    cursor.word("row")
    cursor.word("in")
    table = str(cursor.text("a table name", allow_literal=False))
    if not cursor.at_punct(":"):
        raise StepSyntaxError("'for each row in' ends with ':' and has its steps nested under it")
    cursor.next(":")
    return ForEach(line, table)


def _step_repeat(cursor: _Cursor, line: int) -> Step:
    times = cursor.number("how many times")
    if times != int(times) or not 1 <= times <= 1000:
        raise StepSyntaxError("repeat takes a whole number from 1 to 1000")
    cursor.word("times")
    if not cursor.at_punct(":"):
        raise StepSyntaxError("'repeat N times' ends with ':' and has its steps nested under it")
    cursor.next(":")
    return Repeat(line, int(times))


_VERBS: dict[str, Callable[[_Cursor, int], Step]] = {
    "move": _step_move,
    "left-click": _clicker(Button.LEFT),
    "right-click": _clicker(Button.RIGHT),
    "middle-click": _clicker(Button.MIDDLE),
    "press-button": _step_press_button,
    "release-button": _step_release_button,
    "scroll": _step_scroll,
    "type": _step_type,
    "key-click": _step_key_click,
    "key-down": _step_key_down,
    "key-up": _step_key_up,
    "run": _step_run,
    "wait": _step_wait,
    "screenshot": _step_screenshot,
    "find": _step_find,
    "read": _step_read,
    "record": _step_record,
    "expect": _step_expect,
    "do": _step_do,
    "for": _step_for,
    "repeat": _step_repeat,
}


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


@dataclass
class _Item:
    line: int
    indent: int
    text: str


@dataclass
class _Section:
    heading: str
    line: int
    routine: tuple[str, tuple[str, ...]] | None = None
    items: list[_Item] = field(default_factory=list)


class _DocumentReader:
    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.issues: list[ValidationIssue] = []
        self.title: str | None = None
        self.title_line = 0
        self.platform: str | None = None
        self.sections: list[_Section] = []
        self.preamble: list[_Item] = []
        self.tables: dict[str, Table] = {}
        self.blocks: dict[str, Block] = {}
        self.notes: list[Note] = []

    # -- pass 1: shape of every line -----------------------------------------
    def read(self) -> None:
        index = 0
        while index < len(self.lines):
            index = self._line(index)

    def _line(self, index: int) -> int:
        raw = self.lines[index]
        number = index + 1

        if _FENCE.match(raw):
            return self._skip_fence(index)
        note = _NOTE.match(raw)
        if note:
            self.notes.append(Note(note.group("kind"), number, note.group("text").strip()))
            return index + 1

        heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", raw)
        if heading:
            self._heading(len(heading.group(1)), heading.group(2), number)
            return index + 1

        directive = _DIRECTIVE.match(raw)
        if directive:
            return self._directive(directive.group(1), directive.group(2), index)

        item = _LIST_ITEM.match(raw)
        if item:
            self._item(_Item(number, len(item.group(1).expandtabs(4)), item.group(2)))
        elif _EMPTY_LIST_ITEM.match(raw):
            self.issues.append(error("script.empty_step", number, "a list item with no step"))
        return index + 1

    def _heading(self, level: int, text: str, line: int) -> None:
        if level == 1:
            if self.title is not None:
                self.issues.append(
                    error(
                        "script.second_title",
                        line,
                        f"a second '# ' title; the first is on line {self.title_line}",
                    )
                )
            elif self.sections:
                self.issues.append(
                    error("script.late_title", line, "the '# ' title must come before every stage")
                )
            else:
                self.title, self.title_line = text, line
            return
        if level > 2:
            return  # ### and deeper are prose: a heading inside a stage
        routine = re.match(r"^Routine\b", text)
        if routine:
            match = _ROUTINE.match(text)
            if match is None:
                self.issues.append(
                    error(
                        "script.routine_heading",
                        line,
                        "a routine heading is '## Routine: name (param, param)' - "
                        "the parentheses are required, empty for no parameters",
                    )
                )
                self.sections.append(_Section(text, line, routine=(text, ())))
                return
            params = tuple(p.strip() for p in match.group("params").split(",") if p.strip())
            for param in params:
                if not _IDENTIFIER.match(param):
                    self.issues.append(
                        error(
                            "script.parameter_name",
                            line,
                            f"parameter {param!r} must be letters, digits and underscores",
                        )
                    )
            duplicates = sorted({p for p in params if params.count(p) > 1})
            if duplicates:
                self.issues.append(
                    error(
                        "script.parameter_twice",
                        line,
                        f"parameter {', '.join(duplicates)} listed twice",
                    )
                )
            self.sections.append(_Section(text, line, routine=(match.group("name"), params)))
            return
        self.sections.append(_Section(text, line))

    def _directive(self, kind: str, value: str, index: int) -> int:
        line = index + 1
        if kind == "Platform":
            platform = PLATFORMS.get(value.lower())
            if platform is None:
                self.issues.append(
                    error(
                        "script.platform",
                        line,
                        f"unknown platform {value!r}; use macOS, Windows or Linux",
                    )
                )
            elif self.platform is not None:
                self.issues.append(
                    error("script.second_platform", line, "Platform: is given twice")
                )
            elif self.sections:
                self.issues.append(
                    error("script.late_platform", line, "Platform: belongs before the first stage")
                )
            else:
                self.platform = platform
            return index + 1
        if kind == "App":
            self._item(_Item(line, 0, f"App: {value}"))
            return index + 1
        name = value.strip()
        if not name:
            self.issues.append(error("script.unnamed", line, f"{kind}: needs a name"))
            return index + 1
        if kind == "Table":
            return self._table(name, index)
        return self._block(name, index)

    def _item(self, item: _Item) -> None:
        if self.sections:
            self.sections[-1].items.append(item)
        elif item.text.startswith("App:"):
            self.preamble.append(item)
        else:
            self.issues.append(
                error("script.step_before_stage", item.line, "a step before the first '## ' stage")
            )

    def _next_content(self, index: int) -> int:
        while index < len(self.lines) and not self.lines[index].strip():
            index += 1
        return index

    def _table(self, name: str, index: int) -> int:
        line = index + 1
        start = self._next_content(index + 1)
        if start >= len(self.lines) or not self.lines[start].lstrip().startswith("|"):
            self.issues.append(
                error(
                    "script.table_missing",
                    line,
                    f"Table: {name} is not followed by a Markdown table",
                )
            )
            return index + 1
        end = start
        while end < len(self.lines) and self.lines[end].lstrip().startswith("|"):
            end += 1
        rows = [_cells(self.lines[i]) for i in range(start, end)]
        if len(rows) < 2 or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
            self.issues.append(
                error(
                    "script.table_shape",
                    start + 1,
                    f"table {name!r} needs a header row and a |---| row",
                )
            )
            return end
        header, body = rows[0], rows[2:]
        for offset, row in enumerate(body):
            if len(row) != len(header):
                self.issues.append(
                    error(
                        "script.table_row",
                        start + 3 + offset,
                        f"table {name!r}: this row has {len(row)} cells, "
                        f"the header has {len(header)}",
                    )
                )
        duplicates = sorted({c for c in header if header.count(c) > 1})
        if duplicates:
            self.issues.append(
                error(
                    "script.table_column_twice",
                    start + 1,
                    f"table {name!r} has column {', '.join(duplicates)} twice",
                )
            )
        for column in header:
            if not _IDENTIFIER.match(column):
                self.issues.append(
                    warning(
                        "script.table_column_name",
                        start + 1,
                        f"table {name!r}: column {column!r} cannot be used as {{{{{column}}}}} "
                        "because it is not letters, digits and underscores",
                    )
                )
        if not body:
            self.issues.append(warning("script.table_empty", line, f"table {name!r} has no rows"))
        self._define(
            self.tables, name, line, Table(name, line, tuple(header), tuple(tuple(r) for r in body))
        )
        return end

    def _block(self, name: str, index: int) -> int:
        line = index + 1
        start = self._next_content(index + 1)
        fence = _FENCE.match(self.lines[start]) if start < len(self.lines) else None
        if fence is None:
            self.issues.append(
                error(
                    "script.block_missing", line, f"Block: {name} is not followed by a fenced block"
                )
            )
            return index + 1
        marker = fence.group(1)
        end = start + 1
        while end < len(self.lines) and not self.lines[end].strip().startswith(marker):
            end += 1
        if end >= len(self.lines):
            self.issues.append(
                error("script.fence_open", start + 1, "this fenced block is never closed")
            )
        self._define(
            self.blocks, name, line, Block(name, line, "\n".join(self.lines[start + 1 : end]))
        )
        return end + 1

    def _skip_fence(self, index: int) -> int:
        marker = _FENCE.match(self.lines[index]).group(1)  # type: ignore[union-attr]
        end = index + 1
        while end < len(self.lines) and not self.lines[end].strip().startswith(marker):
            end += 1
        if end >= len(self.lines):
            self.issues.append(
                error("script.fence_open", index + 1, "this fenced block is never closed")
            )
        return end + 1

    def _define(self, place: dict, name: str, line: int, value: object) -> None:  # type: ignore[type-arg]
        if name in place:
            first = place[name].line
            self.issues.append(
                error("script.defined_twice", line, f"{name!r} is already defined on line {first}")
            )
            return
        place[name] = value

    # -- pass 2: steps, with nesting ------------------------------------------
    def build(self) -> Script:
        stages: list[Stage] = []
        routines: dict[str, Routine] = {}
        for position, section in enumerate(self.sections):
            items = section.items
            if position == 0 and self.preamble:
                items = [*self.preamble, *items]
            steps = self._nest(items)
            if section.routine is not None:
                name, params = section.routine
                routine = Routine(name, section.line, params, steps)
                if name in routines:
                    self.issues.append(
                        error(
                            "script.defined_twice",
                            section.line,
                            f"routine {name!r} is already defined on line {routines[name].line}",
                        )
                    )
                else:
                    routines[name] = routine
            else:
                stages.append(Stage(section.heading, section.line, steps))
        if self.title is None:
            self.issues.append(error("script.no_title", 1, "a script starts with a '# ' title"))
        if not self.sections:
            self.issues.append(
                error("script.no_stages", 1, "a script has at least one '## ' stage")
            )
        return Script(
            title=self.title or "",
            platform=self.platform,
            stages=tuple(stages),
            routines=routines,
            tables=self.tables,
            blocks=self.blocks,
            notes=tuple(self.notes),
        )

    def _nest(self, items: list[_Item]) -> tuple[Step, ...]:
        if not items:
            return ()
        if items[0].indent != 0:
            self.issues.append(
                error("script.indented", items[0].line, "the first step of a stage is not indented")
            )
        steps, _ = self._level(items, 0, items[0].indent)
        return steps

    def _level(self, items: list[_Item], start: int, indent: int) -> tuple[tuple[Step, ...], int]:
        steps: list[Step] = []
        index = start
        while index < len(items):
            item = items[index]
            if item.indent < indent:
                break
            if item.indent > indent:
                self.issues.append(
                    error(
                        "script.indented",
                        item.line,
                        "this step is indented, but nothing above it has steps nested under it",
                    )
                )
                index += 1
                continue
            step = self._step(item)
            index += 1
            if isinstance(step, (ForEach, Repeat)):
                if index < len(items) and items[index].indent > indent:
                    body, index = self._level(items, index, items[index].indent)
                else:
                    body = ()
                    self.issues.append(
                        error(
                            "script.empty_loop",
                            item.line,
                            "nothing is nested under this; its steps go indented below it",
                        )
                    )
                step = (
                    ForEach(step.line, step.table, body)
                    if isinstance(step, ForEach)
                    else Repeat(step.line, step.times, body)
                )
            steps.append(step)
        return tuple(steps), index

    def _step(self, item: _Item) -> Step:
        try:
            return parse_step(item.text, item.line)
        except StepSyntaxError as problem:
            self.issues.append(error("script.step", item.line, str(problem)))
            assigns = re.search(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", item.text)
            return Unparsed(item.line, item.text, assigns.group(1) if assigns else None)


def _cells(row: str) -> list[str]:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", body)]


def parse_script(text: str) -> ParseResult:
    """Read a whole document. Never raises for anything in the text itself."""
    reader = _DocumentReader(text)
    reader.read()
    script = reader.build()
    return ParseResult(script, tuple(sorted(reader.issues, key=_issue_line)))


def _issue_line(issue: ValidationIssue) -> int:
    match = re.search(r"\d+", issue.location)
    return int(match.group()) if match else 0
