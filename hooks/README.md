# Hooks

paper-wiki uses Claude Code's hook system to bootstrap its private Python
environment on demand, so end users never have to think about Python.

## SessionStart: `ensure-env.sh`

Runs at the start of every Claude Code session.

- **First run**: builds a private virtualenv at
  `${CLAUDE_PLUGIN_ROOT}/.venv` and installs paper-wiki's Python
  dependencies. Prefers [`uv`](https://docs.astral.sh/uv/) when
  available; falls back to stdlib `venv` + `pip`.
- **Subsequent runs**: no-op. Idempotency is guaranteed by the
  `.venv/.installed` stamp file.

If the venv ever becomes corrupted, the simplest recovery is:

```bash
rm -rf "${CLAUDE_PLUGIN_ROOT}/.venv"
```

The next session will rebuild it automatically.
