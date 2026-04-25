# AGENTS.md — paper-wiki

Guidance for AI coding agents (Claude Code, Cursor, Copilot, Gemini CLI,
etc.) working in this repo.

## What this repo is

A Claude Code plugin that builds a personal research wiki from arXiv and
Semantic Scholar papers. See [SPEC.md](SPEC.md) for the full contract.

## Always do

- Read [SPEC.md](SPEC.md) before making changes.
- Validate plugin manifests after touching `.claude-plugin/`,
  `.claude/`, `skills/`, `hooks/`, or `agents/`:

  ```bash
  claude plugin validate .
  ```

- Run lints and tests before committing:

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest -q
  ```

- Use Conventional Commits for every commit message.

## Never do

- Never publish to PyPI; this is a Claude Code plugin only.
- Never call LLM APIs from Python (Claude Code is the LLM surface).
- Never use `requests`, `urllib`, stdlib `logging`, or `argparse`.
- Never break the plugin protocol without a major version bump.
- Never write outside `${CLAUDE_PLUGIN_ROOT}/.venv` from a hook.

## Code style at a glance

- Python ≥ 3.11, src layout
- `ruff format`, `ruff check`, `mypy --strict`
- Async-first I/O via `httpx`
- `loguru` for logging
- `Pydantic` for config
- `Typer` for internal CLIs
- English comments and docstrings only

See [SPEC.md](SPEC.md) §5 for the full code style.
