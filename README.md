# paper-wiki

> A personal research wiki builder for Claude Code. Pipeline-driven
> paper ingestion with a plugin architecture, persistent
> knowledge-accumulating wiki, and zero LLM API keys (Claude Code is
> the LLM).

`paper-wiki` turns the firehose of academic publishing into a curated,
queryable, compounding wiki. SKILLs let you fetch papers from arXiv,
Semantic Scholar, and (optionally) paperclip's biomedical corpus;
filter and score them against your research interests; persist durable
notes; and let Claude synthesize topic articles that link sources
together — all from inside Claude Code.

## Prerequisites

- **Python ≥ 3.11**. The plugin self-installs its `.venv` on first
  Claude Code session via `hooks/ensure-env.sh`. `uv` is preferred and
  used automatically when on PATH; otherwise `python3 -m venv` + `pip`.
- **Claude Code CLI** — paper-wiki *is* a Claude Code plugin; SKILLs
  run inside Claude Code, not standalone.
- **Optional**: a [Semantic Scholar API key](https://www.semanticscholar.org/product/api#api-key-form)
  (free) — bumps the rate limit from ~1 req/s to 100 req/s and is
  strongly recommended for any non-trivial use.
- **Optional**: [paperclip CLI](https://gxl.ai/blog/paperclip) for
  biomedical literature; see [`docs/paperclip-setup.md`](docs/paperclip-setup.md).

## Install

In Claude Code:

```text
/plugin marketplace add kaneyxx/paper-wiki
/plugin install paper-wiki@paper-wiki
```

The plugin self-installs its Python environment on first session — no
manual setup required.

## First-run walkthrough

### 1. Verify environment

```text
/paperwiki:setup
```

This runs `hooks/ensure-env.sh`, surfaces missing config, and reports
which optional MCP servers (e.g. paperclip) are registered. It does
**not** create any files in your vault yet.

### 2. Pick a vault

paper-wiki writes into a single directory of your choice — typically
an Obsidian vault. Pick one (or create a fresh one):

```bash
mkdir -p ~/Documents/Paper-Wiki
```

The default subdirs paper-wiki creates inside it are:

```text
~/Documents/Paper-Wiki/
├── Daily/      # daily digest output (one .md per day)
├── Sources/    # per-paper notes (created by /paperwiki:analyze)
└── Wiki/       # synthesized concept articles + per-paper source stubs
    ├── sources/
    ├── concepts/
    └── index.md
```

The defaults are deliberately friendly. If you use
[Johnny.Decimal](https://johnnydecimal.com/) or
[PARA](https://fortelabs.com/blog/para/), every subdir is configurable
per recipe — for example `daily_subdir: 10_Daily`. paper-wiki neither
requires nor blocks those conventions; see
[`docs/example-recipes/personal-johnny-decimal.yaml`](docs/example-recipes/personal-johnny-decimal.yaml).

### 3. Set up your secrets

```bash
mkdir -p ~/.config/paperwiki
cat > ~/.config/paperwiki/secrets.env <<'EOF'
export PAPERWIKI_S2_API_KEY="<your-S2-key>"
EOF
chmod 600 ~/.config/paperwiki/secrets.env
```

Bundled and personal recipes never inline the key. They reference it
via `api_key_env: PAPERWIKI_S2_API_KEY`; the recipe loader resolves
the env var at pipeline-build time, so the secret stays out of any
YAML file.

### 4. Author a personal recipe

The recipes under `recipes/*.yaml` are **templates**. Your personal
recipe lives outside the plugin tree at:

```text
~/.config/paperwiki/recipes/<name>.yaml
```

Copy a template as a starting point:

```bash
mkdir -p ~/.config/paperwiki/recipes
cp recipes/daily-arxiv.yaml ~/.config/paperwiki/recipes/daily.yaml
```

Then edit `~/.config/paperwiki/recipes/daily.yaml`:

- Change every `vault_path` and `vault_paths` reference to your vault
- Change the `topics` to keywords you actually read about
- Add `api_key_env: PAPERWIKI_S2_API_KEY` to the `semantic_scholar`
  source if you have a key (recommended)

### 5. Run your first digest

```bash
source ~/.config/paperwiki/secrets.env
.venv/bin/python -m paperwiki.runners.digest \
    ~/.config/paperwiki/recipes/daily.yaml
```

You should see ~10 paper recommendations land at:

- `<vault>/Daily/<YYYY-MM-DD>-paper-digest.md` — the human-readable
  digest with Obsidian wikilinks
- `<vault>/Wiki/sources/<id>.md` — one-per-paper source stub (when
  `wiki_backend: true` is set on the obsidian reporter)

### 6. Build the wiki

After your first digest, fold the new sources into concept articles:

```text
/paperwiki:wiki-ingest <canonical-id>
```

Claude reads the source, decides which concept articles to update or
create, and writes them under `<vault>/Wiki/concepts/`.

## SKILLs

| SKILL                         | Purpose                                                                                |
|-------------------------------|----------------------------------------------------------------------------------------|
| `/paperwiki:setup`            | Verify environment, surface missing config / MCP servers, walk first-time setup.        |
| `/paperwiki:digest`           | Run a recipe end-to-end → arXiv / S2 / paperclip → filter → score → write to vault.    |
| `/paperwiki:analyze`          | Deep-analyze one paper into a six-section note in `Sources/`, then chain wiki-ingest.   |
| `/paperwiki:extract-images`   | Pull real figures from an arXiv source tarball into `Wiki/sources/<id>/images/`.        |
| `/paperwiki:wiki-ingest`      | Fold a source into the user's concept articles (Karpathy LLM-Wiki ingest loop).         |
| `/paperwiki:wiki-query`       | Keyword search across `Wiki/concepts/` and `Wiki/sources/` with Claude-synthesized answer. |
| `/paperwiki:wiki-lint`        | Health-check: orphan concepts, stale entries, broken wikilinks, dangling sources.       |
| `/paperwiki:wiki-compile`     | Deterministic rebuild of `Wiki/index.md` from frontmatter.                              |
| `/paperwiki:migrate-sources`  | Upgrade legacy `Wiki/sources/<id>.md` files to the current section-organized format.    |
| `/paperwiki:bio-search`       | (Optional) Search bioRxiv / medRxiv / PMC via paperclip MCP, save hits as wiki sources. |

### Optional: biomedical literature

If you work in life sciences, paper-wiki integrates with
[paperclip](https://gxl.ai/blog/paperclip) (8M+ papers across bioRxiv,
medRxiv, PubMed Central):

- `/paperwiki:bio-search <query>` — search via paperclip MCP, with
  optional handoff to `/paperwiki:wiki-ingest`.
- `recipes/biomedical-weekly.yaml` — bundled recipe that uses the
  paperclip CLI as a source plugin (no MCP required).

paperclip is **opt-in**: paper-wiki's other SKILLs work without it.
See [`docs/paperclip-setup.md`](docs/paperclip-setup.md) for one-time
install + MCP registration steps.

## How it works

paper-wiki composes a four-stage async pipeline:

```text
Source(s) → Filter(s) → Scorer → Reporter(s)
                ↓
         optional WikiBackend
```

Each stage is a pluggable async `Protocol`. Built-in plugins ship in
`src/paperwiki/plugins/`. A "recipe" YAML file declares which plugins
to use and how to configure them, so you can describe a complete
research workflow without writing code.

The wiki layer (`MarkdownWikiBackend` + four wiki SKILLs) implements
the [Karpathy LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
loop: Ingest / Query / Lint / Compile. Concept articles cite sources
via frontmatter; sources cite concepts via wikilinks; lint surfaces
contradictions and stale entries.

## Bundled recipes

| Recipe                         | What it does                                                  |
|--------------------------------|---------------------------------------------------------------|
| `recipes/daily-arxiv.yaml`     | Daily arXiv pull (cs.AI/LG/CL/CV) + dedup + Obsidian digest. |
| `recipes/weekly-deep-dive.yaml`| Weekly cadence with broader window for deeper review.        |
| `recipes/sources-only.yaml`    | Source stage only — useful for plugin development / debug.   |
| `recipes/biomedical-weekly.yaml`| paperclip CLI + dedup + wiki backend for biomedical preprints.|

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `0 recommendations` on a fresh vault | Today is Sat/Sun UTC and arXiv has no fresh submissions | Bump `lookback_days` to 3+ in the arxiv source config |
| `pipeline.source.failed: arxiv` HTTP 503 | We've been hammering arXiv; their per-IP throttle hit | Wait an hour; arXiv recovers per-IP, not per-key |
| `s2.parse.skip` warnings, 0 papers | Missing API key, or pre-v0.3.1 plugin without `authors.name` field | Set `PAPERWIKI_S2_API_KEY`; upgrade to v0.3.1+ |
| `dedup.vault.missing` warnings | Recipe references vault subdirs that don't exist yet | Harmless; goes away on second run after vault is populated |
| S2 query with `OR` returns 0 | S2 doesn't support boolean operators in `query` | Use a single keyword/phrase, or stack multiple `semantic_scholar` source entries with different queries |
| Recency filter drops everything | `recency.max_days` < `source.lookback_days` | Make `recency.max_days >= max(lookback_days)` across all sources |

## Architecture and contributing

- [SPEC.md](SPEC.md) — operating contract (domain models, protocols, error codes)
- [tasks/plan.md](tasks/plan.md) — Phase 6/7/8 implementation plans
- [CHANGELOG.md](CHANGELOG.md) — release history (Keep a Changelog format)
- [docs/wiki.md](docs/wiki.md) — wiki ingest/query/lint/compile reference
- [docs/paperclip-setup.md](docs/paperclip-setup.md) — paperclip MCP setup
- The Python implementation lives under `src/paperwiki/`. End users do
  not import this directly — SKILLs invoke it through `python -m
  paperwiki.runners.<name>`.

Tests: `pytest -q` (393 currently). Type-check: `mypy --strict src`.
Lint: `ruff check src tests` + `ruff format --check src tests`.
Plugin manifest: `claude plugin validate .`.

## License

[GPL-3.0](LICENSE)
