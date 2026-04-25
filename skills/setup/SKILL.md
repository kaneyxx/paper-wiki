---
name: setup
description: Verifies the paper-wiki environment and walks the user through first-time configuration. Use when the user invokes /paperwiki:setup, when no paper-wiki config exists yet, or when paperwiki commands fail with environment errors.
---

# paper-wiki Setup

## Overview

The setup SKILL confirms paper-wiki's Python environment is healthy,
walks the user through pointing the plugin at their vault, and chooses
an initial recipe. It runs implicitly the first time another paper-wiki
SKILL needs configuration, and explicitly via `/paperwiki:setup`.

## When to Use

- The user types `/paperwiki:setup`.
- A paper-wiki SKILL fails because no configuration file exists yet.
- The user reports broken Python imports inside
  `${CLAUDE_PLUGIN_ROOT}/.venv`.
- The user asks "how do I configure paper-wiki?" or "where do I point it
  at my vault?"

**Do not use** when the user is asking about a specific recipe, a
specific paper, or pipeline output — those route to other SKILLs.

## Process

1. Confirm the plugin's Python environment is ready by running
   `bash ${CLAUDE_PLUGIN_ROOT}/hooks/ensure-env.sh`. Verify the script
   exits with status 0 and that `${CLAUDE_PLUGIN_ROOT}/.venv/.installed`
   exists.
2. Run
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.diagnostics`
   and parse its JSON output. (Until the diagnostics runner exists, fall
   back to a Python `--version` smoke check.)
3. If no `~/.config/paperwiki/config.toml` is present, ask the user for
   their vault path. Validate that the path exists and is writable
   before saving.
4. Suggest a starter recipe from `recipes/`. Default to
   `daily-arxiv.yaml` once it exists; for now, note that recipes are
   coming in Phase 4.
5. **Surface optional MCP servers.** Read the diagnostics report's
   `mcp_servers` field. If `paperclip` is not present, mention it as
   an *optional* opt-in for biomedical literature search and offer
   the registration command:

   ```bash
   claude mcp add --transport http paperclip https://paperclip.gxl.ai/mcp
   ```

   **Do not auto-run** this command — auth is sensitive and the user
   may be on a metered plan. Hand them the line, link to
   `docs/paperclip-setup.md`, and let them opt in. If `paperclip` is
   already in `mcp_servers`, confirm it cheerfully and move on; do not
   re-register.
6. Tell the user the next command to try (`/paperwiki:digest` once
   available; for now, confirm setup is complete).

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "The user just wants to skip setup." | Without setup, downstream SKILLs read invalid config and emit confusing errors. The fix once is cheaper than the confusion many times. |
| "I'll trust whatever the user says about their vault path." | Validate the path exists and is writable; an invalid path silently breaks every later SKILL. |
| "The venv is probably fine; no need to verify." | Stale or partial venvs are the most common silent failure. Run `ensure-env.sh` and confirm the stamp file every time. |

## Red Flags

- `ensure-env.sh` exits non-zero or the `.installed` stamp is missing —
  the venv is broken; rerun the script and inspect the output.
- The diagnostics runner emits empty or non-JSON output — Python
  imports are broken; nuke `.venv` and rerun `ensure-env.sh`.
- The user already has `~/.config/paperwiki/config.toml` and you are
  about to overwrite it without asking.
- The user mentions Chinese vault paths or templates — surface the
  `locales/zh/` option but keep English as the default.
- The user asks you to "register paperclip for me" or similar — explain
  that paperclip auth is sensitive; emit the command for them to run
  themselves. Never auto-run `claude mcp add` without explicit consent.
- `mcp_servers` already lists `paperclip` but the user wants it
  registered again — surface the existing registration and ask whether
  to remove it first; do not stack duplicates.

## Verification

- `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` exists.
- `~/.config/paperwiki/config.toml` exists and parses as TOML.
- The diagnostics runner (when present) exits 0; before then,
  `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python --version` succeeds.
