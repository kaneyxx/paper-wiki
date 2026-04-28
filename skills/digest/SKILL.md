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

1. **Locate the recipe.** Run this exact bash to resolve `$RECIPE`.
   **DO NOT** use `ls`, `find`, `cd`, or relative paths — those reliably
   land in the plugin starter directory and pick the wrong recipe.

   ```bash
   CONFIG_ROOT="${PAPERWIKI_HOME:-${PAPERWIKI_CONFIG_DIR:-$HOME/.config/paper-wiki}}"
   name="${1:-daily}"
   case "$name" in
     weekly)         name="weekly-deep-dive" ;;
     bio|biomedical) name="biomedical-weekly" ;;
   esac
   if [ -f "$CONFIG_ROOT/recipes/$name.yaml" ]; then
       RECIPE="$CONFIG_ROOT/recipes/$name.yaml"
   elif [ -f "$CLAUDE_PLUGIN_ROOT/recipes/$name.yaml" ]; then
       RECIPE="$CLAUDE_PLUGIN_ROOT/recipes/$name.yaml"
       echo "WARN: using bundled template; no personal recipe at $CONFIG_ROOT/recipes/$name.yaml"
   else
       echo "ERROR: recipe '$name' not found. Run /paper-wiki:setup."
       exit 1
   fi
   echo "Using recipe: $RECIPE"
   ```

   The `echo "Using recipe:"` line is **mandatory** — it gives the user
   visibility into which recipe was actually picked. If the user passes
   an absolute path explicitly (e.g. `/paper-wiki:digest /abs/path.yaml`),
   skip the case mapping and assign `RECIPE="$1"` directly.

   The recipe-name argument convention: `daily` (default), `weekly`,
   `biomedical`/`bio`, or any other custom personal recipe name from
   `~/.config/paper-wiki/recipes/`. If the user explicitly passes
   `daily-arxiv` or `weekly-deep-dive`, treat those as exact recipe
   names (no mapping needed) and look them up directly.
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
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.digest "$RECIPE"`
   with an optional `--target-date YYYY-MM-DD` if the user gave one.
   Always use the `$RECIPE` variable resolved in Step 1 — never hand-pick
   a path or interpolate a `<recipe-path>` placeholder, or you re-open
   the v0.3.32 ambiguity that routed users to the bundled starter.
5. **Inspect the exit code.** 0 = success, 1 = user error
   (bad recipe / bad config), 2 = system error (network, plugin
   contract). On non-zero, surface the structured log line and offer
   the next concrete step.
6. **Summarize the outcome.** Read the reporter output paths from the
   recipe and report: how many recommendations were emitted, where
   they were written, and the titles + composite scores of the top 3.
7. **Auto-chain extract-images + wiki-ingest when configured.** Read the
   recipe's `auto_ingest_top` field. If `> 0`, **immediately and without
   asking the user**, take the top `min(auto_ingest_top, top_k)` papers
   from the digest and for each, **in this order**:

   a. **Extract images first** (for `arxiv:` ids only). Invoke
      `python -m paperwiki.runners.extract_paper_images <vault>
      <canonical-id>` so figures are on disk before wiki-ingest runs.
      Continue on failure (a 404 or non-arXiv id is not a digest
      failure). Cache hits are normal — no warning when `cached=true`.

      After running extract-images for all top-N papers, **always emit
      a per-paper summary block** to the terminal before proceeding to
      Step 7b. Format:

      ```
      Image extraction:
        #1 arxiv:XXXX.YYYYY — success (2 figures: 1 arxiv-source, 1 pdf-figure)
        #2 arxiv:XXXX.YYYYY — success (0 figures, source has no images)
        #3 arxiv:XXXX.YYYYY — failed (404 — arXiv source bundle missing)
      ```

      Classify each paper into one of four outcomes using the
      `sources` dict from the runner's JSON output:
      - **success-with-figures**: exit 0, `image_count > 0` — report
        count + per-source breakdown from `sources` dict.
      - **success-no-figures**: exit 0, `image_count == 0` — report
        "0 figures, source has no images".
      - **skipped-non-arxiv**: id does not start with `arxiv:` — report
        "skipped (non-arXiv id, no source bundle)".
      - **failed-with-error**: non-zero exit code — report "failed
        (error)" with the first line of stderr or the structured log
        key.

      The summary lives in the SKILL terminal output only (not in the
      digest file). Do NOT skip the block even when all extractions
      succeed — the user wants a confidence signal that extraction ran.
   b. **Then wiki-ingest.** Invoke `/paper-wiki:wiki-ingest
      <canonical-id> --auto-bootstrap --fold-citations` for each. The
      `--auto-bootstrap` flag stubs missing concepts; `--fold-citations`
      folds the source citation into pre-existing concepts atomically.
      No LLM work in this path. Surface `created_stubs` and
      `folded_citations` counts per paper.

   The user setting `auto_ingest_top: N` IS their pre-approval — do NOT
   prompt "shall I chain?" or "want me to ingest?". Just do it. When
   `auto_ingest_top` is `0` (the default), skip this step.

   **Note:** interactive `/paper-wiki:wiki-ingest <id>` invocations
   keep the manual confirm prompt — only the digest auto-chain uses
   `--auto-bootstrap`.

8. **Per-paper Detailed report synthesis.** Synthesize Detailed reports
   **only for the top `auto_ingest_top` papers** (i.e. papers ranked 1
   through `min(auto_ingest_top, top_k)`). For papers ranked below
   `auto_ingest_top`, replace the
   `<!-- paper-wiki:per-paper-slot:{canonical_id} -->` marker with this
   single-line teaser instead of a full report:

   > _Run `/paper-wiki:analyze <canonical-id>` for a deep dive into this
   > paper, or `/paper-wiki:wiki-ingest <canonical-id>` to fold it into
   > your concept articles._

   If `auto_ingest_top` is 0, skip Detailed report synthesis entirely for
   ALL papers — every slot gets the teaser line only. If
   `auto_ingest_top >= top_k` (user wants every paper deep-treated),
   synthesize all.

   For each **top-N** paper, replace the marker with the full
   **Detailed report** block containing:
   - 2–3 sentence **"Why this matters"** framing from the abstract.
   - 2–4 bullet **"Key takeaways"** (concrete claims from the abstract;
     never invented).
   - **Figures** (if `Wiki/sources/<canonical-id>/images/` exists and is
     non-empty — sort alphabetically, deterministic listing — pick the
     FIRST 1 file if the directory has 1–2 figures total; pick the FIRST
     2 files if the directory has 3+ figures): embed each as
     `![[Wiki/sources/<canonical-id>/images/<file>|600]]`. Width `|600`
     is intentionally narrower than the card teaser's `|700` so both
     placements are visually distinct. Skip this section silently if the
     directory is empty or does not exist (e.g. `paperclip:` / `s2:`
     ids with no arXiv source bundle).
   - 1–2 sentences **"Score reasoning"** that INTERPRET why the paper
     scores the way it does — not a list of sub-scores. The sub-scores
     are already visible in the metadata callout above; your job is to
     synthesize meaning. Requirements:
     - **1–2 sentences maximum** (no bullet-style sub-score list).
     - **Actively interpret WHY**: what combination of signals drives
       the score? What does it mean for the user's reading priorities?
     - **Acknowledge limits explicitly**: if rigor is low, say why
       (e.g. "brand-new arXiv, no replications yet"). If momentum is
       moderate, say why (e.g. "just published, citation count
       settling").
     - **Cite specific topic matches when relevance is high** (e.g.
       "matches 3 of your 4 topics") rather than listing keywords.
     - **GROUNDED in the sub-scores**: must reference at least one
       concrete sub-score number as evidence for the interpretation,
       not ignore the numbers entirely.
     - **Forbidden pattern**: "0.79 — relevance 0.99, novelty 0.98,
       momentum 0.50, rigor 0.50" is a transcription, not an
       interpretation. Do not do this.

     Good examples:
     > Punches above its weight: novelty is genuinely high (parallel
     > RL on LLM agents is unexplored ground), and rigor is held back
     > only by being brand-new — expect citations to accrue within
     > 6–12 months.

     > Strong topic match but momentum and rigor lag because this is a
     > re-implementation of older work; useful for replication studies,
     > less so for cutting-edge tracking.

   Cite the paper with `#N` matching its digest index. Batch the
   prompts when feasible (one LLM call for all top-K papers) to amortize
   cost; fall back to per-paper if the batched output truncates. If a
   marker is already gone (re-run case), skip it.

