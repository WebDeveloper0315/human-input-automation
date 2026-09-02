"""Built-in action handlers.

Each handler is a small function that performs one action through the ports on
the execution context. They are registered in :func:`default_registry`, which is
what a caller extends to add new action types.
"""

from __future__ import annotations

from .actions import (
    AUTO_CLOSED_PAIRS,
    IndentMode,
    KeyDown,
    KeyPress,
    KeyUp,
    MouseClick,
    MouseDown,
    MouseMove,
    MouseUp,
    Shortcut,
    TypeCode,
    TypeText,
    Wait,
)
from .engine import ActionRegistry, ExecutionContext
from .errors import UnsupportedActionError
from .keys import Key, KeyLike, parse_shortcut
from .typing_style import Hesitate, TypeChars, TypingStep, Undo, plan_typing


def handle_type_text(action: TypeText, ctx: ExecutionContext) -> None:
    """Type text with per-character timing.

    With a zero-delay profile and a style that types exactly, the whole string
    is sent in one call, which is much faster; that also means cancellation is
    only checked before the call, so instant typing is all-or-nothing per
    action.
    """
    if ctx.timing.profile.is_instant_typing and ctx.timing.style.is_exact:
        ctx.keyboard.type_text(action.text)
        return
    _type_string(action.text, ctx)


def handle_type_code(action: TypeCode, ctx: ExecutionContext) -> None:
    """Type text into an editor that indents, closes brackets and completes.

    One line at a time, because every compensation is a per-line one: the
    editor's indentation is only there to be replaced just after a newline, and
    the brackets it closed for us are only reachable while the caret is still on
    the line that opened them.
    """
    lines = action.lines
    for index, line in enumerate(lines):
        if index:
            _tap(ctx, Key.ENTER)

        body = line.lstrip() if action.indent is IndentMode.EDITOR else line
        # Reclaiming means selecting the indentation the editor inserted when
        # *we* pressed Enter, so it only ever applies from the second line on.
        # On the first line the caret is wherever the user left it, and there
        # the same chord would select whatever is already on that line and type
        # over it - losing text the plan never mentioned.
        #
        # A line that is only the editor's indentation is skipped too: there is
        # nothing to type over it with, and the next Enter clears it anyway.
        if index and action.indent is IndentMode.RECLAIM and body.strip():
            _chord(ctx, action.line_start_chord)

        if body:
            _type_string(body, ctx)

        if action.drop_auto_pairs:
            for _ in range(unclosed_pairs(body)):
                _tap(ctx, Key.DELETE)
        if action.dismiss_suggestions:
            _tap(ctx, Key.ESC)


#: Where an editor stops closing brackets for you: inside a string, and after a
#: comment marker. Both are conventions rather than rules, which is why counting
#: too few is the failure this scanner is built to prefer - see below.
_QUOTES = "\"'`"
_LINE_COMMENTS = ("//", "#")


def unclosed_pairs(line: str) -> int:
    """How many brackets ``line`` opens and leaves open.

    That is how many closing brackets an editor has left sitting to the right of
    the caret at the end of the line: the ones we close ourselves are typed over
    as we go, and only the outstanding ones survive.

    Brackets inside a string or a trailing comment are skipped, because an
    editor configured by language does not close those either. Where the guess
    is wrong it is wrong downwards: an unterminated quote stops the scan, so the
    count comes out too low and a bracket is left behind, rather than too high -
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
    return len(stack)


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


def _type_string(text: str, ctx: ExecutionContext) -> None:
    """Send ``text`` through the run's typing style."""
    for step in plan_typing(text, ctx.timing.style, ctx.timing.rng):
        _perform_typing_step(step, ctx)


def _perform_typing_step(step: TypingStep, ctx: ExecutionContext) -> None:
    if isinstance(step, Hesitate):
        ctx.sleep_ms(step.duration_ms)
        return
    if isinstance(step, Undo):
        for _ in range(step.count):
            _tap(ctx, Key.BACKSPACE)
            ctx.sleep_ms(step.pause_ms)
        return
    if not isinstance(step, TypeChars):  # pragma: no cover - the union is closed
        raise UnsupportedActionError(f"unknown typing step {type(step).__name__}")
    for char in step.text:
        ctx.checkpoint()
        ctx.keyboard.type_text(char)
        ctx.sleep_ms(ctx.timing.char_delay_ms(char))


