# Dataview recipes for paper-wiki vaults

> Task 9.163 — copy-paste Dataview snippets that work against the
> v0.4.x paper-wiki frontmatter contract (Properties API per
> [decision **D-D**](../tasks/plan.md#round-1-2026-04-30) /
> [decision **D-N**](../tasks/plan.md#round-2-2026-04-30)).

The [Dataview](https://blacksmithgu.github.io/obsidian-dataview/)
plugin treats YAML frontmatter as queryable data. paper-wiki ships with
a stable frontmatter contract — `tags` / `aliases` / `status` /
`cssclasses` / `created` / `updated` plus per-paper extras like
`canonical_id` / `published_at` / `score_breakdown` — so you can drop
these blocks into any note and they'll surface live data from your
vault.

Each block is verified against the synthetic 100-note fixture
(`tests/fixtures/synthetic_vault_100/`) so the field references are
guaranteed to round-trip.

---

## 1. Recently published papers (last 30 days)

Lists every paper in `Wiki/papers/` whose `published_at` falls in the
last 30 days, newest first.

```dataview
TABLE
  published_at as "Published",
  domain as "Domain",
  citation_count as "Citations"
FROM "Wiki/papers"
WHERE published_at >= date(today) - dur(30 days)
SORT published_at desc
```

---

## 2. Papers by tag

Replace `cs/cv` with the tag you care about. Per **task 9.161**, paper-wiki
normalizes arXiv categories like `cs.CV` into nested
tag form (`cs/cv`); both forms work in Dataview but the nested form
groups cleanly in Obsidian's tag pane.

```dataview
TABLE
  published_at as "Published",
  citation_count as "Citations"
FROM "Wiki/papers"
WHERE contains(tags, "cs/cv")
SORT published_at desc
```

---

## 3. Papers by topic

For a topic note at `Wiki/topics/<topic>.md`, list every paper that
references it via the `papers` frontmatter field. Drop this block into
the topic note itself; Dataview implicitly scopes to the current file.

```dataview
TABLE
  published_at as "Published",
  domain as "Domain"
FROM "Wiki/papers"
WHERE contains(file.outlinks, this.file.link)
  OR contains(papers, this.file.name)
SORT published_at desc
```

---

## 4. Paper count by month

A bar-chart-friendly aggregate: how many papers landed in each month
of the year. Useful for spotting reading-velocity trends.

```dataview
TABLE rows.file.link as "Papers", length(rows) as "Count"
FROM "Wiki/papers"
WHERE published_at
GROUP BY dateformat(published_at, "yyyy-MM") as month
SORT month desc
```

---

## 5. Missing summaries (status = draft, no Key Takeaways yet)

Every per-paper note ships with a Key Takeaways placeholder until
`/paper-wiki:wiki-ingest` fills it in. This block surfaces the
backlog so you know what's still to ingest.

```dataview
TABLE
  published_at as "Published",
  status as "Status"
FROM "Wiki/papers"
WHERE status = "draft"
SORT published_at desc
```

---

## 6. Concepts with the most paper backlinks

Surfaces the densest hubs in your wiki graph — concepts that appear in
the most papers.

```dataview
TABLE length(papers) as "Linked papers"
FROM "Wiki/concepts"
WHERE papers
SORT length(papers) desc
LIMIT 20
```

---

## 7. Recently updated notes (any type)

Combines all four typed subdirs and surfaces the most recently
updated entries. Per **task 9.161**, the `updated` field is an
ISO-8601 string with timezone offset, so Dataview's date arithmetic
works directly.

```dataview
TABLE
  type as "Type",
  updated as "Updated"
FROM "Wiki"
WHERE updated
SORT updated desc
LIMIT 25
```

---

## Notes

* Dataview ignores leading-dot directories, so the `Wiki/.graph/`
  sidecar from `wiki-compile-graph` doesn't pollute these queries.
* The frontmatter contract above is locked at v0.4.x; if you build
  custom recipes, target the field names listed in
  `tests/unit/test_dataview_recipes_doc.py::EMITTED_FIELDS`.
* For dataviewjs (full Javascript queries) examples, see Dataview's
  [own docs](https://blacksmithgu.github.io/obsidian-dataview/api/intro/).
