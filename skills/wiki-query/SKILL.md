---
name: wiki-query
description: Answers a research question by searching the wiki and synthesizing an answer with citations. Use when /paper-wiki:wiki-query is invoked, when the user asks "what does my wiki say about X", or when the user wants a literature-aware answer drawn from previously-ingested sources.
---

# paper-wiki Wiki Query

## Overview

Query is the read path of the wiki. The runner runs a small TF-IDF-ish
keyword search across concept articles and source summaries, returning
ranked hits with snippets. Claude then synthesizes a coherent answer
that **only** draws from the returned hits, citing each claim by
wikilink. No memory-based answers, no fabrication.

This SKILL is the daily payoff of the Karpathy LLM-Wiki design — the
reason the user has been ingesting papers at all.

## When to Use

- The user types `/paper-wiki:wiki-query <question>`.
- The user asks any natural-language research question that the wiki
  might answer ("what foundation models cover pathology?", "summarize
  what I know about CIC mutations").
- The user asks for a refresher on a concept they ingested earlier.

**Do not use** when the user wants to add knowledge (route to
`wiki-ingest`) or check wiki health (route to `wiki-lint`). Do not
use as a general-purpose search engine for things that aren't in the
wiki — say so honestly and suggest `/paper-wiki:digest` to ingest more
sources first.

## Process

1. **Pick search terms.** From the user's question, extract 2-5
   substantive nouns / multi-word phrases. Drop function words.
2. **Run the runner.** Run this exact bash to invoke the query runner.
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
   paperwiki wiki-query <vault> "<terms>" --top-k 10
   ```

   Parse the JSON list of hits.
3. **Surface top hits.** If `len(hits) == 0`, tell the user the wiki
   doesn't cover this topic and offer to ingest sources. Stop.
4. **Read the hit files.** For the top hits (typically 3-5), read the
   actual concept / source body.
5. **Synthesize the answer.** Write a 1-3 paragraph answer that uses
   **only** content from the read files. Cite each claim with the
   matching wikilink, e.g. "[[Vision-Language Foundation Models]]".
6. **Suggest follow-ups.** End with one or two follow-up queries the
   user might ask, or note a `wiki-lint` finding the answer reveals.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "The wiki only has 3 hits but I know the answer; I'll mix in my own knowledge." | The user trusts wiki-query to ground its answer in their wiki. Mixed answers hide what's actually theirs vs what's invented. Surface the gap honestly. |
| "I'll cite by paper title only; wikilinks are noisy." | Wikilinks let the user click through and verify. They are the audit trail; do not strip them. |
| "Three hits is enough; no need to read the bodies." | Snippets are 200 chars and lose context. Always read the top 3-5 bodies before synthesizing. |
| "Empty results just mean the user phrased it badly; I'll answer anyway." | Empty results are signal. Tell the user "your wiki doesn't cover this" and offer ingestion. |

## Red Flags

- The user repeatedly asks the same question and gets empty results:
  the wiki is missing key sources; suggest a focused digest or
  manual analyze.
- The top hit's `confidence` is below 0.4: the concept is a draft;
  tell the user the answer rests on shaky synthesis and offer to
  re-ingest with newer sources.
- Hits all come from one source id: warn the user the answer is
  single-source and may be biased.
- A wikilinked target in your draft answer doesn't appear in the
  returned hits: you are inventing — drop the link.

## Verification

- `paperwiki wiki-query` exits 0.
- Every wikilink in the answer matches the path of a returned hit.
- Every claim in the answer is traceable to a snippet you read.
- The answer never contains "I know" / "in general" / "as a model" —
  if those words feel necessary, the wiki cannot answer the question
  and you should say so.
