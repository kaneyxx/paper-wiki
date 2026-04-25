# paper-wiki — Repo Guide for Claude Code

This file is read when Claude Code is opened inside this repo.

## Project intent

`paper-wiki` is a **Claude Code plugin** (not a PyPI library) that
builds personal research wikis from academic papers. See
[SPEC.md](SPEC.md) for the full operating contract.

## Repo layout (essentials)

- `.claude-plugin/` — plugin manifest and self-marketplace listing
- `.claude/commands/` — user-facing slash commands
- `skills/<name>/SKILL.md` — auto-discovered SKILLs
- `agents/` — specialist personas (optional)
- `references/` — cross-SKILL shared content
- `hooks/` — `SessionStart` venv bootstrap
- `src/paperwiki/` — backing Python (private to plugin)
- `tests/` — pytest suite
- `recipes/` — YAML recipe library

## Working in this repo

Always run before committing:

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src
pytest -q
claude plugin validate .   # whenever .claude-plugin/, .claude/, skills/, hooks/, or agents/ changed
```

## Conventions

- **Conventional Commits** (`feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`, `test:`, `ci:`).
- **English** for all source comments, docstrings, log messages.
  Chinese only inside `src/paperwiki/locales/zh/`.
- **No LLM API calls** in Python code. Reasoning belongs in SKILLs
  driven by Claude Code itself.
- **Use** `httpx`, `loguru`, `Pydantic`, `Typer`. Do **not** use
  `requests`, `urllib`, stdlib `logging`, or `argparse`.
- **Pin** direct dependencies; avoid floating versions.

See [SPEC.md](SPEC.md) §5 for the full code style and §7 for boundaries.
