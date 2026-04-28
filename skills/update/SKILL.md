---
name: update
description: Refresh the paper-wiki marketplace clone, compare versions, and on drift rename the stale cache plus prune installed_plugins.json + settings.json enabledPlugins so the next /plugin install does a real install. Use when /paper-wiki:update is invoked, when the user wants to upgrade paper-wiki, or after the user has pulled a new release tag.
---

# paper-wiki Update

## Overview

This SKILL is a thin wrapper over the `paperwiki update` console-script
(Task 9.26). It exists for discoverability — users typing
`/paper-wiki:update` from inside Claude get the same upgrade behavior
they would from a fresh terminal. The actual heavy lifting lives in
`paperwiki.cli.update()`:

1. `git pull` the marketplace clone at
   `~/.claude/plugins/marketplaces/paper-wiki/`.
2. Compare the marketplace version vs `installed_plugins.json`'s cached
   version for `paper-wiki@paper-wiki`.
3. If they differ, rename
   `~/.claude/plugins/cache/paper-wiki/paper-wiki/<old>/` to
   `<old>.bak.<UTC-timestamp>` and drop the entry from
   `installed_plugins.json` plus both `settings.json` and
   `settings.local.json` `enabledPlugins`.
4. Print a 4-line summary (`old → new`, optional cache backup note,
   and a 3-step "Next" list with the slash-command for the fresh
   install).

This is the official upgrade path replacing the manual `rm -rf cache`
+ JSON-edit ritual that tripped users up on v0.3.5–v0.3.7.

## When to Use

- The user types `/paper-wiki:update`.
- The user asks "how do I upgrade paper-wiki?" or "why isn't my new
  version picking up?".
- After the user reports they pulled a new tag from GitHub or are
  trying to apply a release.

**Do not use** when the user wants a fresh install (route to
`/plugin install paper-wiki@paper-wiki`) or wants to remove the plugin
(route to `/paper-wiki:uninstall`).

## Process

### Step 1 — Run the CLI

```
paperwiki update
```

Fallback if `paperwiki` is not on PATH:

```
${CLAUDE_PLUGIN_ROOT}/.venv/bin/paperwiki update
```

### Step 2 — Surface the output verbatim

The CLI prints either:

- **No-op**: `paper-wiki is already at <version>` — the user is up to
  date. Forward this verbatim and stop.
- **Upgraded**: `paper-wiki: <old> → <new>` plus an optional
  `(cache backed up to <bak-name>)` and a 3-step `Next:` list.
  Forward verbatim.

Do NOT paraphrase the version numbers or the next-steps list. The
exact slash commands and exit instructions are what the user copy-pastes.

### Step 3 — Walk the user through the next steps when needed

The `Next:` list reads:

```
Next:
  1. Exit any running session: /exit (or Ctrl-D)
  2. Open a fresh session: claude
  3. Inside: /plugin install paper-wiki@paper-wiki
```

**Required** (Task 9.34 / D-9.34.1): Steps 1–2 must happen in a NEW
`claude` process. **`/reload-plugins` is NOT enough** to apply the new
version — `/reload-plugins` refreshes the loaded SKILL prose but does
NOT trigger SessionStart hooks, which are responsible for bootstrapping
the new version's venv. Without SessionStart, the new
`${VENV_DIR}/bin/paperwiki` may not exist yet, and the next SKILL
that shells out to `paperwiki <X>` will fail with
`paperwiki: line N: .venv/bin/paperwiki: No such file or directory`.

The v0.3.29 `~/.local/bin/paperwiki` shim self-heals when invoked from
a fresh terminal (it detects the missing venv and inline-bootstraps
via `ensure-env.sh`), so power users running `paperwiki status` from
a new shell window are fine. But inside-Claude SKILL invocations rely
on the SessionStart bootstrap completing first.

Make this explicit if the user asks "can I just `/plugin install`
from here?" or "what's wrong with `/reload-plugins`?". The answer is
always: `/exit` then a brand-new `claude` session.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll re-run `/plugin install paper-wiki@paper-wiki` directly — that should pick up the new version." | Wrong. Claude Code short-circuits with "already installed globally" if the cache directory still exists, even if `git pull` updated the marketplace clone. The cache rename + JSON cleanup is exactly what enables `/plugin install` to do a real install. Always run `paperwiki update` first. |
| "I'll skip the `/exit` step — the user is in the middle of something." | The plugin cache is loaded at session start. Without a fresh session, the new version's SKILLs and runners aren't picked up. Insist on the `/exit → claude` step. |
| "I'll edit `installed_plugins.json` manually — faster." | Manual edits forget `settings.json` and `settings.local.json` `enabledPlugins`, leaving the plugin in a half-disabled state. The CLI handles all three files atomically. Always use the CLI. |

## Red Flags

- `paperwiki update` exits with `paper-wiki marketplace clone not
  found` → the user never installed the plugin via `/plugin install`.
  Suggest the fresh-install flow instead.
- `paperwiki update` exits with `git command failed` → check network /
  credentials. Don't fall back to manual JSON editing; surface the git
  error so the user can fix the underlying problem.
- The output mentions `(not installed → <new>)` instead of
  `<old> → <new>` → the cache was already missing; the JSON cleanup
  still ran. Tell the user the next steps are still required.

## Verification

- The terminal output from `paperwiki update` was forwarded verbatim.
- The user understood that steps 1–2 of the `Next:` list require a
  brand-new terminal/session, not just `claude -c`.
- After the user completes the next steps and re-installs, a follow-up
  `paperwiki status` shows `cache version` and `marketplace ver` agree
  on the new version.
