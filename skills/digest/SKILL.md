---
name: digest
description: Builds a research-paper digest from a recipe, writing it to disk via the configured reporters. Use when the user asks for "today's papers", invokes /paper-wiki:digest, requests a daily/weekly research roundup, or wants to refresh their paper-wiki vault.
---

# paper-wiki Digest

## Overview

The digest SKILL turns a YAML recipe into a curated Markdown digest of
recent papers. The recipe declares which sources to pull from, which
filters to apply, how to score, and where to write the output. Claude
reads the user's intent, picks the right recipe, runs the digest
runner, and reports the outcome with the top papers summarized.

This is the workhorse SKILL for paper-wiki. Every other SKILL in the
plugin builds on the same recipe + pipeline foundation.

## When to Use

- The user types `/paper-wiki:digest` or `/paper-wiki:digest <recipe>`.
- The user asks for "today's papers", "this week's papers", "what
  should I read today", or any phrasing of "give me a research digest".
- The user wants to refresh their daily Obsidian note with newly
  published work.
- A previous run failed mid-way and the user wants to retry.

**Do not use** when the user is asking for a deep analysis of one
specific paper — that routes to `paperwiki:analyze`. Do not use when
the user is configuring the plugin for the first time — that routes
to `paperwiki:setup`.

## Process

1. **Locate the recipe.** Resolution order:
   1. **Personal recipe** at `~/.config/paper-wiki/recipes/<name>.yaml`
      (the user's editable copy with their topics, vault paths, and
      ``auto_ingest_top`` preference). If ``$PAPERWIKI_CONFIG_DIR`` is
      set, look there instead of ``~/.config/paper-wiki/``.
   2. **Bundled template** at `${CLAUDE_PLUGIN_ROOT}/recipes/<name>.yaml`.

   Default ``<name>`` is ``daily``. If the user said "weekly", default
   to ``weekly-deep-dive``; if "biomedical" / "bio", default to
   ``biomedical-weekly``. Confirm the resolved path exists; if not,
   surface a clear error and offer to run ``/paper-wiki:setup``.
2. **Source secrets if present.** If
   ``~/.config/paper-wiki/secrets.env`` exists, source it (or ``export``
   each ``KEY=value`` line) before the runner so any
   ``api_key_env: PAPERWIKI_S2_API_KEY`` indirection in the recipe
   resolves cleanly. The recipe loader raises ``UserError`` with a
   pointer at this file when the env var is missing — you'll see it
   in the runner's stderr.
3. **Confirm the environment.** Verify
   `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` exists. If missing, run
   `bash ${CLAUDE_PLUGIN_ROOT}/hooks/ensure-env.sh` and re-check.
4. **Run the digest.** Invoke
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.digest <recipe-path>`
   with an optional `--target-date YYYY-MM-DD` if the user gave one.
5. **Inspect the exit code.** 0 = success, 1 = user error
   (bad recipe / bad config), 2 = system error (network, plugin
   contract). On non-zero, surface the structured log line and offer
   the next concrete step.
6. **Summarize the outcome.** Read the reporter output paths from the
   recipe and report: how many recommendations were emitted, where
   they were written, and the titles + composite scores of the top 3.
7. **Synthesize Today's Overview.** Read the digest file at the path
   emitted by the runner (the obsidian reporter's `output_dir`). Find
   the line `<!-- paper-wiki:overview-slot -->` inside the
   `> [!summary] Today's Overview` callout. Replace that single line
   with 60–200 words of synthesized prose covering:
   - Top trends across the N recommendations (e.g. "3 papers explore
     VLA models, 2 explore diffusion-based generation")
   - Quality / score distribution (e.g. "scores skew high; median 0.74")
   - Suggested reading order (e.g. "start with #2 for the foundation
     paper, then #5 for the application")

   Every factual claim MUST cite the paper(s) it comes from using `#N`
   markers matching the digest's paper indices (e.g. "...as in #1 and
   #4"). Do not invent claims. Use only what's in the digest you just
   read. Keep prose Obsidian-readable (callout-friendly: short
   paragraphs, bullet-able if helpful).
8. **Auto-chain wiki-ingest when configured.** Read the recipe's
   `auto_ingest_top` field. If `> 0`, take the top
   `min(auto_ingest_top, top_k)` papers from the digest and chain
   `/paper-wiki:wiki-ingest <canonical-id> --auto-bootstrap` for each,
   in score order. The `--auto-bootstrap` flag tells wiki-ingest to
   auto-stub any new concepts the source suggests, so a fresh vault
   doesn't dead-end on paper #1 — missing concept articles are stubbed
   automatically before the normal update loop runs. The wiki-ingest
   SKILL handles its own idempotence (no-op when a source is already
   folded into all relevant concepts), so safe to run on every digest.
   Surface the per-paper outcome briefly to the user — they should see
   "ingesting paper #1 → created 2 stubs, updated 1 concept" rather
   than a silent block of activity. When `auto_ingest_top` is `0` (the
   default), skip this step.

   **Note:** interactive `/paper-wiki:wiki-ingest <id>` invocations
   keep the manual confirm prompt — only the digest auto-chain uses
   `--auto-bootstrap`.
9. **Suggest a follow-up.** If the user has not configured a vault,
   suggest `/paper-wiki:setup`. If a paper looks interesting and was
   not auto-ingested, suggest `/paper-wiki:analyze <paper-id>` for a
   deeper dive or `/paper-wiki:wiki-ingest <paper-id>` to fold it
   into concept articles.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll just guess which recipe the user wants without checking." | Recipes diverge a lot (daily vs weekly vs sources-only). Pick wrong and the user gets the wrong window/scoring. Always confirm or default explicitly. |
| "If the runner exits non-zero, the message is enough." | Exit codes are coarse. Read the structured log line (`digest.failed`) and explain the failure in plain English. |
| "Skipping the env check is fine; venv usually exists." | First runs and venv corruption are exactly when this SKILL gets called. Always confirm the `.installed` stamp before invoking the runner. |
| "Top 3 summary is fluff." | Without it the user re-opens the digest file to find anything notable. The summary makes the SKILL useful end-to-end. |
| "I'll claim a trend even if only one paper supports it — sounds smarter." | One paper is not a trend. Cite specifically: "#3 explores X" rather than "the field is moving toward X". Every trend claim needs at least two papers. |
| "I'll skip the `#N` citations — they look ugly." | Citations are how the user can verify and follow up. Without them the overview is ungrounded prose that erodes trust in the digest. |

## Red Flags

- The runner exits 0 but writes 0 recommendations: filters or sources
  are too tight; suggest relaxing the recipe.
- The runner exits 2 with `IntegrationError`: external API is down or
  rate-limited; offer to retry with backoff or to use cached data.
- The user keeps invoking `paperwiki:digest` at sub-minute cadence:
  rate-limits will follow; encourage scheduling instead.
- The recipe references a `vault_path` that does not exist: dedup
  silently degrades to no-op. Warn the user before they wonder why
  duplicates are showing up.
- **Today's Overview synthesis claims a topic that doesn't appear in
  any paper's matched_topics or abstract** → STOP. The synthesis is
  hallucinating. Re-read the digest carefully and re-synthesize using
  only present claims.

## Verification

- The recipe file referenced in the run actually exists.
- `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` is present.
- The runner's stdout includes a `digest.complete` log line with a
  positive (or zero with explanation) `recommendations` count.
- Every reporter's expected output file is on disk; confirm via
  `ls -la <output-dir>`.
- Top-3 summary cites real titles and scores, not invented content.
