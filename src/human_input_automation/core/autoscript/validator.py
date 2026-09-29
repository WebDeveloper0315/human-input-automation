"""Checking a parsed script before anything runs.

Parsing answers "is every line well formed?". This answers "does the script
make sense as a whole?" - every name defined before it is used, every routine
called the way it is declared, every table there to loop over, a terminal
wherever a command is run, and every look at the screen made at a screen that
is still current.

That last one is the check this module exists for. ``find`` reads the most
recent screenshot; after a click, a key or a movement, that screenshot may show
a screen that no longer exists. A position read off it is a real position,
pointing at whatever used to be there - a failure that produces no error at
all at run time. So it is caught here, by following what is known about the
screen through every step, loop and routine call, before any input is sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import Severity, ValidationIssue
from .model import (
    OUTPUT,
    Call,
    Click,
    Expect,
    Find,
    ForEach,
    KeyClick,
    KeyDown,
    KeyUp,
    Locator,
    MoveTo,
    PositionVariable,
    PressButton,
    Read,
    Record,
    ReleaseButton,
    Repeat,
    Routine,
    Run,
    Screenshot,
    Script,
    Scroll,
    Step,
    Template,
    TypeBlock,
    TypeTable,
    TypeText,
    UseApp,
    WaitFor,
    WaitForWindow,
    walk,
)
from .parser import Unparsed

#: Applications that are terminals without being declared so (§5.12).
KNOWN_TERMINALS = frozenset(
    name.lower()
    for name in (
        "Terminal",
        "iTerm2",
        "iTerm",
        "Windows Terminal",
        "PowerShell",
        "Command Prompt",
        "GNOME Terminal",
        "Konsole",
        "xterm",
    )
)

#: Steps that may change what is on screen.
_INPUT = (
    UseApp,
    MoveTo,
    Click,
    PressButton,
    ReleaseButton,
    Scroll,
    TypeText,
    TypeBlock,
    TypeTable,
    KeyClick,
    KeyDown,
    KeyUp,
    Run,
    Unparsed,
)


def _error(code: str, line: int, message: str) -> ValidationIssue:
    return ValidationIssue(code, message, f"line {line}", Severity.ERROR)


def _warning(code: str, line: int, message: str) -> ValidationIssue:
    return ValidationIssue(code, message, f"line {line}", Severity.WARNING)


@dataclass
class _Scope:
    """What a step can refer to at the point it runs."""

    #: Variables assigned by ``find`` (positions) and ``read`` (text).
    positions: set[str] = field(default_factory=set)
    texts: set[str] = field(default_factory=set)
    #: Columns of the rows being looped over, innermost last.
    columns: list[set[str]] = field(default_factory=list)
    #: A routine's parameters.
    parameters: set[str] = field(default_factory=set)

    def text_names(self) -> set[str]:
        names = self.texts | self.parameters
        for columns in self.columns:
            names |= columns
        return names

    def copy(self) -> _Scope:
        return _Scope(
            set(self.positions),
            set(self.texts),
            [set(c) for c in self.columns],
            set(self.parameters),
        )


@dataclass
class _RoutineSummary:
    """What calling a routine does to the caller's state."""

    fresh_after: int | str | None = "routine"
    app_after: str | None = None
    changes_app: bool = False
    records: set[str] = field(default_factory=set)
    #: Sends input before it names an application of its own.
    input_before_app: bool = False


