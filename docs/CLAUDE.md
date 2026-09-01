# Claude Code Instructions

Read `README.md`, `docs/ARCHITECTURE.md`, and `docs/ROADMAP.md` before changing code.

Principles:
- Keep core logic platform-independent.
- Put OS-specific behavior behind interfaces/adapters.
- Prefer small, testable changes.
- Add tests for every behavior change.
- Never use fixed timing everywhere; use the timing service.
- Never claim input is indistinguishable from humans or use it to bypass CAPTCHA/anti-bot/security controls.
- Preserve an emergency stop path.
- Do not block the UI thread during automation.
- Run `pytest`, `ruff`, and `mypy` before considering a phase complete.
- Update ROADMAP.md and documentation when architecture changes.
