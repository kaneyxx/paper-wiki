---
description: Pull real paper figures from arXiv source and embed them in Wiki/sources/
---

Invoke the paper-wiki extract-images SKILL.

Accept the paper as an arXiv canonical id (`arxiv:1234.5678`) or an
arXiv URL (canonicalize first). Validate that the id starts with
`arxiv:` — paperclip / S2 / PMC papers don't have source-tarball
URLs and must be handled separately.

Run
`${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.extract_paper_images
<vault> <canonical-id>` and surface the JSON result. If
`image_count > 0`, point the user at `/paper-wiki:wiki-ingest` to fold
the now-illustrated source into concept articles. If
`image_count == 0`, tell the user the paper is PDF-only on arXiv
(legitimate, not a failure) and offer `/paper-wiki:analyze` as the
text-only fallback.

Do NOT manually edit the `## Figures` section — the runner owns it
and will overwrite on the next call. Put any prose annotations in the
`## Notes` section, which the runner never touches.