class _Validator:
    def __init__(self, script: Script) -> None:
        self.script = script
        self.issues: list[ValidationIssue] = []
        self.terminals = {
            step.name.lower()
            for step in self._every_step()
            if isinstance(step, UseApp) and step.declared_terminal
        } | KNOWN_TERMINALS
        self.recorded_columns = self._recorded_tables()
        self.summaries: dict[str, _RoutineSummary] = {}
        self.used_routines: set[str] = set()
        self.used_tables: set[str] = set()
        self.used_blocks: set[str] = set()

    def _every_step(self) -> list[Step]:
        steps: list[Step] = []
        for stage in self.script.stages:
            steps.extend(walk(stage.steps))
        for routine in self.script.routines.values():
            steps.extend(walk(routine.steps))
        return steps

    # -- whole-document checks ----------------------------------------------
    def run(self) -> tuple[ValidationIssue, ...]:
        if self.script.platform is None:
            self.issues.append(
                _warning(
                    "script.no_platform",
                    1,
                    "no 'Platform:' line; shortcuts mean different things on different "
                    "platforms, so a script should say which one it is for",
                )
            )
        self._check_calls()
        cyclic = self._cycles()
        for name, routine in self.script.routines.items():
            if name not in cyclic:
                self._summarise(routine)
        self._walk_stages()
        self._balance()
        self._unused()
        return tuple(sorted(self.issues, key=_line_of))

    def _recorded_tables(self) -> dict[str, tuple[str, ...]]:
        columns: dict[str, tuple[str, ...]] = {}
        for step in self._every_step():
            if not isinstance(step, Record):
                continue
            names = tuple(name for name, _ in step.columns)
            if step.table in self.script.tables:
                self.issues.append(
                    _error(
                        "script.record_into_declared",
                        step.line,
                        f"{step.table!r} is a declared table, and declared tables do not change; "
                        "record into a table of its own",
                    )
                )
            elif step.table in columns and columns[step.table] != names:
                self.issues.append(
                    _error(
                        "script.record_columns",
                        step.line,
                        f"{step.table!r} was first recorded with columns "
                        f"{', '.join(columns[step.table])}; "
                        "every record into it uses the same columns",
                    )
                )
            else:
                columns.setdefault(step.table, names)
        return columns

    def _check_calls(self) -> None:
        for step in self._every_step():
            if not isinstance(step, Call):
                continue
            self.used_routines.add(step.routine)
            routine = self.script.routines.get(step.routine)
            if routine is None:
                known = ", ".join(sorted(self.script.routines)) or "none are defined"
                self.issues.append(
                    _error(
                        "script.unknown_routine",
                        step.line,
                        f"no routine called {step.routine!r} (routines: {known})",
                    )
                )
                continue
            given = [name for name, _ in step.arguments]
            missing = [p for p in routine.parameters if p not in given]
            extra = [g for g in given if g not in routine.parameters]
            if missing:
                self.issues.append(
                    _error(
                        "script.missing_argument",
                        step.line,
                        f"{step.routine!r} needs {', '.join(missing)}",
                    )
                )
            if extra:
                self.issues.append(
                    _error(
                        "script.unknown_argument",
                        step.line,
                        f"{step.routine!r} has no parameter {', '.join(extra)} "
                        f"(it takes: {', '.join(routine.parameters) or 'nothing'})",
                    )
                )

    def _cycles(self) -> set[str]:
        """Routines that call themselves, directly or through others."""
        graph = {
            name: {step.routine for step in walk(routine.steps) if isinstance(step, Call)}
            for name, routine in self.script.routines.items()
        }
        cyclic: set[str] = set()

        def visit(name: str, path: list[str]) -> None:
            if name in path:
                loop = [*path[path.index(name) :], name]
                if name not in cyclic:
                    cyclic.update(loop)
                    routine = self.script.routines[name]
                    self.issues.append(
                        _error(
                            "script.recursion",
                            routine.line,
                            "routines call each other in a loop: " + " -> ".join(loop),
                        )
                    )
                return
            for callee in graph.get(name, ()):
                if callee in graph:
                    visit(callee, [*path, name])

        for name in graph:
            visit(name, [])
        return cyclic

    def _balance(self) -> None:
        """A key or button held and never let go, within one stage or routine.

        Not an error - the engine releases everything when a run ends - but a
        modifier held across the rest of a stage changes every key after it.
        """
        bodies = [stage.steps for stage in self.script.stages]
        bodies += [routine.steps for routine in self.script.routines.values()]
        for steps in bodies:
            held: dict[object, int] = {}
            for step in walk(steps):
                if isinstance(step, (KeyDown, PressButton)):
                    held[step.key if isinstance(step, KeyDown) else step.button] = step.line
                elif isinstance(step, KeyUp):
                    held.pop(step.key, None)
                elif isinstance(step, ReleaseButton):
                    held.pop(step.button, None)
            for thing, line in held.items():
                self.issues.append(
                    _warning(
                        "script.held",
                        line,
                        f"{thing!s} is pressed here and never released "
                        "in the same stage or routine",
                    )
                )

    def _unused(self) -> None:
        for name, routine in self.script.routines.items():
            if name not in self.used_routines:
                self.issues.append(
                    _warning(
                        "script.unused_routine", routine.line, f"routine {name!r} is never called"
                    )
                )
        for name, table in self.script.tables.items():
            if name not in self.used_tables:
                self.issues.append(
                    _warning("script.unused_table", table.line, f"table {name!r} is never used")
                )
        for name, block in self.script.blocks.items():
            if name not in self.used_blocks:
                self.issues.append(
                    _warning("script.unused_block", block.line, f"block {name!r} is never typed")
                )

    # -- routines --------------------------------------------------------------
    def _summarise(self, routine: Routine) -> _RoutineSummary:
        existing = self.summaries.get(routine.name)
        if existing is not None:
            return existing
        # Placeholder first, so a routine reached again while it is being
        # summarised (only possible through a cycle, already reported) ends.
        self.summaries[routine.name] = _RoutineSummary()
        walker = _Walker(self, routine=routine)
        scope = _Scope(parameters=set(routine.parameters))
        stale: int | str | None = (
            f"the start of routine {routine.name!r}, where nothing on screen is known yet"
        )
        stale, app = walker.body(routine.steps, scope, stale, None, report=True)
        summary = _RoutineSummary(
            fresh_after=stale,
            app_after=app,
            changes_app=any(isinstance(step, UseApp) for step in walk(routine.steps)),
            records={step.table for step in walk(routine.steps) if isinstance(step, Record)},
            input_before_app=self._input_before_app(routine.steps),
        )
        for step in walk(routine.steps):
            if isinstance(step, Call) and step.routine in self.summaries:
                summary.records |= self.summaries[step.routine].records
        self.summaries[routine.name] = summary
        return summary

    def _input_before_app(self, steps: tuple[Step, ...]) -> bool:
        for step in walk(steps):
            if isinstance(step, UseApp):
                return False
            if isinstance(step, _INPUT):
                return True
            if isinstance(step, Call):
                called = self.summaries.get(step.routine)
                if called is not None and called.input_before_app:
                    return True
                if called is not None and called.changes_app:
                    return False
        return False

    def summary(self, name: str) -> _RoutineSummary | None:
        routine = self.script.routines.get(name)
        if routine is None:
            return None
        return self._summarise(routine)

    # -- stages ----------------------------------------------------------------
    def _walk_stages(self) -> None:
        walker = _Walker(self, routine=None)
        scope = _Scope()
        stale: int | str | None = "the start of the script, where nothing on screen is known yet"
        app: str | None = None
        for stage in self.script.stages:
            if not stage.steps:
                self.issues.append(
                    _warning(
                        "script.empty_stage", stage.line, f"stage {stage.heading!r} has no steps"
                    )
                )
            stale, app = walker.body(stage.steps, scope, stale, app, report=True)


