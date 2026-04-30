---
name: wiki-graph
description: Queries the v0.4.x wiki knowledge graph for papers citing X, concepts in topic Y, or collaborators of person Z. Use when /paper-wiki:wiki-graph is invoked, when the user asks "what papers cite X" / "what concepts does topic Y cover" / "who has collaborated with Z", or when they want a structured view of the wiki graph.
---

# paper-wiki Wiki Graph

## Overview

The wiki-graph SKILL surfaces the v0.4.x typed-entity knowledge graph
that ``wiki_compile_graph`` builds (task 9.157). It answers three
direct (non-transitive) queries against the cached
``<vault>/Wiki/.graph/edges.jsonl``:

* ``--papers-citing <paper>`` — every entity that wikilinks to the
  target paper.
* ``--concepts-in-topic <topic>`` — concepts directly referenced by
  the target topic.
* ``--collaborators-of <person>`` — people directly linked from the
  target person's note.

The runner auto-rebuilds the graph cache when source Markdown is
newer than the cached ``edges.jsonl`` (per consensus plan iter-2 R13
+ Scenario 6) so users don't have to think about cache freshness.

## When to Use

- The user types ``/paper-wiki:wiki-graph``.
- The user asks "what papers cite X" / "what concepts does topic Y
  cover" / "who has Z collaborated with".
- The user wants a structured query against the v0.4.x typed-entity
  layout (papers / concepts / topics / people subdirs).

**Do not use** when:

- The user wants free-text search across note bodies (use
  ``wiki-query`` instead).
- The vault uses the legacy flat layout (no typed subdirs yet) — run
  ``wiki-compile`` migration (task 9.160) first.
- The user wants to lint graph integrity (use ``wiki-lint
  --check-graph`` instead).

## Process

1. **Identify the query**: parse the user's intent into one of the
   three flags. If ambiguous, ask one clarifying question.

2. **Resolve the target**: the SKILL passes the user's term verbatim
   to the runner. The runner accepts slug forms (``transformer``),
   subdir-qualified ids (``concepts/transformer``), and canonical
   ``arxiv:`` ids — whichever the user typed.

3. **Invoke the runner via the shim**:

   ```
   paperwiki wiki-graph <vault> --wiki-subdir Wiki \
     --papers-citing <target> --json
   ```

   Replace ``--papers-citing`` with the appropriate flag. Use
   ``--json`` (default) when piping the result back through Claude
   for synthesis; use ``--pretty`` only when the user explicitly
   asked for a human-readable table.

4. **Synthesize the answer**: read the JSON and answer the user in
   natural language. Cite specific entity ids (rendered as
   ``[[entity_id]]`` so Obsidian renders the wikilinks). Do not
   reproduce more than ~10 records inline; if the result has more,
   summarise and offer to dump the full list.

5. **Surface staleness**: if the runner emitted a
   ``wiki_graph_query.rebuild.start`` log line, mention to the user
   that the cache was auto-rebuilt — first call after edits is the
   one-time cost; subsequent queries are instant.

## Common Rationalizations

- "I'll just grep the Markdown myself." — wiki_graph_query is
  faster (one cached file vs. walking the vault) and resolves
  aliases (canonical_id, slug, frontmatter aliases) consistently
  with what ``wiki_compile_graph`` saw at build time.
- "I'll synthesise without invoking the runner." — Don't. Claude's
  view of the wiki is partial; the runner sees the actual graph.
- "I'll just rebuild the graph every time." — The auto-rebuild is
  idempotent and gated on mtime; forcing ``--rebuild`` only when
  the user explicitly requests it keeps the latency budget tight.

## Red Flags

- Queries that return 0 records on a vault the user expects to be
  full → check ``--wiki-subdir`` is correct (legacy vaults use
  ``.``; v0.4.0 typed-subdir vaults use ``Wiki``).
- Unresolved targets → suggest ``wiki-lint --check-graph`` to find
  ORPHAN_SOURCE / GRAPH_INCONSISTENT violations.
- Errors mentioning ``edges.jsonl`` missing → the user's vault
  probably hasn't been compiled yet; run
  ``/paper-wiki:wiki-compile`` first.

## Verification

After running:

- The runner exited 0.
- The JSON parsed without errors.
- The natural-language answer cites at least one concrete entity_id
  (or honestly says "no matches").
- For non-empty results, the user has clear next steps (e.g. open a
  cited paper note, run ``wiki-lint --check-graph``).
