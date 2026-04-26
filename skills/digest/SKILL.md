---
name: digest
description: Builds a research-paper digest from a recipe, writing it to disk via the configured reporters. Use when the user asks for "today's papers", invokes /paperwiki:digest, requests a daily/weekly research roundup, or wants to refresh their paper-wiki vault.
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

- The user types `/paperwiki:digest` or `/paperwiki:digest <recipe>`.
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

1. **Locate the recipe.** If the user named one (e.g. "weekly digest"),
   pick the matching `recipes/<name>.yaml` from the plugin root. If
   they did not, default to `recipes/daily-arxiv.yaml`. Confirm the
   file exists; if not, surface a clear error and offer to run setup.
2. **Confirm the environment.** Verify
   `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` exists. If missing, run
   `bash ${CLAUDE_PLUGIN_ROOT}/hooks/ensure-env.sh` and re-check.
3. **Run the digest.** Invoke
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.digest <recipe-path>`
   with an optional `--target-date YYYY-MM-DD` if the user gave one.
4. **Inspect the exit code.** 0 = success, 1 = user error
   (bad recipe / bad config), 2 = system error (network, plugin
   contract). On non-zero, surface the structured log line and offer
   the next concrete step.
5. **Summarize the outcome.** Read the reporter output paths from the
   recipe and report: how many recommendations were emitted, where
   they were written, and the titles + composite scores of the top 3.
6. **Auto-chain wiki-ingest when configured.** Read the recipe's
   `auto_ingest_top` field. If `> 0`, take the top
   `min(auto_ingest_top, top_k)` papers from the digest and chain
   `/paperwiki:wiki-ingest <canonical-id>` for each, in score order.
   The wiki-ingest SKILL handles its own idempotence (no-op when a
   source is already folded into all relevant concepts), so safe to
   run on every digest. Surface the per-paper outcome briefly to the
   user — they should see "ingesting paper #1 → updated 2 concepts,
   suggested 1 new concept" rather than a silent block of activity.
   When `auto_ingest_top` is `0` (the default), skip this step.
7. **Suggest a follow-up.** If the user has not configured a vault,
   suggest `/paperwiki:setup`. If a paper looks interesting and was
   not auto-ingested, suggest `/paperwiki:analyze <paper-id>` for a
   deeper dive or `/paperwiki:wiki-ingest <paper-id>` to fold it
   into concept articles.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll just guess which recipe the user wants without checking." | Recipes diverge a lot (daily vs weekly vs sources-only). Pick wrong and the user gets the wrong window/scoring. Always confirm or default explicitly. |
| "If the runner exits non-zero, the message is enough." | Exit codes are coarse. Read the structured log line (`digest.failed`) and explain the failure in plain English. |
| "Skipping the env check is fine; venv usually exists." | First runs and venv corruption are exactly when this SKILL gets called. Always confirm the `.installed` stamp before invoking the runner. |
| "Top 3 summary is fluff." | Without it the user re-opens the digest file to find anything notable. The summary makes the SKILL useful end-to-end. |

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

## Verification

- The recipe file referenced in the run actually exists.
- `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` is present.
- The runner's stdout includes a `digest.complete` log line with a
  positive (or zero with explanation) `recommendations` count.
- Every reporter's expected output file is on disk; confirm via
  `ls -la <output-dir>`.
- Top-3 summary cites real titles and scores, not invented content.
