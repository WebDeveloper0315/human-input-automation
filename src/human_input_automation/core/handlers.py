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
    TypeText,
    Wait,
)
from .engine import ActionRegistry, ExecutionContext


def handle_type_text(action: TypeText, ctx: ExecutionContext) -> None:
    """Type text with per-character timing.

    With a zero-delay profile the whole string is sent in one call, which is
    much faster; that also means cancellation is only checked before the call,
    so instant typing is all-or-nothing per action.
    """
    if ctx.timing.profile.is_instant_typing:
        ctx.keyboard.type_text(action.text)
        return
    for char in action.text:
        ctx.checkpoint()
        ctx.keyboard.type_text(char)
        ctx.sleep_ms(ctx.timing.char_delay_ms(char))


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
        ctx.mouse.move_by(action.x, action.y, duration)
    else:
        ctx.mouse.move_to(action.x, action.y, duration)


def handle_mouse_click(action: MouseClick, ctx: ExecutionContext) -> None:
    position = action.position
    if position is not None:
        ctx.mouse.move_to(position[0], position[1], ctx.timing.mouse_move_duration_ms())
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
