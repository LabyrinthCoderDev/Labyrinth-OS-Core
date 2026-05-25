# Contributing to Labyrinth-OS-Core

Thank you for your interest in contributing.

---

## Getting Started

```bash
git clone https://github.com/LabyrinthCoder/labyrinth-os-core.git
cd labyrinth-os-core
pip install -r requirements.txt
python run_all.py
```

All tests should pass before submitting any changes.

---

## Contribution Guidelines

**Code quality:**
- Follow existing code style and naming conventions
- All new modules must include tests
- Tests must pass before submission: `python run_all.py`
- Do not reduce test coverage

**Commits:**
- Conventional format: `feat:`, `fix:`, `docs:`, `test:`, `chore:`
- Present tense, imperative: "add feature" not "added feature"
- One logical change per commit

**Pull requests:**
- Small, focused PRs are easier to review
- Include a clear description of what changed and why
- Reference any related issues

---

## Architecture

This system enforces one law: **Imagination is free. Execution requires proof.**

Before contributing, read:
- `README.md` — what this build is and what it does
- `ARCHITECTURE.md` (if present) — the mandatory pipeline
- `KNOWN_GAPS.md` — known open items

Do not bypass the gate. Do not weaken the invariants.
Any change that reduces the enforcement guarantees will be rejected.

---

## Security

Do not file public issues with security vulnerabilities.
See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

---

*@LabyrinthCoder — sole authority on all architectural decisions*
