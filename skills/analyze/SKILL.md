---
name: analyze
description: Deep-analyzes a single paper into a wiki entry. Use when the user invokes /paperwiki:analyze, asks "tell me more about <paper>", wants a per-paper breakdown of methods and contributions, or is following up on a recommendation from /paperwiki:digest.
---

# paper-wiki Analyze

## Overview

The analyze SKILL takes a single paper (by canonical id, arXiv URL, or
title fragment) and produces a deep-analysis wiki entry: research
problem, method, key innovations, experimental setup, deep analysis,
and a comparison block. The output is written into the user's vault as
a paper note that the digest can later cross-link to.

This SKILL is the bridge between "I saw this in the digest" and "I
have a durable note about it in my vault".

> **Status:** Phase 6 deliverable. The Python runner backing this
> SKILL is not yet implemented; for now the SKILL guides Claude through
> the workflow manually, which still produces a usable note.

## When to Use

- The user types `/paperwiki:analyze <id-or-title>` or
  `/paperwiki:analyze` after picking a paper from a digest.
- The user says "analyze this paper", "summarize <title>", "give me
  a deep dive on <paper>".
- The user asks for "the methods" or "the contributions" of a specific
  paper.

**Do not use** when the user wants a list of papers to read — that
routes to `paperwiki:digest`. Do not use for general literature
overviews or topic surveys (no SKILL covers that yet).

## Process

1. **Resolve the paper.** Accept `arxiv:1234.5678`, an arXiv URL,
   `s2:<paperId>`, or a fuzzy title. Confirm the resolution before
   doing the work.
2. **Fetch metadata.** Use the source plugin matching the namespace:
   arXiv for `arxiv:`, Semantic Scholar for `s2:` or unspecified.
3. **Read the abstract and (optionally) the PDF.** PDF download is a
   future capability; for now, lean on the abstract.
4. **Build the analysis.** Cover six sections in this order:
   research problem, method overview, key innovations, experimental
   results, deep analysis, comparison with related work.
5. **Write to the vault.** Paper notes live under the vault's
   `Sources/` subdir at `{vault_path}/Sources/{normalized-title}.md`
   (the constant `SOURCES_SUBDIR` in `paperwiki.config.layout`).
   Frontmatter must carry `canonical_id`, `title`, `tags`, `status`,
   and `confidence` so dedup recognizes the entry on the next digest
   run and `wiki_lint` does not flag it as broken. Johnny.Decimal /
   PARA users may override the subdir name in their recipe; the
   constant is the single source of truth.
6. **Hand off to wiki-ingest.** Immediately invoke
   `/paperwiki:wiki-ingest <canonical-id>` so the new source is
   folded into the user's concept articles. Skipping this step
   leaves a `DANGLING_SOURCE` finding the next time `wiki-lint`
   runs.
7. **Cross-link.** If the user came from a digest entry, update the
   digest line to point its wikilink at the new note.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I can guess what's in the paper from the title." | Wrong analyses corrupt the wiki and erode trust. Always anchor in the abstract and explicit metadata. |
| "Skipping frontmatter is fine; the user knows what they wrote." | The dedup filter relies on `paper_id`/`title` frontmatter. No frontmatter = recommendation loop. |
| "If the PDF download fails, give up." | The abstract alone is enough for a usable first note. The user can deepen it later. |

## Red Flags

- The user provides only a title and there are multiple matches:
  surface the candidates and ask, do not pick blindly.
- A paper with the same `paper_id` already exists in the vault:
  ask before overwriting; offer to refresh metadata only.
- The note exceeds ~600 lines without the user asking for that
  depth: trim to the six core sections.

## Verification

- The output file lives under `{vault_path}/Sources/` (or whatever
  `SOURCES_SUBDIR` is configured to in the active recipe).
- Frontmatter parses as YAML and contains at least `canonical_id`,
  `title`, `tags`, `status`, and `confidence`.
- `/paperwiki:wiki-ingest` ran on the new canonical id and reported
  zero `BROKEN_LINK` findings.
- `/paperwiki:wiki-lint` does not flag the new source with
  `DANGLING_SOURCE` (a concept now references it).
- The next `/paperwiki:digest` run dedupes the analyzed paper out of
  recommendations (it should not surface again).