9. **Synthesize Today's Overview.** Read the digest file at the path
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

   **Do this last** — after auto-chain and per-paper synthesis — so the
   overview can reference the ingested concepts and extracted figures
   that Step 7 produced.

10. **Suggest a follow-up.** If the user has not configured a vault,
   suggest `/paper-wiki:setup`. If a paper looks interesting and was
   not auto-ingested, suggest `/paper-wiki:analyze <paper-id>` for a
   deeper dive or `/paper-wiki:wiki-ingest <paper-id>` to fold it
   into concept articles.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "I'll just guess which recipe the user wants without checking." | Recipes diverge a lot (daily vs weekly vs sources-only). Pick wrong and the user gets the wrong window/scoring. Always confirm or default explicitly. |
| "I'll just `ls recipes/` to see what's available." | NO. `ls` lands in plugin starter and picks the wrong recipe. Use the bash above. |
| "If the runner exits non-zero, the message is enough." | Exit codes are coarse. Read the structured log line (`digest.failed`) and explain the failure in plain English. |
| "Skipping the env check is fine; venv usually exists." | First runs and venv corruption are exactly when this SKILL gets called. Always confirm the `.installed` stamp before invoking the runner. |
| "Top 3 summary is fluff." | Without it the user re-opens the digest file to find anything notable. The summary makes the SKILL useful end-to-end. |
| "I'll claim a trend even if only one paper supports it — sounds smarter." | One paper is not a trend. Cite specifically: "#3 explores X" rather than "the field is moving toward X". Every trend claim needs at least two papers. |
| "I'll skip the `#N` citations — they look ugly." | Citations are how the user can verify and follow up. Without them the overview is ungrounded prose that erodes trust in the digest. |
| "I'll ask the user before chaining wiki-ingest — being safe." | NO. `auto_ingest_top: N` in the recipe IS the user's pre-approval. Asking "want me to chain?" defeats the whole point of the field — they configured it precisely so they don't have to answer that prompt every morning. Just do it. (If they don't want auto-chain, they set `auto_ingest_top: 0`.) |
| "I'll skip the image-extraction summary if all extractions succeeded — it's noise." | Wrong. The user wants a confidence signal that extraction ran. Even all-success is useful confirmation. Always emit the per-paper summary block with all four outcome classifications; never silently absorb any result. |
| "I'll invent per-paper claims that aren't in the abstract — makes the report richer." | NO. Every claim in the Detailed report MUST come from the abstract or the score breakdown. Hallucinated methods and results erode the user's trust in the digest. One wrong claim per day = the user stops reading. |
| "I'll skip image extraction because Obsidian renders without it." | The user wants figures. Figures appear in the NEXT digest run's inline teasers. Skipping extraction silently delays that by one day and the user can't tell why their digest looks bare. |
| "I'll run wiki-ingest before extract-images to save a step." | Extract-images must run FIRST so figures are on disk when `_try_inline_teaser` is invoked. Swapping the order means day-2 teasers are missing. The order is intentional. |
| "The card teaser already shows a figure — the Detailed report doesn't need one." | The card teaser is the FIRST figure outside the synthesized report. The inlined figures inside the Detailed report are different — they ground the prose with specific visual evidence as the user reads. Both placements are intentional. |
| "I'll embed all 7 architecture diagrams to be thorough." | 1–2 figures max per Detailed report. Use the heuristic: sort alphabetically, pick the first 1 (for directories with 1–2 figures) or first 2 (for 3+ figures). Excessive figures clutter the digest and slow Obsidian render. |
| "I synthesized Detailed reports for all 10 papers — more value for the user." | Wrong. `auto_ingest_top` controls treatment depth. Only top-N get the full Detailed report (Why this matters / Key takeaways / inline figures / Score reasoning). The rest get a teaser pointing at `/paper-wiki:analyze`. Respect the user's depth budget. |
| "I'll just list the sub-scores — it's accurate." | Accurate but useless. The user can read the metadata callout. Synthesize an interpretation: WHY this score? WHAT does it mean? WHAT to expect next? One transcription per digest erodes trust faster than one hallucination. |
| "If the score is moderate (e.g. 0.65), there's nothing interesting to say." | Wrong. Moderate scores are the most interesting — explain the trade-off (e.g. "Strong topic match but momentum lags because this is a re-implementation of older work; useful for replication studies, less so for cutting-edge tracking"). |

## Red Flags

- Claude wrote `ls recipes/`, `cd ${CLAUDE_PLUGIN_ROOT}`, or used a
  relative recipe path → STOP. Re-read Step 1.
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
- **Detailed reports synthesized for all N papers when `auto_ingest_top`
  is 3** → STOP. `auto_ingest_top` is the depth-of-treatment envelope.
  Only top-3 get the full Detailed report; the rest get the analyze-link
  teaser. Fix by replacing the extra reports with the teaser line.
- **Score reasoning starts with the composite number and just restates
  the four sub-scores in parentheses** → STOP. The user has the metadata
  callout. Synthesize an interpretation: explain WHY the score is what it
  is, what it means, and what to expect. Do not transcribe the metadata.

## Verification

- The recipe file referenced in the run actually exists.
- `${CLAUDE_PLUGIN_ROOT}/.venv/.installed` is present.
- The runner's stdout includes a `digest.complete` log line with a
  positive (or zero with explanation) `recommendations` count.
- Every reporter's expected output file is on disk; confirm via
  `ls -la <output-dir>`.
- Top-3 summary cites real titles and scores, not invented content.
- After Step 7a extract-images auto-chain, a per-paper summary block
  was emitted to the user terminal with one line per paper. No failure
  (404, non-arXiv id, zero-figure result) was silently absorbed. Each
  line uses one of the four classifications: success-with-figures /
  success-no-figures / skipped-non-arxiv / failed-with-error.
- Each paper with extracted images has at least one
  `![[Wiki/sources/<id>/images/...|600]]` line in the Detailed report block.
- After Step 8, exactly `min(auto_ingest_top, top_k)` per-paper slots have
  synthesized Detailed reports; the remaining slots have the teaser line.
- Each Score reasoning sentence interprets WHY (not just WHAT); does not
  consist solely of the four sub-score numbers restated in parentheses;
  references at least one specific signal beyond raw numbers (e.g. topic
  match count, recency context, dataset release, citation trajectory).
