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
- **Claude Code CLI ≥ 2.1.119** — paper-wiki *is* a Claude Code plugin;
  SKILLs run inside Claude Code, not standalone. v0.3.4's setup wizard
  depends on `AskUserQuestion`'s `header` field which versions older
  than 2.1.119 do not render correctly (earlier versions auto-truncate
  the label).
- **Optional**: a [Semantic Scholar API key](https://www.semanticscholar.org/product/api#api-key-form)
  (free) — bumps the rate limit from ~1 req/s to 100 req/s and is
  strongly recommended for any non-trivial use.
- **Optional**: [paperclip](https://gxl.ai/blog/paperclip) for
  biomedical literature; see [Optional: biomedical literature](#optional-biomedical-literature)
  below for details on the CLI vs MCP paths.

## Install

In Claude Code:

```text
/plugin marketplace add kaneyxx/paper-wiki
/plugin install paper-wiki@paper-wiki
```

The plugin self-installs its Python environment on first session — no
manual setup required.

## Upgrading

**Recommended path (v0.3.20+)**: use the `paperwiki` CLI that ships with
the plugin. It handles version comparison, stale-cache backup, and JSON
pruning automatically:

```bash
paperwiki update
```

The `paperwiki` command is automatically installed at `~/.local/bin/paperwiki`
on first session start. If `~/.local/bin` is not on your PATH, you'll see a
one-time warning with the exact line to add to your shell rc; the shim itself
remains usable via full path.

If needed, the full path to the binary is:

```bash
# From the plugin's virtual environment (fallback):
~/.claude/plugins/cache/paper-wiki/paper-wiki/<current-version>/.venv/bin/paperwiki update
```

The command:
1. Pulls the latest marketplace clone.
2. Compares versions.
3. On version drift: renames the stale cache to `<ver>.bak.<timestamp>`,
   removes `paper-wiki@paper-wiki` from `installed_plugins.json` and both
   `settings.json` / `settings.local.json` `enabledPlugins` arrays.
4. Prints a `Next:` section guiding you through the reinstall.

Then follow the printed instructions:

```text
/exit          # exit the current session
claude         # open a fresh session
/plugin install paper-wiki@paper-wiki
```

> **Required after a version bump**: `/exit` then a brand-new `claude`
> process. **`/reload-plugins` is NOT enough.** SessionStart hooks
> (which bootstrap the plugin venv) only fire on fresh sessions; without
> them the new version's `paperwiki` binary may not be set up in time
> and SKILLs that shell out will fail with
> `.venv/bin/paperwiki: No such file or directory`. The v0.3.29+ shim
> auto-bootstraps from a fresh terminal, but inside-Claude SKILL
> invocations still rely on SessionStart firing.

### Manual upgrade (fallback)

If the `paperwiki` CLI is not available (e.g. on a fresh machine where
the plugin has not yet been installed), use the manual flow:

```text
/plugin uninstall paper-wiki@paper-wiki
/plugin install paper-wiki@paper-wiki
```

Then fully exit and start a fresh session. If `/plugin install` says
"already installed" but SKILLs are missing, remove
`paper-wiki@paper-wiki` from `~/.claude/plugins/installed_plugins.json`
manually before reinstalling.

### Where paper-wiki keeps your stuff (v0.3.29+)

Run `paperwiki where` to see every paper-wiki path on disk with sizes:

```bash
paperwiki where           # human-readable indented tree
paperwiki where --json    # machine-parseable
```

Default layout:

```
${PAPERWIKI_HOME:-~/.config/paper-wiki}/   # YOU control this root
├── recipes/        # YAML recipes from /paper-wiki:setup
├── secrets.env     # API keys (chmod 600)
└── venv/           # shared venv across plugin versions

~/.claude/plugins/cache/paper-wiki/paper-wiki/   # Claude Code controls this
├── <current>/      # active install
├── <ver>.bak.<ts>  # rollback target (PAPERWIKI_BAK_KEEP=3 by default)
├── <ver>.bak.<ts>
...

~/.local/bin/paperwiki   # version-agnostic CLI shim
```

Override the user-controlled root with `PAPERWIKI_HOME`:

```bash
export PAPERWIKI_HOME=~/dotfiles/paper-wiki
```

Resolution priority (precedence chain):

```
1. $PAPERWIKI_VENV_DIR           # finer-grained: only the venv
2. $PAPERWIKI_HOME               # canonical root (recipes + secrets + venv)
3. $PAPERWIKI_CONFIG_DIR         # legacy alias (v0.3.4–v0.3.28); still works
4. ~/.config/paper-wiki          # default
```

### Uninstall (v0.3.35+)

`paperwiki uninstall` is flag-driven. The default still only touches
the plugin cache + JSON entries; opt in to deeper cleanup with one or
more of `--everything`, `--purge-vault PATH`, `--nuke-vault`, `--yes`.

| Flag | What it adds |
|---|---|
| (none) | `~/.claude/plugins/cache/paper-wiki/`, `installed_plugins.json` paper-wiki entry, `settings.json` `enabledPlugins["paper-wiki@paper-wiki"]`. |
| `--everything` | Adds: `~/.config/paper-wiki/` (recipes + secrets + venv), `~/.local/bin/paperwiki` shim + `.paperwiki-path-warned` marker, marketplace clone, `settings.json` `extraKnownMarketplaces.paper-wiki`. |
| `--purge-vault PATH` | Adds: paperwiki-created files under PATH (`Daily/`, `Wiki/`, `.digest-archive/`, `.vault.lock`, `Welcome.md`). Preserves `.obsidian/`, `.DS_Store`, and anything else. PATH must exist. |
| `--nuke-vault` | (only valid with `--purge-vault`) replaces the surgical removal with `rm -rf PATH`. |
| `--yes` / `-y` | Skip confirmation prompts. |
| `--verbose` / `-v` | Log each target as it is removed. |

```bash
paperwiki where             # safe inventory before any uninstall
paperwiki uninstall         # plugin layer only (asks for confirmation)
paperwiki uninstall --everything --yes        # plugin + user config + shim + marketplace
```

#### Fresh-user reset

One command for a complete wipe before re-testing as a fresh user:

```bash
paperwiki uninstall --everything --purge-vault ~/Documents/Obsidian-Vault --nuke-vault --yes
```

This removes the plugin layer, the user-controlled config root, the
PATH shim + marker, the marketplace clone, the `extraKnownMarketplaces`
entry, AND the entire vault directory. Re-install with
`/plugin install paper-wiki@paper-wiki` from a fresh `claude` session.

Bak retention is configurable via `PAPERWIKI_BAK_KEEP` (default `3`)
and can be inspected/cleaned anytime via `paperwiki gc-bak --dry-run`.

> **Note for dotfiles / Time Machine users**: `${PAPERWIKI_HOME}/venv/`
> contains a Python virtualenv (~250 MB). Add it to your dotfiles
> manager's ignore list (e.g. chezmoi `ignore`, yadm `gitignore`),
> and remember that macOS Time Machine will back it up unless you
> exclude it manually (`tmutil addexclusion ~/.config/paper-wiki/venv`).

## First-run walkthrough

### 1. Install

```text
/plugin marketplace add kaneyxx/paper-wiki
/plugin install paper-wiki@paper-wiki
```

### 2. Run the setup wizard

```text
/paper-wiki:setup
```

The wizard asks 5–8 questions (vault path, topics, Semantic Scholar API
key, auto-ingest depth, paperclip availability) and writes:

- `~/.config/paper-wiki/recipes/daily.yaml` — your personal recipe
- `~/.config/paper-wiki/secrets.env` — API keys (chmod 600)

Re-running the wizard against an existing config offers
**Keep / Reconfigure all / Edit one piece** — non-destructive by
default.

### 3. Generate your first digest

```text
/paper-wiki:digest daily
```

Pulls papers from arXiv + Semantic Scholar, scores them against your
topics, and writes `~/Documents/<your-vault>/Daily/<YYYY-MM-DD>.md`
with Obsidian callouts, inline teaser figures, and `### Detailed report`
sub-headings per paper.

If your recipe has `auto_ingest_top: 3`, the top 3 papers are
automatically folded into the wiki concept articles via
`/paper-wiki:wiki-ingest` at the end of the digest run.

### 4. Browse and query

```text
/paper-wiki:wiki-query "vision-language pathology"
```

Keyword + tag search across `Wiki/concepts/` and `Wiki/sources/`, with
Claude synthesizing a cited answer.

### Manual setup (fallback)

If you prefer to bypass the wizard and configure by hand, the recipes
under `recipes/*.yaml` are templates. Copy one as a starting point:

```bash
mkdir -p ~/.config/paper-wiki/recipes
cp recipes/daily-arxiv.yaml ~/.config/paper-wiki/recipes/daily.yaml
```

Then edit `~/.config/paper-wiki/recipes/daily.yaml`:

- Change every `vault_path` and `vault_paths` reference to your vault
- Change the `topics` to keywords you actually read about
- Add `api_key_env: PAPERWIKI_S2_API_KEY` to the `semantic_scholar`
  source if you have a key (recommended)

Store the API key securely:

```bash
mkdir -p ~/.config/paper-wiki
cat > ~/.config/paper-wiki/secrets.env <<'EOF'
export PAPERWIKI_S2_API_KEY="<your-S2-key>"
EOF
chmod 600 ~/.config/paper-wiki/secrets.env
```

Bundled and personal recipes never inline the key. They reference it
via `api_key_env: PAPERWIKI_S2_API_KEY`; the recipe loader resolves
the env var at pipeline-build time, so the secret stays out of any
YAML file.

The vault subdirectory layout paper-wiki creates by default:

```text
~/Documents/Paper-Wiki/
├── Daily/      # daily digest output (one .md per day)
├── Sources/    # per-paper notes (created by /paper-wiki:analyze)
└── Wiki/       # synthesized concept articles + per-paper source stubs
    ├── sources/
    ├── concepts/
    └── index.md
```

Every subdir is configurable per recipe — for example
`daily_subdir: 10_Daily`. See
[`docs/example-recipes/personal-johnny-decimal.yaml`](docs/example-recipes/personal-johnny-decimal.yaml).

## SKILLs

| SKILL                           | Purpose                                                                                |
|---------------------------------|----------------------------------------------------------------------------------------|
| `/paper-wiki:setup`             | Interactive wizard (5–8 AskUserQuestion prompts) that writes your personal recipe and secrets file. Re-run to keep / reconfigure / edit one piece. |
| `/paper-wiki:digest`            | Run a recipe end-to-end → arXiv / S2 / paperclip → filter → score → write Obsidian callouts, inline figures, and `### Detailed report` sub-headings. When `auto_ingest_top: N` is set, chains `/paper-wiki:wiki-ingest` for the top N papers automatically. |
| `/paper-wiki:analyze`           | Deep-analyze one paper into a six-section note in `Sources/`, then chain wiki-ingest.   |
| `/paper-wiki:extract-images`    | Pull real figures from an arXiv source tarball into `Wiki/sources/<id>/images/`.        |
| `/paper-wiki:wiki-ingest`       | Fold a source into the user's concept articles (Karpathy LLM-Wiki ingest loop).         |
| `/paper-wiki:wiki-query`        | Keyword search across `Wiki/concepts/` and `Wiki/sources/` with Claude-synthesized answer. |
| `/paper-wiki:wiki-lint`         | Health-check: orphan concepts, stale entries, broken wikilinks, dangling sources.       |
| `/paper-wiki:wiki-compile`      | Deterministic rebuild of `Wiki/index.md` from frontmatter.                              |
| `/paper-wiki:migrate-sources`   | Upgrade legacy `Wiki/sources/<id>.md` files to the current section-organized format.    |
| `/paper-wiki:migrate-recipe`    | Surgically update a personal recipe to the latest template keywords (e.g. remove stale `foundation model` from `biomedical-pathology`) without re-running the full setup wizard.    |
| `/paper-wiki:bio-search`        | (Optional) Search bioRxiv / medRxiv / PMC via paperclip MCP, save hits as wiki sources. |
| `/paper-wiki:status`            | Print paper-wiki install state (cache version / marketplace version / enabledPlugins state). Thin wrapper around `paperwiki status`. |
| `/paper-wiki:update`            | Refresh the marketplace clone, clean the stale cache and JSON entries, and surface the next-steps for `/plugin install`. Thin wrapper around `paperwiki update`. |
| `/paper-wiki:uninstall`         | Print the safe uninstall path. Claude can't safely tear itself out from inside its own session, so the SKILL points the user at `paperwiki uninstall` from a fresh terminal. |

### CLI vs SKILL surface symmetry (v0.3.27+)

Every paper-wiki operation is now invocable from BOTH inside Claude Code
(slash command) AND a fresh terminal (`paperwiki <subcommand>` console
script). Pick whichever fits the moment — Claude integration when you
want LLM synthesis along the way, terminal when you want determinism
and cron-friendliness.

| Operation        | Slash command (in Claude)   | CLI (terminal)                          | Notes                                                                                               |
|------------------|-----------------------------|-----------------------------------------|-----------------------------------------------------------------------------------------------------|
| Setup            | `/paper-wiki:setup`         | _(no CLI; LLM-driven wizard)_           | Interactive AskUserQuestion flow; cannot mirror to CLI sensibly.                                    |
| Digest           | `/paper-wiki:digest`        | `paperwiki digest <recipe>`             | Same pipeline; CLI suits cron / scheduled invocations.                                              |
| Wiki-ingest      | `/paper-wiki:wiki-ingest`   | `paperwiki wiki-ingest <vault> <id>`    | `--auto-bootstrap` is the typical flag.                                                             |
| Wiki-lint        | `/paper-wiki:wiki-lint`     | `paperwiki wiki-lint <vault>`           | Both emit JSON.                                                                                     |
| Wiki-compile     | `/paper-wiki:wiki-compile`  | `paperwiki wiki-compile <vault>`        | Deterministic rebuild of `Wiki/index.md`.                                                           |
| Wiki-query       | `/paper-wiki:wiki-query`    | `paperwiki wiki-query <vault> <q>`      | CLI is deterministic substring search; SKILL adds LLM synthesis on top.                             |
| Extract images   | `/paper-wiki:extract-images`| `paperwiki extract-images <vault> <id>` | Same 3-priority extraction.                                                                         |
| Migrate sources  | `/paper-wiki:migrate-sources`| `paperwiki migrate-sources <vault>`    | One-shot legacy-format upgrade.                                                                     |
| Migrate recipe   | `/paper-wiki:migrate-recipe`| `paperwiki migrate-recipe <recipe>`     | Surgical keyword diff; both surfaces back up the recipe before write.                               |
| Status           | `/paper-wiki:status`        | `paperwiki status`                      | Three-line install report.                                                                          |
| Update plugin    | `/paper-wiki:update`        | `paperwiki update`                      | Refresh marketplace + clean cache; user runs `claude` + `/plugin install` afterwards.               |
| Uninstall plugin | `/paper-wiki:uninstall`     | `paperwiki uninstall`                   | SKILL prints redirect only (can't safely uninstall from inside Claude); run the CLI in fresh shell. |
| Analyze          | `/paper-wiki:analyze`       | _(no CLI; LLM-driven 6-section synth)_  | Inherently SKILL-shaped; no deterministic equivalent.                                               |
| Bio-search       | `/paper-wiki:bio-search`    | _(no CLI; uses paperclip MCP)_          | Auth + LLM-driven; SKILL only.                                                                      |

### Optional: biomedical literature

If you work in life sciences, paper-wiki integrates with
[paperclip](https://gxl.ai/blog/paperclip) (8M+ papers across bioRxiv,
medRxiv, PubMed Central). There are two separate paths:

**paperclip CLI** — a local executable used by `PaperclipSource` plugin
and the `biomedical-weekly.yaml` bundled recipe. No auth flow inside
Claude Code. Install it per the [paperclip docs](https://gxl.ai/blog/paperclip).

**paperclip MCP** — an HTTP MCP server used by `/paper-wiki:bio-search`.
Register it once with user scope:

```bash
claude mcp add --transport http --scope user paperclip https://paperclip.gxl.ai/mcp
```

Then inside a Claude Code session: `/mcp` → highlight `paperclip` →
**Authenticate** → OAuth flow opens a browser to complete login.

paperclip is **opt-in**: paper-wiki's other SKILLs work without it.
See [`docs/paperclip-setup.md`](docs/paperclip-setup.md) for full
install, authentication, and troubleshooting steps.

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

| Recipe                           | What it does                                                  |
|----------------------------------|---------------------------------------------------------------|
| `recipes/daily-arxiv.yaml`       | Daily arXiv pull (cs.AI/LG/CL/CV) + dedup + Obsidian digest. `auto_ingest_top` is configurable in your personal copy. |
| `recipes/weekly-deep-dive.yaml`  | Weekly cadence with broader window for deeper review.        |
| `recipes/sources-only.yaml`      | Source stage only — useful for plugin development / debug.   |
| `recipes/biomedical-weekly.yaml` | paperclip CLI (not MCP) + dedup + wiki backend for biomedical preprints. |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `0 recommendations` on a fresh vault | Today is Sat/Sun UTC and arXiv has no fresh submissions | Bump `lookback_days` to 3+ in the arxiv source config |
| `pipeline.source.failed: arxiv` HTTP 503 | We've been hammering arXiv; their per-IP throttle hit | Wait an hour; arXiv recovers per-IP, not per-key |
| `s2.parse.skip` warnings, 0 papers | Missing API key, or pre-v0.3.1 plugin without `authors.name` field | Set `PAPERWIKI_S2_API_KEY`; upgrade to v0.3.1+ |
| `dedup.vault.missing` warnings | Recipe references vault subdirs that don't exist yet | Harmless; goes away on second run after vault is populated |
| S2 query with `OR` returns 0 | S2 doesn't support boolean operators in `query` | Use a single keyword/phrase, or stack multiple `semantic_scholar` source entries with different queries |
| Recency filter drops everything | `recency.max_days` < `source.lookback_days` | Make `recency.max_days >= max(lookback_days)` across all sources |
| `/plugin install` says "already installed" but `/paper-wiki:setup` says "Unknown command" | Stale plugin state — cache and metadata are out of sync | Run `/plugin uninstall paper-wiki@paper-wiki`, then `/plugin install paper-wiki@paper-wiki`, then fully exit and start a fresh `claude` session (not `claude -c`). As a last resort, manually remove `paper-wiki@paper-wiki` from `~/.claude/plugins/installed_plugins.json` before reinstalling. |
| MCP servers added via `claude mcp add` don't show in `/mcp` UI | Active session loaded MCP config at startup; doesn't hot-reload | Fully `/exit` and start a new `claude` session |
| Setup wizard shows weird "Topics (1)/(2)" tabs or "Custom kw" labels | Pre-v0.3.4 setup SKILL violated AskUserQuestion 4-option/header schema | Upgrade plugin: `/plugin update paper-wiki` (then nuke cache + reinstall if update doesn't take) |
| `paperwiki: line N: .venv/bin/paperwiki: No such file or directory` | New plugin version was installed via `/plugin install` + `/reload-plugins` (which doesn't fire SessionStart hooks), so the venv hasn't bootstrapped yet | v0.3.29+: simply rerun `paperwiki status` from a fresh terminal — the shim auto-bootstraps. Older versions: run `bash ~/.claude/plugins/cache/paper-wiki/paper-wiki/<ver>/hooks/ensure-env.sh` manually, or just `/exit` and start a new `claude` session. |
| `.bak/` directories pile up under the plugin cache | `paperwiki update` retains historical caches as rollback targets | v0.3.29+: `paperwiki gc-bak --dry-run` shows what would be cleaned; default retention is 3 (configurable via `PAPERWIKI_BAK_KEEP`). |
| Want a one-shot list of all paper-wiki paths on disk | — | `paperwiki where` (v0.3.29+) prints config / venv / cache / shim with sizes; `--json` for scripting. |

## Architecture and contributing

- [SPEC.md](SPEC.md) — operating contract (domain models, protocols, error codes)
- [tasks/plan.md](tasks/plan.md) — Phase 6/7/8 implementation plans
- [CHANGELOG.md](CHANGELOG.md) — release history (Keep a Changelog format)
- [docs/wiki.md](docs/wiki.md) — wiki ingest/query/lint/compile reference
- [docs/paperclip-setup.md](docs/paperclip-setup.md) — paperclip MCP setup
- The Python implementation lives under `src/paperwiki/`. End users do
  not import this directly — SKILLs invoke it through `python -m
  paperwiki.runners.<name>`.

Tests: `pytest -q` (450+ tests). Type-check: `mypy --strict src`.
Lint: `ruff check src tests` + `ruff format --check src tests`.
Plugin manifest: `claude plugin validate .`.

## License

[GPL-3.0](LICENSE)
