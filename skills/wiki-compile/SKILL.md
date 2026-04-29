---
name: wiki-compile
description: Rebuilds Wiki/index.md deterministically from current concept and source articles. Use when /paper-wiki:wiki-compile is invoked, after a wiki-ingest run, before sharing the wiki, or whenever the user wants the index refreshed.
---

# paper-wiki Wiki Compile

## Overview

Compile rebuilds the wiki's table-of-contents file (`Wiki/index.md`).
The runner reads every concept and source, sorts deterministically,
and rewrites the index with frontmatter, a warning banner, the concept
list, and the source/concept cross-reference table. Claude then
optionally regenerates the human-readable summary at the top of the
index in plain English.

The output is byte-deterministic so the index can sit in git without
churning on every run.

## When to Use

- The user types `/paper-wiki:wiki-compile`.
- Right after a `wiki-ingest` run, so the index reflects new concepts
  and sources.
- Before the user shares the wiki externally.
- When `wiki-lint` reports `BROKEN_LINK` errors — the index
  regeneration confirms the new state of cross-references.

**Do not use** when no concept or source has changed since the last
compile (idempotent, but wastes a run).

## Process

1. **Run the runner.** Run this exact bash to invoke the compile runner.
   The `export PATH=...` line is mandatory — fresh-install users may
   not have `~/.local/bin` on PATH yet (D-9.34.6).

   ```bash
   source "$HOME/.local/lib/paperwiki/bash-helpers.sh" 2>/dev/null || {
       echo "ERROR: paper-wiki bash-helpers missing at ~/.local/lib/paperwiki/bash-helpers.sh." >&2
       echo "  Fix: exit Claude Code and re-open — the SessionStart hook installs the helper." >&2
       echo "  Persistent failures: ~/.local/lib/ may be unwritable; re-run \$CLAUDE_PLUGIN_ROOT/hooks/ensure-env.sh." >&2
       exit 1
   }
   paperwiki_ensure_path
   paperwiki wiki-compile <vault>
   ```

   The runner rewrites `Wiki/index.md` and prints
   `compiled: N concepts, M sources -> <path>`.
2. **Confirm the index file.** Read the first 30 lines and verify
   frontmatter has `concepts: N` and `sources: M` matching the
   runner's stdout.
3. **Optionally write the prose summary.** Just below the warning
   banner, draft a 1-2 sentence narrative summary of the wiki state
   (count of concepts, dominant topics, last_synthesized range).
   Keep it terse — this is index material, not a digest.
4. **Append to `_log.md`** with `wiki-compile <iso8601> N concepts,
   M sources`.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll edit the index by hand; the runner will pick it up." | The runner overwrites the file. Hand edits are lost. Use prose-summary substitution if you want narrative, but the structured sections are runner-owned. |
| "Skipping compile after ingest is fine." | Stale indexes mislead the user about what's in the wiki. Re-running compile is cheap; do it. |
| "The runner already prints counts; no need to verify the file." | Ensures the on-disk state matches the run summary; protects against partial writes after a crash. |

## Red Flags

- Compile rewrites the file but counts changed unexpectedly: a
  concept or source got deleted/renamed outside this session. Ask the
  user.
- The narrative-summary section keeps drifting between runs: pin the
  wording in a CLAUDE.md or template; do not regenerate from scratch
  each time.
- `last_compiled` in frontmatter is in the future: clock skew on the
  user's machine. Note it; don't try to fix.

## Verification

- `paperwiki wiki-compile` exits 0.
- `Wiki/index.md` opens cleanly; frontmatter parses.
- Concept and source counts in the file match the runner stdout
  exactly.
- A second `wiki-compile` run produces identical bytes (deterministic).