class _Walker:
    """Follows one body of steps in the order they run."""

    def __init__(self, owner: _Validator, *, routine: Routine | None) -> None:
        self.owner = owner
        self.routine = routine
        #: Recorded tables that exist by now - only tracked across stages,
        #: since a routine cannot know what its caller recorded.
        self.recorded: set[str] = set()

    def report(self, issue: ValidationIssue, enabled: bool) -> None:
        if enabled:
            self.owner.issues.append(issue)

    def body(
        self,
        steps: tuple[Step, ...],
        scope: _Scope,
        stale: int | str | None,
        app: str | None,
        *,
        report: bool,
    ) -> tuple[int | str | None, str | None]:
        for step in steps:
            stale, app = self.step(step, scope, stale, app, report=report)
        return stale, app

    def step(
        self,
        step: Step,
        scope: _Scope,
        stale: int | str | None,
        app: str | None,
        *,
        report: bool,
    ) -> tuple[int | str | None, str | None]:
        self._names(step, scope, report)

        if self.routine is None and app is None:
            sends_input = isinstance(step, _INPUT) and not isinstance(step, UseApp)
            if isinstance(step, Call):
                called = self.owner.summary(step.routine)
                sends_input = called is not None and called.input_before_app
            if sends_input:
                self.report(
                    _error(
                        "script.input_before_app",
                        step.line,
                        "this sends input before any 'App:' line has said where it goes; "
                        "a script never types into whatever happens to have focus",
                    ),
                    report,
                )

        if stale is not None and self._looks_at_screen(step):
            self.report(_stale(step, stale), report)

        needs_terminal = isinstance(step, Run) or self._reads_output(step)
        if needs_terminal and (app is None or app.lower() not in self.owner.terminals):
            where = (
                f"the current application is {app!r}"
                if app
                else "no application has been named yet"
            )
            what = "run" if isinstance(step, Run) else "output"
            self.report(
                _error(
                    "script.not_a_terminal",
                    step.line,
                    f"'{what}' needs a terminal, and {where}; name one with App: - "
                    "or declare another application one with 'App: Name (terminal)'",
                ),
                report,
            )

        if isinstance(step, Find):
            scope.positions.add(step.variable)
        elif isinstance(step, Read):
            scope.texts.add(step.variable)
        elif isinstance(step, Unparsed) and step.assigns:
            scope.positions.add(step.assigns)
            scope.texts.add(step.assigns)
        elif isinstance(step, Record):
            self.recorded.add(step.table)

        if isinstance(step, UseApp):
            app = step.name
        if isinstance(step, ForEach):
            return self._for_each(step, scope, stale, app, report)
        if isinstance(step, Repeat):
            return self._loop(step.body, scope, stale, app, report, None)
        if isinstance(step, Call):
            summary = self.owner.summary(step.routine)
            if summary is None:
                return step.line, app
            self.recorded |= summary.records
            after = step.line if summary.fresh_after is not None else None
            return after, (summary.app_after if summary.changes_app else app)
        if isinstance(step, (Screenshot, WaitFor, WaitForWindow)):
            return None, app
        if isinstance(step, _INPUT):
            return step.line, app
        return stale, app

    def _for_each(
        self, step: ForEach, scope: _Scope, stale: int | str | None, app: str | None, report: bool
    ) -> tuple[int | str | None, str | None]:
        columns = self._table_columns(step.table, step.line, report)
        return self._loop(step.body, scope, stale, app, report, columns)

    def _loop(
        self,
        body: tuple[Step, ...],
        scope: _Scope,
        stale: int | str | None,
        app: str | None,
        report: bool,
        columns: set[str] | None,
    ) -> tuple[int | str | None, str | None]:
        inner = scope.copy()
        if columns is not None:
            inner.columns.append(columns)
        # The first time round starts from what was known before the loop; every
        # later time round starts from what the body left. A step inside is only
        # safe if it is safe both ways, so the body is first walked quietly to
        # learn how it ends, then walked for real from the worse of the two.
        end_of_first, _ = self.body(body, inner.copy(), stale, app, report=False)
        entry = stale if stale is not None else end_of_first
        end, app_after = self.body(body, inner, entry, app, report=report)
        # Assignments made inside the loop are visible after it.
        scope.positions |= inner.positions
        scope.texts |= inner.texts
        return (end if end is not None else stale), app_after

    # -- what a step refers to ---------------------------------------------------
    def _looks_at_screen(self, step: Step) -> bool:
        if isinstance(step, Find):
            return True
        if isinstance(step, Read):
            return step.source is not None
        if isinstance(step, Expect):
            return isinstance(step.subject, Locator)
        if isinstance(step, MoveTo):
            return isinstance(step.target, Locator)
        return False

    def _reads_output(self, step: Step) -> bool:
        if isinstance(step, Read):
            return step.source is None
        if isinstance(step, Expect):
            return step.subject == OUTPUT
        return False

    def _table_columns(self, table: str, line: int, report: bool) -> set[str]:
        self.owner.used_tables.add(table)
        declared = self.owner.script.tables.get(table)
        if declared is not None:
            return set(declared.columns)
        recorded = self.owner.recorded_columns.get(table)
        if recorded is None:
            known = (
                ", ".join(sorted({*self.owner.script.tables, *self.owner.recorded_columns}))
                or "none"
            )
            self.report(
                _error(
                    "script.unknown_table", line, f"no table called {table!r} (tables: {known})"
                ),
                report,
            )
            return set()
        if self.routine is None and table not in self.recorded:
            self.report(
                _error(
                    "script.table_not_yet_recorded",
                    line,
                    f"nothing has been recorded into {table!r} by this point, so it would be empty",
                ),
                report,
            )
        return set(recorded)

    def _names(self, step: Step, scope: _Scope, report: bool) -> None:
        texts: list[Template] = []
        if isinstance(step, (TypeText,)):
            texts.append(step.text)
        elif isinstance(step, Run):
            texts.append(step.command)
        elif isinstance(step, TypeBlock):
            self.owner.used_blocks.add(step.block)
            block = self.owner.script.blocks.get(step.block)
            if block is None:
                known = ", ".join(sorted(self.owner.script.blocks)) or "none"
                self.report(
                    _error(
                        "script.unknown_block",
                        step.line,
                        f"no block called {step.block!r} (blocks: {known})",
                    ),
                    report,
                )
            else:
                texts.append(Template(block.text))
        elif isinstance(step, TypeTable):
            self._table_columns(step.table, step.line, report)
        elif isinstance(step, Find):
            texts.extend(_locator_texts(step.locator))
        elif isinstance(step, Read):
            texts.extend(_locator_texts(step.source))
        elif isinstance(step, WaitFor):
            texts.extend(_locator_texts(step.locator))
        elif isinstance(step, WaitForWindow):
            texts.append(step.title)
        elif isinstance(step, MoveTo):
            target = step.target
            if isinstance(target, Locator):
                texts.extend(_locator_texts(target))
            elif isinstance(target, PositionVariable):
                self._position(target.name, step.line, scope, report)
        elif isinstance(step, Record):
            texts.extend(value for _, value in step.columns)
        elif isinstance(step, Call):
            texts.extend(value for _, value in step.arguments)
        elif isinstance(step, Expect):
            if isinstance(step.subject, Locator):
                texts.extend(_locator_texts(step.subject))
            elif step.subject != OUTPUT:
                self._text(step.subject, step.line, scope, report)
            if isinstance(step.value, Template):
                texts.append(step.value)
        for text in texts:
            for name in text.names:
                self._text(name, step.line, scope, report)

    def _text(self, name: str, line: int, scope: _Scope, report: bool) -> None:
        if name in scope.text_names():
            return
        if name in scope.positions:
            self.report(
                _error(
                    "script.position_as_text",
                    line,
                    f"{{{{{name}}}}} holds a position from 'find'; it cannot be used as text",
                ),
                report,
            )
            return
        self.report(
            _error("script.unknown_variable", line, _unknown(name, scope, self.routine)), report
        )

    def _position(self, name: str, line: int, scope: _Scope, report: bool) -> None:
        if name in scope.positions:
            return
        if name in scope.text_names():
            self.report(
                _error(
                    "script.text_as_position",
                    line,
                    f"{{{{{name}}}}} is text, not a position; 'move to' needs a name set by 'find'",
                ),
                report,
            )
            return
        self.report(
            _error("script.unknown_variable", line, _unknown(name, scope, self.routine)), report
        )


