# Obsidian conventions paper-wiki targets

> Tasks 9.161 / 9.162 / 9.164 / **D-D** / **D-N**: paper-wiki is
> Obsidian-native by design. This doc covers the on-disk conventions
> the plugin assumes, the recipe flags that toggle them, and the
> Templater patterns that compose with the rest.

paper-wiki writes Markdown to your vault in a shape that Obsidian
indexes natively — Properties API frontmatter, Wiki/.graph/ sidecar,
typed subdirs under `Wiki/`, and Obsidian-flavored callouts. This
doc spells out the conventions so you can build custom Templater
templates, Dataview queries, or third-party tooling against a stable
contract.

---

## 1. Properties API frontmatter (task 9.161 / **D-D**)

Every Markdown file paper-wiki writes carries a six-field Obsidian
Properties block:

| Field        | YAML type          | Purpose |
|--------------|--------------------|---------|
| `tags`       | list of strings    | Lowercased + nested-tag-friendly (`cs.LG` → `cs/lg`). Obsidian's tag pane groups by area. |
| `aliases`    | list of strings    | Alternate names; Obsidian wires up `[[wikilink]]` aliases automatically. |
| `status`     | string             | One of `draft` / `reviewed` / `stale`. Drives the wiki-lint `STATUS_MISMATCH` rule. |
| `cssclasses` | list of strings    | Obsidian scopes per-note CSS rules to any class in this list. |
| `created`    | ISO-8601 string    | First-write timestamp with timezone offset. |
| `updated`    | ISO-8601 string    | Most-recent-write timestamp; updated on every `upsert_paper` / `upsert_concept`. |

The shape is locked at v0.4.x. See [`references/dataview-recipes.md`](dataview-recipes.md)
for queries that target these fields.

### Per-paper extras

`Wiki/papers/<id>.md` files carry the Properties block plus paper-specific
keys: `canonical_id`, `title`, `confidence`, `domain`, `published_at`,
`landing_url`, `pdf_url`, `citation_count`, `score_breakdown`,
`related_concepts`, and `last_synthesized`.

### Typed-entity extras (task 9.156)

`Wiki/{concepts,topics,people}/<slug>.md` files add:

* `type`: one of `concept` / `topic` / `person`.
* `name`: human-readable display name.
* `definition` (concepts) / `description` (topics).
* `papers`: list of canonical IDs the entry is linked to.
* `concepts` (topics): list of related concepts.
* `collaborators` (people): list of co-authored people slugs.
* `affiliation` (people, optional): plain string.

---

## 2. Callouts (task 9.162 / recipe flag `obsidian.callouts`)

The Obsidian callout shape is `> [!type] Optional Title` followed by
`> ` -prefixed body lines. paper-wiki uses three callout types:

| Slot       | Callout                       | Source                                      |
|------------|-------------------------------|---------------------------------------------|
| Abstract   | `> [!abstract] Abstract`      | Reporter + wiki backend (callouts on)       |
| Metadata   | `> [!info] Metadata`          | Obsidian reporter (always on)               |
| Overview   | `> [!summary] Today's Overview` | Obsidian reporter (always on)             |

The `obsidian.callouts: true` (default) recipe flag turns the Abstract
section into a callout. Set `obsidian.callouts: false` (e.g. in
`recipes/sources-only.yaml`) to fall back to the legacy `## Abstract`
heading shape so plain-Markdown consumers stay readable.

### SKILL synthesis conventions

When a SKILL fills the per-paper synthesis slot
(`<!-- paper-wiki:per-paper-slot:{canonical_id} -->`), prefer these
callout types for emphasis blocks:

* `> [!note] Key claims` — what the paper argues.
* `> [!warning] Caveats` — limitations, edge cases, threats to validity.
* `> [!example] Methods` — short methodology summary.

These are conventions, not enforced — Obsidian renders any callout
type, and unknown types fall back to a generic style.

---

## 3. Templater (task 9.164 / recipe flag `obsidian.templater`)

