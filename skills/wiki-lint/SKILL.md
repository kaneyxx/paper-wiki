---
name: wiki-lint
description: Runs a health check on the wiki and surfaces orphans, stale entries, oversized files, broken wikilinks, and status mismatches. Use when /paper-wiki:wiki-lint is invoked, before a release of the wiki to others, or periodically to keep concept articles trustworthy.
---

# paper-wiki Wiki Lint

## Overview

Lint is the wiki's quality gate. The runner walks every concept
article and reports five classes of issue with stable codes
(`ORPHAN_CONCEPT`, `STALE`, `OVERSIZED`, `BROKEN_LINK`,
`STATUS_MISMATCH`). Claude reads the structured report and offers
batch fixes — re-ingest a stale concept, split an oversized one,
demote a wrongly-`reviewed` concept, etc.

The check is read-only; nothing changes until the user accepts a
proposed fix.

## When to Use

- The user types `/paper-wiki:wiki-lint`.
- After a batch ingest (3+ sources in a session) — periodic health
  check catches drift early.
- Before the user shares the wiki externally or commits changes.
- When `wiki-query` returns answers that feel off (low confidence,
  contradictions) — lint may localize the cause.

**Do not use** when the user wants to ingest content (`wiki-ingest`)
or query knowledge (`wiki-query`).

## Process

1. **Run the runner.** Invoke
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_lint
   <vault>`. Optionally pass `--stale-days N` if the user wants a
   tighter / looser staleness threshold.
2. **Group by severity.** Errors first (`BROKEN_LINK`), then warnings
   (`ORPHAN_CONCEPT`, `STATUS_MISMATCH`), then infos (`STALE`,
   `OVERSIZED`).
3. **Summarize counts.** "1 error, 3 warnings, 2 infos across N
   concept files."
4. **Propose batch fixes.** For each finding type, offer the most
   useful action:
   - `BROKEN_LINK`: list the missing target name; offer to create a
     stub concept or remove the link.
   - `ORPHAN_CONCEPT`: offer to delete the concept or to ingest a
     candidate source.
   - `STATUS_MISMATCH`: offer to demote `reviewed` -> `draft` or
     update the confidence.
   - `STALE`: offer to re-ingest the linked sources.
   - `OVERSIZED`: offer to split into two concepts or to summarize.
5. **Wait for user choice.** Do not auto-fix. Each fix is a separate
   handoff to `wiki-ingest`, manual edit, or removal.
6. **Append to `_log.md`** if any fix is applied.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll auto-fix all `STATUS_MISMATCH` findings." | The user might want their `reviewed` concept to keep its status while they raise confidence elsewhere. Always confirm. |
| "Five findings is a lot; I'll summarize and skip the details." | Each finding has a stable code — the user filters by severity. Surface them all so the user can grep / accept in batch. |
| "If a wikilink target is just one typo away from a real concept, I'll fix it silently." | Silent edits lose audit trail. Suggest the fix; let the user accept. |
| "Stale `info` findings can be ignored." | Stale concepts are how contradictions creep in. At minimum, flag them. |

## Red Flags

- More than 10 `BROKEN_LINK` findings: a major concept name was
  renamed and references didn't update. Suggest a search-and-replace
  pass before any other fix.
- Every concept is `STALE`: the user hasn't ingested in months.
  Offer a fresh digest run.
- An `OVERSIZED` concept is tagged `status: reviewed`: splitting
  risks losing the user's curation. Always confirm before splitting.
- The runner exits non-zero: report the error code and don't
  pretend the lint succeeded.

## Verification

- `paperwiki.runners.wiki_lint` exits 0.
- Severity counts in your summary match `report.counts` exactly.
- Each proposed fix references a finding code from the report.
- After any accepted fix, a follow-up lint run produces fewer
  findings of that code.
