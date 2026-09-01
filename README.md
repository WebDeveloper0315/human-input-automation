# Human Input Automation

Cross-platform desktop automation tool for keyboard/mouse input, inspired by AutoIt.

## Goals
- Windows, macOS, Ubuntu/Linux
- Target a selected window/application
- Type user-provided text and perform mouse/keyboard actions
- Configurable human-like timing with bounded jitter
- Deterministic/reproducible timing via optional random seed
- Dry-run and emergency stop
- Pluggable OS backends

## Important design note
The project should not promise that generated input is indistinguishable from a human. "Human-like" means natural configurable timing and movement for usability/testing, not bypassing security, anti-bot, CAPTCHA, or access controls.

## Suggested stack
Python 3.11+
- PySide6: desktop GUI
- pynput: cross-platform keyboard/mouse input
- pywinctl: window discovery/activation where supported
- PyYAML or JSON: saved profiles
- pytest: tests
- ruff + mypy: quality checks
- PyInstaller: desktop packaging

Keep platform-specific code behind interfaces so the core automation engine is testable without a real desktop.

## Run
```bash
python -m venv .venv
# activate the environment
pip install -e ".[dev]"
python -m human_input_automation
```

See `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.
