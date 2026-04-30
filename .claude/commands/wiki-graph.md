---
description: Query the v0.4.x wiki knowledge graph (papers citing X, concepts in topic Y, collaborators of Z)
---

Invoke the paper-wiki wiki-graph skill.

If the user provided a query target inline (e.g. "what cites
arxiv:2401.00001"), pass it verbatim to the runner. If not, ask
which of the three queries they want and what target — keep the
clarification to one round.

After the runner returns JSON, synthesise the answer in natural
language with concrete `[[entity_id]]` wikilinks. Cap inline
listings at 10 records; offer to dump the full list if more.
