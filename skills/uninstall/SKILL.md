---
name: uninstall
description: Print the safe paper-wiki uninstall command and explain why it must be run from a fresh terminal (Claude Code can't safely tear itself out from inside its own session). Use when /paper-wiki:uninstall is invoked. The actual uninstall lives in the paperwiki CLI; this SKILL exists for discoverability.
---

# paper-wiki Uninstall

## Overview

This SKILL is intentionally a one-step pointer rather than performing
the uninstall directly. Claude Code is using paper-wiki right now — if
this SKILL deleted the plugin cache and pruned the JSON entries from
inside Claude, the active session would lose its SKILLs and runners
mid-execution, which is confusing and unrecoverable without restarting
anyway.

So `/paper-wiki:uninstall` always tells the user to run the same
command from a fresh terminal:

```
paperwiki uninstall
```

The CLI handles the actual teardown:

1. Removes the cache directory at
   `~/.claude/plugins/cache/paper-wiki/paper-wiki/<version>/`.
2. Drops the `paper-wiki@paper-wiki` entry from
   `installed_plugins.json`.
3. Drops the entry from both `settings.json` and `settings.local.json`
   `enabledPlugins`.
4. Prints next-step instructions if the user wants to reinstall.

D-9.29.2: shipping this SKILL despite the "confusing UX" objection
because users who ask `/paper-wiki:uninstall` deserve a clear pointer
to the right command — silence makes them think they have to manually
edit JSON files.

## When to Use

- The user types `/paper-wiki:uninstall`.
- The user asks "how do I remove paper-wiki?" or "how do I uninstall
  this plugin?".

**Do not use** when the user wants to upgrade (route to
`/paper-wiki:update`) or downgrade (route to `paperwiki update` after
checking out an older marketplace tag — out of scope for this SKILL).

## Process

### Step 1 — Print the redirect message

Tell the user:

```
paper-wiki cannot safely uninstall itself from inside Claude Code —
the active session would lose its SKILLs and runners mid-execution.

Run this from a fresh terminal (NOT inside `claude`):

    paperwiki uninstall

The CLI removes the plugin cache, prunes `installed_plugins.json`,
and clears `enabledPlugins` in both `settings.json` and
`settings.local.json`. Reinstall any time with:

    claude
    /plugin install paper-wiki@paper-wiki
```

Substitute `${CLAUDE_PLUGIN_ROOT}/.venv/bin/paperwiki uninstall` if the
user reports `paperwiki: command not found` (their PATH doesn't
include `~/.local/bin`).

### Step 2 — Do NOT shell out

Even if the user insists "just do it from here", explain that the
uninstall pattern is fundamentally a fresh-terminal operation. The
CLI is idempotent so they can run it any time, but doing it from
inside Claude leaves the current session in a broken half-state.

This SKILL never invokes `paperwiki uninstall` itself — it only
prints the redirect.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "The CLI is idempotent — I'll just run it; the user can `/exit` after." | Wrong. The active session loses its SKILLs and runners the moment the cache is removed. The user gets stuck in a half-functional Claude session and has to force-quit. Always print the redirect; never invoke. |
| "The user said 'just do it' — that's consent." | The user can't consent to a self-destruct path they don't fully understand. Print the redirect once; if they push back, explain why and stand firm. |
| "I'll print the message AND shell out — best of both worlds." | The shell-out has the same problem regardless of whether you printed a message first. Do not invoke. |

## Red Flags

- The user appears to be running `/paper-wiki:uninstall` repeatedly
  because nothing seems to happen → confirm they've actually opened
  a fresh terminal. The SKILL never performs the uninstall itself
  by design.
- The user says "I already exited and the cache is still there" →
  they ran `/exit` from inside Claude but Claude.app may still be
  running. Suggest `paperwiki status` to confirm state, then
  `paperwiki uninstall` from a clean shell.

## Verification

- The redirect message was printed in full.
- This SKILL did NOT invoke `paperwiki uninstall` (no Bash call to
  the uninstall command).
- The user understood that the operation requires a fresh terminal,
  not just a new Claude session inside the same parent shell.
