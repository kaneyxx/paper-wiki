# wiki-query ranking formula (v0.4.x — task 9.171)

> Replaces the v0.3.x pure-keyword score with a composite of
> **frequency × recency × tag-match**. Weights live in
> `paperwiki.runners.wiki_query.RankingWeights`; CLI flags
> `--weight-frequency` / `--weight-recency` / `--weight-tag-match` let
> a recipe author override per-call.

## What the score answers

Given a multi-word query, paper-wiki's vault search picks notes that
**both match the query terms AND look like the user actually cares
about them**. The v0.3.x score got the first half right (substring
match in title + tags) but ignored the rest of the document body and
treated a year-old draft the same as a fresh capture. That made the
top-K bias toward titles that happened to contain the query word
even when the user had richer notes elsewhere.

v0.4.x's composite formula combines three signals:

| Signal       | What it captures                              | Default weight |
|--------------|-----------------------------------------------|----------------|
| **frequency**| Term occurrence count in title + body         | `1.0`          |
| **recency**  | Half-life decay against file mtime            | `0.5`          |
| **tag-match**| Exact match against frontmatter `tags:` list  | `1.0`          |

Title hits are an inner-frequency boost (`title_multiplier = 2.0` by
default) on top of the body count, so a query word in the title
counts twice. Damping is sqrt-based so a 100-occurrence note doesn't
drown out a focused 1-occurrence one.

## Formula

```text
body_freq  = Σ_terms sqrt(count(term, body))
title_hits = Σ_terms count(term, title)
tag_hits   = Σ_terms I[term ∈ tags]

age_days = (now - mtime(file)) / 86400
recency  = 2 ** (-age_days / half_life)        if recency_weight > 0 else 1
                                                # half_life default = 90 days

raw     = frequency_weight * (body_freq + title_multiplier * title_hits)
        + tag_match_weight * tag_hits
boosted = raw * (1 + recency_weight * (recency - 1))

score   = 0           if raw == 0 else  boosted
```

The recency form `(1 + w·(r − 1))` keeps a fresh doc at full weight
(`r = 1`, multiplier `1.0`) and an arbitrarily old one at `1 − w` of
its raw score, so `w = 0` cleanly disables the recency signal.

## Default weight rationale

Tuned against the project's own `.omc/wiki/` (about 6 decision pages
+ pattern notes + session logs). Smoke checks:

* `ralph boulder` → finds the canonical "ralph never-stops" decision
  page even though "boulder" appears more times in unrelated session
  logs (recency keeps the older decision page from being buried).
* `templater obsidian` → finds the v0.4.x consensus page (high
  frequency in body), not the brief mention in an old retro.
* `dedup-ledger` → finds the new task 9.168 doc page (recency hits
  hardest here — the term is both rare and recent).

If the project's wiki shape shifts (e.g. session logs grow much
larger than decision pages), revisit the half-life and frequency
multiplier. A single regression-style smoke check in
`tests/unit/runners/test_wiki_query_ranking.py` keeps the contract
(equal-frequency docs rank by recency; tag-match boosts; zero
recency weight disables recency).

## Tuning

Per-query CLI overrides:

```bash
# Recency-heavy "what changed lately" search
paperwiki wiki-query ~/Vault "obsidian" \
    --weight-frequency 0.3 --weight-recency 1.5

# Pure substring match (v0.3.x semantics)
paperwiki wiki-query ~/Vault "obsidian" \
    --weight-recency 0.0 --weight-tag-match 0.0
```

Recipe-level defaults are not yet wired in v0.4.x — recipe authors
who want a different baseline should pass the flags via their own
SKILL invocation. Promotion to a `wiki_query.weights` recipe block
is queued for v0.5+ once a real per-vault tuning need surfaces.

## See also

* [`tasks/plan.md`](../tasks/plan.md) — task 9.171 in §4 Phase 3.
* [`src/paperwiki/runners/wiki_query.py`](../src/paperwiki/runners/wiki_query.py) — `RankingWeights` + `score_document`.
* [`tests/unit/runners/test_wiki_query_ranking.py`](../tests/unit/runners/test_wiki_query_ranking.py) — contract tests for each signal.