[Templater](https://silentvoid13.github.io/Templater/) is an Obsidian
plugin that evaluates `<%* ... %>` (execute) and `<% ... %>` (output)
expressions against a JS-like API exposing `tp.file.*`, `tp.date.*`,
and other helpers.

### Recipe flag

Set `obsidian.templater: true` in your recipe (or
`recipes/_defaults.yaml`) when every user of the recipe has the
Templater plugin installed. Default is **off** because users without
Templater would see the syntax as literal text.

```yaml
obsidian:
  callouts: true
  templater: true
```

### What paper-wiki injects when the flag is on

When `obsidian.templater: true`, the per-paper Notes section gets a
live "last edited" stamp:

```markdown
## Notes

_Last edit: <%* tR += tp.file.last_modified_date('YYYY-MM-DD HH:mm') %>_

_Your annotations and follow-up questions go here._
```

Templater re-evaluates the expression every time Obsidian re-renders
the note, so the stamp stays current without re-running paper-wiki.

### Other Templater patterns to layer in your own templates

paper-wiki doesn't write these by default, but they compose cleanly
with the frontmatter contract above. Drop them into your own
templates or directly into note bodies:

```markdown
<%* tR += tp.file.title %>

Created: <% tp.file.creation_date('YYYY-MM-DD') %>
Vault path: <% tp.file.path(true) %>
```

Reference: [Templater internal modules](https://silentvoid13.github.io/Templater/internal-functions/internal-modules/internal-modules.html).

---

## 4. `Wiki/.graph/` sidecar (task 9.157 / **D-B**)

`paperwiki wiki-compile-graph` writes two JSONL files under
`<vault>/Wiki/.graph/`:

* `edges.jsonl` — one row per typed graph edge (`builds_on` /
  `cites` / etc.); see `paperwiki.core.models.EdgeType`.
* `citations.jsonl` — bibliographic citation rows.

The `.graph/` directory starts with a leading dot so Obsidian skips
it during note indexing — your graph view, search, and tag pane
ignore the sidecar entirely.

---

## 4.5 `<vault>/.paperwiki/` private state (task 9.167 / **D-O**)

paper-wiki keeps every piece of vault-bound mutable state under a
single hidden namespace at `<vault>/.paperwiki/`:

| Path                             | Owner                  | Purpose |
|----------------------------------|------------------------|---------|
| `run-status.jsonl`               | digest runner (9.167)  | Append-only ledger; one JSONL line per digest run with source counts, filter drops, final paper count, elapsed_ms, optional error class/message. |
| `dedup-ledger.jsonl`             | dedup filter (9.168)   | Anti-repetition memory; vault-global per **D-M**. |
| `properties-migration-backup/`   | migrate-properties     | SHA-256 manifest backup before frontmatter rewrites. |
| `migration-backup/`              | migrate-v04            | SHA-256 manifest backup before typed-subdir migration. |

The leading dot is the same trick the `.graph/` sidecar uses —
Obsidian skips dotfiles during indexing, so the namespace is invisible
in the note pane, search, graph view, and tag pane.

### Why the vault, not `~/.config/paperwiki`?

Per **D-O**, vault-bound state means cross-machine sync (Obsidian Sync,
Syncthing, Git) carries the history with the vault. A user who opens
their vault on a fresh machine still sees:

- Their dedup history (no re-recommended papers).
- Their run-status ledger (audit trail across the move).
- Their migration backups (rollback path stays intact).

Storing this in `~/` would strand history on whichever machine ran
the digest.

### Inspecting the run-status ledger

```bash
paperwiki status --vault ~/Documents/MyVault
```

prints the last 5 rows after the install-health section. The full
JSONL is yours to grep / `jq` / pipe into Dataview if you want a
custom view.

---

## 5. Image embeds (task 9.165)

`/paper-wiki:extract-images` pulls figures from arXiv source tarballs
and writes them under `Wiki/sources/<id>/images/`. Embeds use
Obsidian's wikilink-with-width syntax:

```markdown
![[arxiv_2506.13063/images/Figure_1.png|800]]
```

Obsidian renders the image inline at the requested width; markdown
viewers that don't speak wikilinks fall back to displaying the link
text.

---

## See also

* [`references/dataview-recipes.md`](dataview-recipes.md) — copy-paste
  Dataview queries that target this contract.
* [`tasks/plan.md`](../tasks/plan.md) — full v0.4.x plan with
  decision log (D-A through D-S).
* [`SPEC.md`](../SPEC.md) — top-level paper-wiki contract.