def _locator_texts(locator: Locator | None) -> list[Template]:
    if locator is None:
        return []
    return [locator.label] + ([locator.window] if locator.window is not None else [])


def _unknown(name: str, scope: _Scope, routine: Routine | None) -> str:
    message = f"{{{{{name}}}}} is not defined at this point"
    if routine is not None:
        message += (
            f"; routine {routine.name!r} sees only its parameters "
            f"({', '.join(routine.parameters) or 'none'}) and the names it sets itself"
        )
    elif not scope.columns:
        message += "; table columns are only defined inside a 'for each' over that table"
    return message


def _stale(step: Step, stale: int | str) -> ValidationIssue:
    what = type(step).__name__.lower().replace("moveto", "move to")
    if isinstance(stale, int):
        cause = f"the input on line {stale} may have changed the screen since"
    else:
        cause = f"this is {stale}"
    return _error(
        "script.stale_screenshot",
        step.line,
        f"'{what}' looks at the last screenshot, but {cause}. "
        "Take a 'screenshot', or 'wait for' something, first (§5.6)",
    )


def _line_of(issue: ValidationIssue) -> int:
    digits = "".join(ch for ch in issue.location if ch.isdigit())
    return int(digits) if digits else 0


def validate_script(script: Script) -> tuple[ValidationIssue, ...]:
    """Everything wrong with ``script`` as a whole; empty when there is nothing."""
    return _Validator(script).run()
