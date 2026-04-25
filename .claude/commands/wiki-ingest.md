---
description: Fold a source paper into the wiki, regenerating affected concept articles
---

Invoke the paper-wiki wiki-ingest skill.

If the user provided a canonical id (`arxiv:...`), URL, or fuzzy title,
resolve it before running the planner. If the user typed
`/paperwiki:wiki-ingest` with no argument, ask which paper to ingest;
suggest recent digest entries if any are available.

After the SKILL completes, summarize how many concepts were updated and
suggest running `/paperwiki:wiki-compile` to refresh the index.
