---
name: wiki-ingest
description: Ingests a new source paper into the wiki by regenerating affected concept articles. Use when /paperwiki:wiki-ingest is invoked, when a fresh source lands in Wiki/sources/ via analyze or digest, or when the user says "fold this paper into the wiki" or "update the wiki with X".
---

# paper-wiki Wiki Ingest

## Overview

Ingest folds a single source into the wiki. The runner enumerates which
concept articles already reference the source — those need
re-synthesis — and which concepts the source's own
`related_concepts` frontmatter hints at but don't yet exist in the
wiki. Claude then synthesizes the new prose for each affected concept
and writes it back via the markdown wiki backend.

This is the heart of the Karpathy / kytmanov LLM-Wiki loop. Run it
whenever a new source lands so concepts stay current and contradictions
do not pile up.

## When to Use

- The user types `/paperwiki:wiki-ingest <canonical-id>`.
- The `analyze` SKILL has just written a new file under `Sources/` and
  passes control here.
- The `digest` reporter ran with `wiki_backend: true` and dropped new
  source files into `Wiki/sources/` — ingest each one in turn.
- The user says "fold this paper into my wiki" / "update the concepts
  for this source".

**Do not use** when the user is asking a research question (route to
`wiki-query`) or to refresh the index (route to `wiki-compile`).

## Process

1. **Resolve the source id.** Accept `arxiv:1234.5678`, `s2:<paperId>`,
   or a fuzzy title; normalize to a canonical id via the
   `paperwiki._internal.normalize` helpers if the user gave a URL.
2. **Run the planner.** Invoke
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_ingest_plan
   <vault> <canonical-id>`. Read the JSON.
3. **Honor `source_exists`.** If `source_exists` is `false`, stop and
   ask the user to run `/paperwiki:analyze <id>` first; ingest cannot
   work without a source file under `Wiki/sources/`.
4. **Update affected concepts.** For each name in `affected_concepts`:
   read the existing concept body, fetch the new source's content,
   and synthesize an updated body that incorporates the new evidence
   without dropping prior synthesis. Respect `status: reviewed` —
   merge into a draft section rather than overwriting reviewed prose.
   Persist via
   `MarkdownWikiBackend.upsert_concept(name=..., body=..., sources=[...],
   confidence=..., status="draft")`.
5. **Optionally bootstrap suggested concepts.** Walk
   `suggested_concepts`. For each, ask the user whether to create the
   concept (yes/no/skip-all). If yes, generate a first draft body
   and call `upsert_concept` with `status="draft"`.
6. **Append to `_log.md`.** Add a single line:
   `- <iso8601-utc> wiki-ingest <canonical-id> -> <n> concepts updated`.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "The user just gave me an arxiv URL; I can synthesize from memory." | Wrong abstracts and made-up methods sneak in. Always read the actual source file written by analyze. |
| "Overwriting a `reviewed` concept is fine; I'm just refreshing." | Reviewed status is the user's signal that the prose is correct. Merge or branch into a draft section; never silently overwrite. |
| "If `source_exists` is false I'll just synthesize from the URL." | The dedup filter relies on the source file's frontmatter. No file means future digests recommend the same paper again. Run analyze first. |
| "I'll skip `_log.md`; the user doesn't read it." | The compile and lint runners use the log to spot stale concepts. Without it, the wiki's audit trail breaks. |

## Red Flags

- The runner returns no `affected_concepts` and no `suggested_concepts`:
  the source has zero topical hooks. Either the analyze step lost the
  metadata (re-run analyze) or the wiki has no relevant concepts yet
  (offer to seed one).
- The same source id keeps re-ingesting on every run: the digest
  reporter is double-firing. Tell the user, do not hide the duplicate.
- A "suggested concept" name collides with an existing concept after
  case folding: surface to the user and let them rename.
- The synthesis would exceed ~600 lines: the wiki-lint runner will
  flag it. Trim or split before committing.

## Verification

- `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_ingest_plan`
  exits 0.
- Each affected concept's `last_synthesized` field is today's date.
- Each affected concept's `sources` list contains the ingested
  canonical id at most once.
- `_log.md` gains exactly one new line.
- `/paperwiki:wiki-lint` shows no `BROKEN_LINK` findings introduced
  by the new prose.
