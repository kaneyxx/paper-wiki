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

The CLI is flag-driven (v0.3.35+). Default mode handles the
plugin layer; `--everything` extends to the user-controlled config
root, the PATH shim, the marketplace clone, and the marketplace
settings entry; `--purge-vault PATH` adds paperwiki-created vault
content; `--nuke-vault` (with `--purge-vault`) removes the entire
vault directory:

| Flag | What it adds |
|---|---|
| (none) | plugin cache, `installed_plugins.json` paper-wiki entry, `settings.json` `enabledPlugins["paper-wiki@paper-wiki"]` |
| `--everything` | + `~/.config/paper-wiki/`, `~/.local/bin/paperwiki` shim + `.paperwiki-path-warned`, marketplace clone, `extraKnownMarketplaces.paper-wiki` |
| `--purge-vault PATH` | + `Daily/`, `Wiki/`, `.digest-archive/`, `.vault.lock`, `Welcome.md` under PATH (preserves `.obsidian/` + everything else) |
| `--nuke-vault` (with `--purge-vault`) | replaces surgical removal with `rm -rf PATH` |
| `--yes` / `-y` | skip confirmation prompts |
| `--verbose` / `-v` | log each removal |

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

### Step 1 — Print the flag-driven uninstall redirect

Tell the user:

```
paper-wiki cannot safely uninstall itself from inside Claude Code —
the active session would lose its SKILLs and runners mid-execution.

Run this from a fresh terminal (NOT inside `claude`):

    paperwiki uninstall                  # plugin layer only (default)
    paperwiki uninstall --everything     # + config root, shim, marketplace
    paperwiki uninstall --everything --purge-vault PATH        # + vault content
    paperwiki uninstall --everything --purge-vault PATH --nuke-vault   # + rm -rf vault

Add --yes (or -y) to skip the confirmation prompt; -v to log each
removal. Reinstall any time with:

    claude
    /plugin install paper-wiki@paper-wiki
```

If the user reports `paperwiki: command not found`, point them at the
PATH-defensive form first:

```bash
source "$HOME/.local/lib/paperwiki/bash-helpers.sh" 2>/dev/null || {
    echo "ERROR: paper-wiki bash-helpers missing at ~/.local/lib/paperwiki/bash-helpers.sh." >&2
    echo "  Fix: exit Claude Code and re-open — the SessionStart hook installs the helper." >&2
    echo "  Persistent failures: ~/.local/lib/ may be unwritable; re-run \$CLAUDE_PLUGIN_ROOT/hooks/ensure-env.sh." >&2
    exit 1
}
paperwiki_ensure_path
paperwiki uninstall
```

If that still fails, the SessionStart hook didn't install the shim;
they need to exit Claude Code and start a fresh `claude` session so
`hooks/ensure-env.sh` re-runs.

`paperwiki where` is the safe inventory before any of this — run it
first so the user can SEE what would be lost. The CLI also prints the
removal plan and confirms before acting (unless `--yes` is given).

### Step 1b — Fresh-user reset

If the user explicitly asks for a "fresh-user reset" or wants to
simulate an unconfigured machine for re-testing, the one-command
recipe is:

```bash
paperwiki uninstall --everything --purge-vault ~/Documents/Obsidian-Vault --nuke-vault --yes
```

(Substitute the actual vault path. `--nuke-vault` removes everything
under the vault including `.obsidian/`, so warn the user that any
non-paperwiki content in that directory will be lost. Drop
`--nuke-vault` for a surgical reset that keeps `.obsidian/` and other
non-paperwiki files.)

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
