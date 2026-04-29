---
name: bio-search
description: Searches biomedical literature (bioRxiv, medRxiv, PubMed Central) via the paperclip MCP server and optionally folds results into the wiki. Use when the user invokes /paper-wiki:bio-search, asks to "search bioRxiv", "search PubMed", "find biomedical papers on X", "look up a clinical trial on Y", or otherwise wants biomedical-domain literature beyond what arXiv covers.
---

# paper-wiki bio-search

## Overview

bio-search is the biomedical-literature surface for paper-wiki. It
delegates the actual search to [paperclip](https://gxl.ai/blog/paperclip)
via the paperclip MCP server (`mcp__paperclip__*` tools when registered)
and optionally hands hits to `/paper-wiki:wiki-ingest` so they land in
your wiki the same way arXiv papers do.

This SKILL is **opt-in**: paperclip is a third-party service with its
own auth and tier model. paper-wiki's other SKILLs (digest, analyze,
wiki-*) work without it. Only invoke bio-search when the user is
specifically asking for biomedical-domain literature.

## When to Use

- The user types `/paper-wiki:bio-search <query>`.
- The user says "search bioRxiv", "search medRxiv", "search PubMed",
  "find biomedical papers on X".
- The user asks for clinical / translational research that arXiv
  generally does not cover (pathology, oncology, cardiology, genomics,
  drug discovery, etc.).
- The user follows up an `analyze`/`digest` thread with "what do
  bioRxiv preprints say about this?" or similar.

**Do not use** for:

- arXiv / general CS work — that routes to `/paper-wiki:digest` with
  the `daily-arxiv` recipe.
- Single-paper deep dives — that routes to `/paper-wiki:analyze`.
- Searches inside the user's own wiki — that routes to
  `/paper-wiki:wiki-query`.

## Process

1. **Check that paperclip MCP is available.** Run this exact bash to
   call the diagnostics runner via the shim. The `export PATH=...`
   line is mandatory — fresh-install users may not have
   `~/.local/bin` on PATH yet (D-9.34.6).

   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   paperwiki diagnostics
   ```

   Parse the JSON output and inspect `mcp_servers`. If `paperclip` is
   missing, **stop** and show the user the registration steps from
   [`docs/paperclip-setup.md`](../../docs/paperclip-setup.md). Do not
   run `claude mcp add` yourself; the user opts in.

   As an offline fallback, mention the bundled
   `recipes/biomedical-weekly.yaml` recipe — it shells out to the
   paperclip CLI and works without the MCP layer if the user prefers.
2. **Resolve the query.** Accept free-text. If the user gives a vague
   topic ("pathology"), ask one clarifying follow-up before burning a
   paperclip call: "do you want preprints, peer-reviewed PMC, or
   both?", "any time window?", etc. Default to bioRxiv + medRxiv + PMC
   over the last 14 days unless told otherwise.
3. **Call paperclip via MCP.** Use the `mcp__paperclip__search` tool
   (or whatever name the registered MCP server exposes). Surface the
   raw paperclip results — title, authors, source, abstract, link —
   in a numbered list. Do not paraphrase; users want to scan the
   actual abstracts.
4. **Offer follow-ups.**
   - "Analyze paper #N in depth" → invoke `/paper-wiki:analyze
     paperclip:bio_<id>` (or `arxiv:<id>` if the hit has an arXiv id
     under `external_ids`).
   - "Save these as wiki sources" → for each chosen hit, write the
     source stub under `Wiki/sources/<canonical-id>.md` via
     `MarkdownWikiBackend.upsert_paper` directly, then chain to
     `/paper-wiki:wiki-ingest`. (A dedicated `paperwiki fetch-pdf`
     subcommand is a future-Phase candidate; today the wiki backend
     handles the upsert without a separate fetcher runner.)
   - "Refine the search" → loop back to step 2 with the new query.
5. **Summarize at the end.** Tell the user what was added to the wiki
   (canonical ids + concept names if any), and suggest the next step:
   `/paper-wiki:wiki-lint` to spot dangling sources, or
   `/paper-wiki:wiki-query` to ask follow-up questions.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll auto-register paperclip MCP for the user." | Auth is sensitive and the user may be on a metered plan. Hand over the registration command, never run it. |
| "I'll paraphrase the abstracts to save space." | Users want to scan the actual paperclip text — paraphrasing introduces drift and hides what the search engine actually returned. |
| "If paperclip times out, I'll fall back to my training data." | Out-of-date / hallucinated biomedical claims can be dangerous. If the call fails, surface the failure; don't fake the result. |
| "The user said 'biomedical' — I'll just guess they mean PMC." | Different sub-corpora have different freshness and peer-review status. Confirm scope (preprints vs. peer-reviewed) before searching. |

## Red Flags

- The diagnostics report shows no `paperclip` in `mcp_servers` and the
  user is mid-conversation with high urgency — slow down. Show the
  registration steps; do not run `claude mcp add`.
- paperclip returns 0 hits — the query is probably too narrow. Offer
  to broaden (drop one keyword, expand the date window) before giving
  up.
- A hit's `id` collides with an existing source under
  `Wiki/sources/` — surface the duplicate; do not silently overwrite.
- The user asks for "the latest treatment for <disease>" — biomedical
  literature is not clinical advice. Decline to summarize as
  recommendations; surface the papers and let the user / their
  clinician decide.

## Verification

- `paperclip` appears in the diagnostics `mcp_servers` field before
  the SKILL invokes any MCP tool.
- The user's vault has at least one new file under `Wiki/sources/` if
  the user opted to save hits.
- `/paper-wiki:wiki-lint` surfaces a `DANGLING_SOURCE` finding for any
  newly saved source until the user runs `/paper-wiki:wiki-ingest`.
- Each MCP call's `tool_use_id` is logged so the user can audit what
  paperclip was asked.
