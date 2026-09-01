# Architecture

## Layers

1. **UI** — PySide6 desktop interface.
2. **Application** — orchestration, validation, run lifecycle, cancellation.
3. **Core** — platform-independent action models, timing, parser, scheduler.
4. **Ports** — interfaces for window discovery, activation, keyboard and mouse.
5. **Adapters** — Windows/macOS/Linux implementations.

## Target-window model

A target should be represented by a stable backend identifier plus title/process metadata.
Do not rely only on the visible title because titles can change.

Window targeting should be capability-aware:
- Windows: enumerate/activate windows with native APIs where needed.
- macOS: Accessibility APIs and permissions.
- Linux: X11/Wayland differences must be detected. Wayland may restrict global input/window control.

## Human-like timing

Use configurable bounded variation, not fixed sleeps. A later version can support:
- per-character delay distributions
- punctuation/word-boundary pauses
- action-level pauses
- mouse movement duration
- configurable profiles
- deterministic seeds for tests

Avoid claims that timing is "undetectable" or designed to defeat anti-bot systems.

## Safety

Include:
- Start/Pause/Stop
- global emergency stop
- visible active-target indicator
- dry-run mode
- confirmation before execution
- limits on action count and text length
- audit/log output
