---
name: extract-images
description: Pulls real paper figures from arXiv source tarballs and embeds them in the source's Wiki/papers/<id>.md file. Use when the user invokes /paper-wiki:extract-images, asks to "show me the figures from <paper>", "pull the architecture diagram", "extract images from <id>", or follows up on a digest entry that has an empty Figures section.
---

# paper-wiki Extract Images

## Overview

Extract Images downloads the arXiv source bundle for a paper, pulls
the real paper figures (architecture diagrams, experimental plots,
qualitative results) out of common figure directories
(`figures/`, `fig/`, `pics/`, `images/`, `img/`), and embeds them
into the `## Figures` section of `Wiki/papers/<id>.md` using
Obsidian wikilink-with-width syntax.

This SKILL is the visual half of the per-paper note story. The text
half (frontmatter + Core Information + Abstract + Key Takeaways +
Notes) is filled by `/paper-wiki:digest`, `/paper-wiki:analyze`, and
`/paper-wiki:wiki-ingest`.

## When to Use

- The user types `/paper-wiki:extract-images <canonical-id>`.
- The user says "show me the figures for <paper>", "pull the
  architecture diagram from <id>", "what does the method look like".
- The user is reviewing a fresh digest and wants the figures from a
  ranked paper before deciding whether to deep-dive.
- The `## Figures` section in a `Wiki/papers/<id>.md` file is empty
  (still has the placeholder text) — that's the explicit prompt to
  run this SKILL.

**Do not use** for non-arXiv canonical ids (the source-tarball URL
only exists for `arxiv:` papers — paperclip/PMC papers don't have
one). Surface that to the user instead of running the runner.

## Process

1. **Validate canonical id.** It must start with `arxiv:`. If the user
   handed an arXiv URL or a fuzzy title, normalize first via the
   `paperwiki._internal.normalize` helpers (or just ask).
2. **Run the runner.** Run this exact bash to invoke the
   extract-images runner. The `export PATH=...` line is mandatory —
   fresh-install users may not have `~/.local/bin` on PATH yet
   (D-9.34.6).

   ```bash
   source "$HOME/.local/lib/paperwiki/bash-helpers.sh" 2>/dev/null || {
       echo "ERROR: paper-wiki bash-helpers missing at ~/.local/lib/paperwiki/bash-helpers.sh." >&2
       echo "  Fix: exit Claude Code and re-open — the SessionStart hook installs the helper." >&2
       echo "  Persistent failures: ~/.local/lib/ may be unwritable; re-run \$CLAUDE_PLUGIN_ROOT/hooks/ensure-env.sh." >&2
       exit 1
   }
   paperwiki_ensure_path
   paperwiki extract-images <vault> <canonical-id>
   ```

   Read the JSON output. Pass `--cache-bust`, `--max-figures N`, or
   `--from-pdf` if the user asked for those modes.
3. **Surface the result.** Confirm `image_count` to the user. If
   `image_count == 0`, tell them the paper is probably PDF-only on
   arXiv (legitimate, no failure) and offer next steps:
   `/paper-wiki:analyze` for a Claude-written deep dive based on the
   abstract, or download the PDF themselves.
4. **Optionally preview.** If the user asks "show me the teaser" or
   similar, render one or two of the embedded figures in a chat
   message via Obsidian wikilink — paper-wiki has no PDF→preview
   capability so this is just the wikilink, not actual image
   rendering.
5. **Hand off to wiki-ingest.** Suggest the user run
   `/paper-wiki:wiki-ingest <id>` next so the freshly imaged source
   folds into concept articles with the figure references intact.

## Common Rationalizations

| Excuse | Why it's wrong |
|---|---|
| "The user wants images, I'll grab the PDF and convert pages." | PDF page renders include logos, equations, and full-text noise. The arXiv source tarball has the AUTHOR'S OWN figure files — that's what users want. Always go through the runner. |
| "Tarball is missing — I'll just say 'failed' and move on." | A 0-figures result is normal for older PDF-only papers. Tell the user explicitly so they don't think it's a bug. |
| "I'll add my own commentary into the `## Figures` section." | The runner overwrites that section verbatim each call. Put commentary in `## Notes`, which the runner never touches. |
| "Force a re-download every time to make sure it's fresh." | The cache exists for a reason — arXiv rate-limits source downloads more aggressively than the API. Only use `--force` when the user explicitly asks. |

## Red Flags

- The user gave a `paperclip:` or `s2:` canonical id — there is no
  arXiv source URL. Surface this and offer alternatives instead of
  running the runner.
- `Wiki/papers/<id>.md` doesn't exist — the runner errors with
  `UserError`. Tell the user to run `/paper-wiki:digest` or
  `/paper-wiki:analyze` first to create the source stub.
- `image_count` is suspiciously high (> 30) — usually means the
  source bundle has glyph rasters or figure subsets we accidentally
  caught. Eyeball the list before suggesting wiki-ingest.
- arXiv returns 503 — they throttle source-tarball downloads more
  than the API. Wait an hour, retry. Do NOT keep hammering.

## Verification

- `Wiki/papers/<id>/images/` exists and contains at least the count
  the runner reported.
- The source `.md` file's `## Figures` section now has
  `![[<id>/images/<filename>|800]]` embeds (or the
  "no figures found" note when `image_count == 0`).
- The source `.md` file's `## Notes` section is unchanged from
  before the run.
- `Wiki/.cache/sources/<arxiv-id>.tar.gz` exists for future
  re-extracts without HTTP fetches.
