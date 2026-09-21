"""Built-in action handlers.

Each handler is a small function that performs one action through the ports on
the execution context. They are registered in :func:`default_registry`, which is
what a caller extends to add new action types.
"""

from __future__ import annotations

from .actions import (
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
from .editor_typing import Emit, Press, plan_code_typing
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

    Every decision was made by :func:`~.editor_typing.plan_code_typing`, which
    is a pure function of the text and the editor's behaviour; this only
    performs what it planned, so the interesting part stays testable without a
    keyboard anywhere near it.
    """
    for step in plan_code_typing(action):
        if isinstance(step, Emit):
            _type_string(step.text, ctx)
        elif isinstance(step, Press):
            for _ in range(step.count):
                _tap(ctx, step.key)
        else:
            _chord(ctx, step.shortcut)


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
