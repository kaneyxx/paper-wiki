---
name: migrate-sources
description: Upgrades existing Wiki/sources/<id>.md files to the current source-stub format while preserving user-edited content in Notes / Key Takeaways / Figures sections. Use when /paper-wiki:migrate-sources is invoked, after upgrading paper-wiki to a new minor version, when wiki-lint surfaces stale-format warnings, or when the user notices their old source files lack the Core Information / Key Takeaways / Figures section structure.
---

# paper-wiki Migrate Sources

## Overview

Paper-wiki's per-paper source-stub format (``Wiki/sources/<id>.md``)
evolves between minor releases. New ingests always write the current
format, but files already in the user's vault stay on whichever
format they were originally written under — leaving the wiki visually
inconsistent (some entries have ``## Figures`` placeholders, some
don't; outline panes look different per paper).

This SKILL runs ``paperwiki.runners.migrate_sources``, which walks
every ``Wiki/sources/*.md`` and rewrites legacy files to the current
format while preserving any user-authored content in ``## Notes``,
``## Key Takeaways``, and ``## Figures``. Files already in the
current format are skipped (no-op).

## When to Use

- The user types ``/paper-wiki:migrate-sources``.
- The user just upgraded paper-wiki and notices old digest entries
  look "ugly" or "different" from new ones.
- ``wiki-lint`` reports a STALE_FORMAT-like finding (currently a
  follow-up; until that lands, look for missing ``## Core
  Information`` headings as the visual cue).
- The user asks "can I update my old papers to the new format?" /
  "upgrade existing source files" / "rewrite legacy stubs".

**Do not use** for fresh vaults (the runner's a no-op there) or for
non-source files (concept articles under ``Wiki/concepts/`` are not
touched — they already have a different schema).

## Process

1. **Dry-run first.** Run this exact bash to invoke the migrate-sources
   runner in dry-run mode. The ``export PATH=...`` line is mandatory —
   fresh-install users may not have ``~/.local/bin`` on PATH yet
   (D-9.34.6).

   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   paperwiki migrate-sources <vault> --dry-run
   ```

   Surface the count to the user. If ``migrated == 0``, tell them no
   migration is needed and stop.
2. **Confirm before rewriting.** If ``migrated > 0``, show the user
   the exact list (``migrated_paths``) so they know what's about to
   change, and ask whether to proceed.
3. **Run the migration.** Drop ``--dry-run`` and re-invoke the
   runner. Surface the final report.
4. **Suggest follow-up.** Once migration is done, suggest the user
   re-run ``/paper-wiki:wiki-lint`` to confirm the upgraded files
   pass health checks, and ``/paper-wiki:wiki-compile`` to refresh
   the index.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "Just run with no flags — dry-run is overhead." | The user may have hand-edited their old source files. Dry-run shows them what's about to change so they can opt out before destruction. Always dry-run first. |
| "If migration drops the user's notes, we'll just tell them." | Don't drop them in the first place. The runner explicitly preserves ``## Notes`` / ``## Key Takeaways`` / ``## Figures`` content; verify with the smoke test before wide rollout. |
| "I'll skip files with hand-edits." | The runner already has placeholder detection. Trust the runner; it preserves real user content and only overwrites the canonical placeholders. |
| "If something fails I'll just retry." | The runner reports per-file errors in the JSON ``errors`` field. Surface them to the user instead of silently swallowing — they may indicate corrupted files that need manual repair. |

## Red Flags

- The runner reports ``checked == 0`` — the vault has no
  ``Wiki/sources/*.md`` files. The user probably hasn't run
  ``/paper-wiki:digest`` yet; route them there.
- An unfamiliar file appears in ``migrated_paths`` (e.g., something
  the user manually wrote with a custom schema) — pause and let the
  user inspect before rewriting.
- ``errors`` is non-empty — surface the file name + reason verbatim;
  don't hide parse failures.
- A re-run still reports ``migrated > 0`` — the canonical-format
  marker drifted; file an issue with the diff before the second
  rewrite damages anything.

## Verification

- Re-running with ``--dry-run`` after a successful migration reports
  ``migrated == 0`` (idempotent).
- Files listed in ``migrated_paths`` now contain ``## Core
  Information`` and the other four canonical sections.
- For any file that previously had user content in ``## Notes``,
  ``## Key Takeaways``, or ``## Figures``, that content survives
  verbatim under the same heading after migration.
- ``/paper-wiki:wiki-lint`` still passes (no new ``BROKEN_LINK``s
  from the rewrite).
