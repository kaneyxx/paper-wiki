---
description: Search biomedical literature (bioRxiv, medRxiv, PubMed Central) via paperclip MCP
---

Invoke the paper-wiki bio-search SKILL.

Accept the search expression as free text. If the user invoked the
command without a query, ask what they want to search for and which
sub-corpora (bioRxiv preprints, medRxiv preprints, peer-reviewed PMC,
or all three).

Before running any paperclip MCP tool, confirm the server is
registered by reading the `mcp_servers` field from
`paperwiki.runners.diagnostics`. If `paperclip` is absent, stop and
hand the user the registration steps from
`docs/paperclip-setup.md` rather than running `claude mcp add`
yourself.

After surfacing the hits, offer to:

- analyze a specific result via `/paper-wiki:analyze`
- save selected results as `Wiki/sources/<id>.md` files (and chain to
  `/paper-wiki:wiki-ingest` so concepts stay current)
- refine the search

Do not paraphrase abstracts — show the paperclip output verbatim so
the user can audit what the search engine returned.