def _tap(ctx: ExecutionContext, key: KeyLike) -> None:
    """Press and release one key, tracked so a stop cannot leave it held."""
    ctx.checkpoint()
    ctx.hold_key(key)
    ctx.sleep_ms(ctx.timing.key_hold_ms())
    ctx.release_key(key)


def _chord(ctx: ExecutionContext, shortcut: str) -> None:
    """Send ``"shift+home"``-style notation: hold all but the last, tap the last."""
    keys = parse_shortcut(shortcut)
    held: list[KeyLike] = []
    try:
        for key in keys[:-1]:
            ctx.hold_key(key)
            held.append(key)
            ctx.sleep_ms(ctx.timing.key_hold_ms())
        # Tapped inline rather than through _tap: its checkpoint could block on
        # a pause with the modifiers still held down over the whole desktop.
        ctx.hold_key(keys[-1])
        ctx.sleep_ms(ctx.timing.key_hold_ms())
        ctx.release_key(keys[-1])
    finally:
        for key in reversed(held):
            ctx.release_key(key)


def handle_key_press(action: KeyPress, ctx: ExecutionContext) -> None:
    for repetition in range(action.count):
        ctx.checkpoint()
        ctx.hold_key(action.key)
        ctx.sleep_ms(ctx.timing.key_hold_ms())
        ctx.release_key(action.key)
        if repetition < action.count - 1:
            ctx.sleep_ms(ctx.timing.key_repeat_delay_ms())


def handle_key_down(action: KeyDown, ctx: ExecutionContext) -> None:
    ctx.hold_key(action.key)


def handle_key_up(action: KeyUp, ctx: ExecutionContext) -> None:
    ctx.release_key(action.key)


def handle_shortcut(action: Shortcut, ctx: ExecutionContext) -> None:
    """Hold every key but the last, tap the last, then release in reverse."""
    held = []
    try:
        for key in action.modifiers:
            ctx.hold_key(key)
            held.append(key)
            ctx.sleep_ms(ctx.timing.key_hold_ms())
        ctx.hold_key(action.main_key)
        ctx.sleep_ms(ctx.timing.key_hold_ms())
        ctx.release_key(action.main_key)
    finally:
        for key in reversed(held):
            ctx.release_key(key)


def handle_mouse_move(action: MouseMove, ctx: ExecutionContext) -> None:
    duration = ctx.timing.mouse_move_duration_ms(action.duration_ms)
    if action.relative:
        ctx.mouse.move_by(action.x, action.y, duration, ctx.control)
    else:
        ctx.mouse.move_to(action.x, action.y, duration, ctx.control)


def handle_mouse_click(action: MouseClick, ctx: ExecutionContext) -> None:
    position = action.position
    if position is not None:
        ctx.mouse.move_to(
            position[0], position[1], ctx.timing.mouse_move_duration_ms(), ctx.control
        )
    for repetition in range(action.count):
        ctx.checkpoint()
        ctx.hold_button(action.button)
        ctx.sleep_ms(ctx.timing.key_hold_ms())
        ctx.release_button(action.button)
        if repetition < action.count - 1:
            ctx.sleep_ms(ctx.timing.key_hold_ms())


def handle_mouse_down(action: MouseDown, ctx: ExecutionContext) -> None:
    ctx.hold_button(action.button)


def handle_mouse_up(action: MouseUp, ctx: ExecutionContext) -> None:
    ctx.release_button(action.button)


def handle_wait(action: Wait, ctx: ExecutionContext) -> None:
    ctx.sleep_ms(action.duration_ms)


def default_registry() -> ActionRegistry:
    """Registry containing every built-in action handler."""
    registry = ActionRegistry()
    registry.register(TypeText, handle_type_text)
    registry.register(TypeCode, handle_type_code)
    registry.register(KeyPress, handle_key_press)
    registry.register(KeyDown, handle_key_down)
    registry.register(KeyUp, handle_key_up)
    registry.register(Shortcut, handle_shortcut)
    registry.register(MouseMove, handle_mouse_move)
    registry.register(MouseClick, handle_mouse_click)
    registry.register(MouseDown, handle_mouse_down)
    registry.register(MouseUp, handle_mouse_up)
    registry.register(Wait, handle_wait)
    return registry
