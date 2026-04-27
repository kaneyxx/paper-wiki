# Wiki — Ingest, Query, Lint, Compile

paper-wiki ships an **LLM-driven knowledge wiki** modeled on Andrej
Karpathy's [LLM Wiki sketch][karpathy-gist] and the practical pattern
that [`kytmanov/obsidian-llm-wiki-local`][kytmanov-repo] proved out.
The wiki sits in your vault as plain Markdown; Claude maintains it
through four SKILLs that mirror Karpathy's ingest / query / lint loop.

[karpathy-gist]: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
[kytmanov-repo]: https://github.com/kytmanov/obsidian-llm-wiki-local

## Layout

```text
<vault>/
└── Wiki/
    ├── index.md          # Auto-generated table of contents
    ├── _log.md           # Append-only operation chronicle
    ├── sources/          # One file per ingested paper
    ├── concepts/         # Synthesized topic articles
    └── .drafts/          # Pending review (gitignored)
```

The default subdir name is `Wiki` (overridable per-recipe). Sources
under `Wiki/sources/<canonical-id>.md` are the per-paper summaries
written by the analyze SKILL or the digest reporter when
`wiki_backend: true` is set. Concepts under `Wiki/concepts/<name>.md`
are the synthesized topic articles Claude writes during
`/paper-wiki:wiki-ingest`.

## Frontmatter convention

Both file types carry YAML frontmatter the runners and dedup filter
read.

**Source** (per paper):

```yaml
title: "PRISM2: Unlocking Multi-Modal General Pathology AI"
canonical_id: "arxiv:2506.13063"
status: draft
confidence: 0.85
tags: [foundation-model, pathology]
related_concepts: ["[[Vision-Language Foundation Models]]"]
last_synthesized: 2026-04-25
```

**Concept** (per topic):

```yaml
title: "Vision-Language Foundation Models"
status: reviewed
confidence: 0.7
sources: ["arxiv:2506.13063", "arxiv:0001.0001"]
related_concepts: ["[[Multimodal Reasoning]]"]
last_synthesized: 2026-04-25
```

`status` is `draft | reviewed | stale`. `confidence` is `0.0 – 1.0`.
The dedup filter and `wiki_lint` rely on these fields.

## The four operations

```text
                       SOURCES
                          │
                          ▼
       ┌───── /paper-wiki:wiki-ingest ─────┐
       │                                  │
       │   plan affected concepts         │
       │   regenerate prose via Claude    │
       │   write concept articles         │
       │                                  │
       └──────────────┬───────────────────┘
                      ▼
                 CONCEPTS  ◄────── /paper-wiki:wiki-query
                      │
                      ▼
       /paper-wiki:wiki-compile (rebuild index.md)
                      │
                      ▼
                  index.md
                      │
                      ▼
       /paper-wiki:wiki-lint (orphans, stale, broken links)
```

### `paperwiki:wiki-ingest`

Folds one source into the wiki. The runner
(`paperwiki.runners.wiki_ingest_plan`) lists which concepts already
reference the source plus suggests new concepts from
`related_concepts`. Claude regenerates each affected concept body and
writes it back via `MarkdownWikiBackend.upsert_concept`. Reviewed
concepts are merged into rather than overwritten.

### `paperwiki:wiki-query`

Read-only. Runs a small TF-IDF-ish keyword search across concepts and
sources (`paperwiki.runners.wiki_query`). Claude reads the top hit
bodies and synthesizes an answer that cites every claim with a
wikilink. No memory-based answers, no fabrication — empty hits are
surfaced as such.

### `paperwiki:wiki-lint`

Health check. The runner reports five classes of issue with stable
codes (`ORPHAN_CONCEPT`, `STALE`, `OVERSIZED`, `BROKEN_LINK`,
`STATUS_MISMATCH`). Claude offers batch fixes; nothing changes until
the user accepts.

### `paperwiki:wiki-compile`

Rebuilds `Wiki/index.md` deterministically from the current concept
and source state. The output is byte-stable so the file fits cleanly
in version control. Claude optionally regenerates the prose summary at
the top.

## What the plugin does **not** do

- We do **not** call any LLM API directly. Claude Code is the LLM —
  every prose synthesis happens in the SKILL, never in Python. (See
  SPEC §6.)
- We do **not** use vector embeddings. At the ~100-source scale
  Karpathy designed the wiki for, plain keyword search is enough and
  avoids embedding infrastructure.
- We do **not** ship a watcher daemon. SKILLs are user-triggered.
- We do **not** maintain a SQLite state DB. Frontmatter + git history
  serve the same audit-trail role.
