---
name: status
description: Show paper-wiki install state — version cached on disk, marketplace clone version, and which Claude Code settings file enables the plugin. Use when /paper-wiki:status is invoked, when the user reports "is paper-wiki installed?", or when troubleshooting upgrade flows.
---

# paper-wiki Status

## Overview

Reports the paper-wiki install state in three lines:

1. **cache version** — what's on disk under
   `~/.claude/plugins/cache/paper-wiki/paper-wiki/<version>/` per
   `installed_plugins.json`.
2. **marketplace ver** — what the marketplace clone at
   `~/.claude/plugins/marketplaces/paper-wiki/.claude-plugin/plugin.json`
   advertises (this is the version a fresh `/plugin install` would pull).
3. **enabledPlugins** — whether `paper-wiki@paper-wiki` is enabled in
   `settings.json` and `settings.local.json`.

This SKILL is a thin wrapper over the `paperwiki status` console-script
(Task 9.26 / 9.29). The runner is LLM-free; this SKILL exists for
discoverability — users who type `/paper-wiki:status` from inside
Claude get the same answer they would from a terminal.

## When to Use

- The user types `/paper-wiki:status`.
- The user asks "is paper-wiki installed?", "what version am I on?",
  or "why isn't paper-wiki picking up my changes?".
- Troubleshooting an upgrade flow (paired with `/paper-wiki:update`).

**Do not use** when the user wants to perform an upgrade — route to
`/paper-wiki:update` instead.

## Process

### Step 1 — Run the CLI

Invoke the console-script directly (it's installed at
`~/.local/bin/paperwiki` by `hooks/ensure-env.sh` since v0.3.21).
The `export PATH=...` line is mandatory — fresh-install users may not
have `~/.local/bin` on PATH yet (D-9.34.6).

```bash
export PATH="$HOME/.local/bin:$PATH"
paperwiki status
```

If `paperwiki status` still reports `command not found` after the
`export PATH=...` line, the SessionStart hook didn't run — tell the
user to exit and restart Claude Code so `hooks/ensure-env.sh`
re-installs the shim.

### Step 2 — Surface the output

The CLI prints three lines exactly as documented above. Forward them
verbatim to the user; do not re-format or paraphrase. The user is
checking the raw state for diagnostic purposes.

### Step 3 — Interpret if asked

Common follow-up questions and the right interpretation:

- **"cache version `(not in installed_plugins.json)`"** → the plugin
  was either never installed or was already cleaned up by `paperwiki
  uninstall` / `paperwiki update`.
- **"marketplace ver `(marketplace clone not found)`"** → the user
  hasn't run `/plugin install paper-wiki@paper-wiki` yet (which clones
  the marketplace as a side-effect), OR they manually deleted
  `~/.claude/plugins/marketplaces/paper-wiki/`.
- **`cache version` and `marketplace ver` differ** → an upgrade is
  available. Suggest `/paper-wiki:update` to apply it cleanly.
- **`enabledPlugins: settings.json=no settings.local.json=no`** but
  cache version is set → the plugin is installed but disabled. Suggest
  `/plugin enable paper-wiki@paper-wiki`.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll re-implement the status check inline as Python so I can format the output prettier." | The CLI is the single source of truth for install state. Re-implementing diverges the SKILL surface from the terminal surface and breaks the v0.3.27 symmetry contract. Always shell out. |
| "The user only wants to know the version — I'll just print `__version__`." | `paperwiki.__version__` reflects the wheel that's INSTALLED in the venv, not the cache version Claude Code sees. The three sources can disagree and that disagreement is exactly what this SKILL surfaces. Do not skip lines. |

## Red Flags

- `paperwiki status` exits non-zero → the runner crashed (corrupt
  JSON, permission denied, etc.). Surface the stderr verbatim and do
  NOT silently fall back to inline Python.
- The user pastes output where two `enabledPlugins` lines are both
  `yes` but `cache version` is `(not in installed_plugins.json)` →
  state files are out of sync. Suggest `paperwiki update` to clean up.

## Verification

- The terminal output from `paperwiki status` was forwarded to the
  user verbatim.
- Any interpretation provided maps directly to the
  cache/marketplace/enabledPlugins lines printed by the CLI; no
  invented state.
