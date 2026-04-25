# Recipes

A *recipe* is a YAML file that names paper-wiki plugins by their registry
key and supplies their constructor configs. The runner translates the
recipe into a fully-wired pipeline.

## Bundled recipes

| Recipe | Purpose |
|--------|---------|
| [`daily-arxiv.yaml`](daily-arxiv.yaml) | Yesterday's arXiv submissions, filtered for vision-language and agents, deduped against the Obsidian vault. |
| [`weekly-deep-dive.yaml`](weekly-deep-dive.yaml) | A 30-day window with citation-aware scoring across arXiv + Semantic Scholar. |
| [`sources-only.yaml`](sources-only.yaml) | Minimal pipeline for first-time setup smoke testing — no filters, no vault dependency. |

## Editing a recipe

Every recipe must declare:

- `name`: A short identifier; appears in logs and the run context.
- `sources`: ≥ 1 source plugin spec.
- `scorer`: Exactly one scorer plugin spec.
- `reporters`: ≥ 1 reporter plugin spec.

Optional:

- `filters`: 0 or more filter plugin specs (applied in declaration order).
- `top_k`: Truncate the sorted recommendation list.

Each plugin spec is a mapping:

```yaml
- name: <registry-key>
  config:
    # constructor kwargs for the plugin
```

See `src/paperwiki/plugins/` for the available plugins and their
parameters. Unknown plugin names raise `UserError` at recipe load time.

## Path expansion

Any recipe path that starts with `~` is expanded to the user home
directory at load time. Use absolute or `~`-prefixed paths so recipes
remain portable across machines.
