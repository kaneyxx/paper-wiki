# Changelog

All notable changes to **paper-wiki** are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

The plugin protocol stays `@experimental` until v1.0; minor versions
before then may break it.

## [Unreleased]

## [0.3.0] — 2026-04-25

### Phase 7 — Paperclip integration (optional)

#### Added
- **`paperwiki.runners.diagnostics`** gains an `mcp_servers: list[str]`
  field. The runner shells out to `claude mcp list` (resolved via
  `shutil.which`) and parses the registered server names. Failures
  (missing CLI, non-zero exit, race conditions) fold into `issues`
  rather than crashing.
- **`PaperclipSource`** plugin (`paperwiki.plugins.sources.paperclip`)
  wraps the third-party paperclip CLI as a paper-wiki `Source`. Maps
  hits' canonical ids to `arxiv:<id>` when the paper exposes one
  (so dedup converges with `ArxivSource`), `paperclip:bio_<id>` for
  bioRxiv/medRxiv, and `paperclip:pmc_<id>` for PubMed Central. Tests
  mock at `asyncio.create_subprocess_exec` and never shell out for
  real.
- Recipes can now name `paperclip` like any other source plugin.
- New bundled recipe **`recipes/biomedical-weekly.yaml`** demonstrates
  paperclip + dedup + `wiki_backend: true` for a weekly biomedical
  preprint pull.
- New SKILL **`paperwiki:bio-search`** (six-section anatomy) +
  `.claude/commands/bio-search.md`. Walks Claude through paperclip
  MCP-driven biomedical search with optional handoff to
  `/paperwiki:wiki-ingest`. Fails gracefully when the MCP server is
  not registered.
- New documentation **`docs/paperclip-setup.md`** covers CLI install,
  authentication, MCP registration, removal, and troubleshooting.
- README Quick Start gains an "Optional: biomedical literature"
  subsection.

#### Changed
- `setup` SKILL surfaces the diagnostics `mcp_servers` field. When
  `paperclip` is missing it offers the registration command verbatim
  but **never auto-runs** `claude mcp add` — auth is sensitive and
  paperclip may be on a metered tier. Two new Red Flags pin this.

## [0.2.0] — 2026-04-25

### Phase 6.3 — Wiki / dedup integration

#### Added
- `MarkdownVaultKeyLoader` now recognizes both the modern
  `canonical_id` frontmatter field and the list-typed `sources:` field
  used by concept articles. Concepts contribute their listed source
  ids to the dedup union automatically, so a paper that has been
  folded into a concept article never re-surfaces in the digest.
- `wiki_lint` gains a sixth code, **`DANGLING_SOURCE`** (severity
  `info`), raised when a `Wiki/sources/` file is not referenced by
  any concept's `sources` list. The lint message points the user at
  `/paperwiki:wiki-ingest` to fold the source in.
- `ObsidianReporter` accepts a `wiki_backend: bool` flag (default
  `False`). When `True`, each top-K recommendation is also persisted
  as a per-paper source file under `Wiki/sources/` via
  `MarkdownWikiBackend.upsert_paper`. The daily digest is unchanged.
- `recipes/daily-arxiv.yaml` documents the new opt-in with a
  commented `wiki_backend: true` line so users can discover the
  feature without it triggering on first run.
- New integration test `tests/integration/test_digest_wiki_handoff.py`
  pins down the digest ➜ wiki backend ➜ wiki_lint contract end-to-end.

#### Changed
- `analyze` SKILL writes per-paper notes under `{vault}/Sources/`
  (the `SOURCES_SUBDIR` default) rather than the legacy
  `{paper_subdir}` placeholder. After writing, it now hands off to
  `/paperwiki:wiki-ingest` so the source folds into concept articles
  immediately. Frontmatter requirements bump to `canonical_id`,
  `title`, `tags`, `status`, and `confidence`.

### Phase 6.2 — Wiki backend implementation

#### Added
- `MarkdownWikiBackend` (`paperwiki.plugins.backends.markdown_wiki`)
  persists papers as `Wiki/sources/<id>.md` and synthesized topic
  articles as `Wiki/concepts/<name>.md` with frontmatter that mirrors
  the Karpathy / kytmanov LLM-Wiki reference (`status`, `confidence`,
  `sources`, `related_concepts`, `last_synthesized`).
- Four wiki runners shipped under `paperwiki.runners`:
  - `wiki_query` — keyword search across concepts + sources, ranked
    by TF-IDF on title and tags. Returns ≤ 10 hits as JSON.
  - `wiki_lint` — health check covering `ORPHAN_CONCEPT`, `STALE`,
    `OVERSIZED`, `BROKEN_LINK`, and `STATUS_MISMATCH` (later joined
    by `DANGLING_SOURCE`).
  - `wiki_compile` — deterministic rebuild of `Wiki/index.md`.
  - `wiki_ingest_plan` — given a new source id, returns the affected
    concepts and suggested new concepts a SKILL should synthesize.
- Four matching SKILLs (`wiki-query`, `wiki-lint`, `wiki-compile`,
  `wiki-ingest`) plus slash commands so the runners are first-class
  user surfaces.
- End-to-end integration test `tests/integration/test_wiki_flow.py`
  walks the full backend ➜ runners path.
- New `docs/wiki.md` documenting the four operations, the layout
  contract, and the frontmatter convention.

### Phase 6.1 — Vault layout cleanup

#### Changed (BREAKING)
- `ObsidianReporter` default `daily_subdir` changed from `"10_Daily"`
  to `"Daily"`. The numeric prefix was a Johnny.Decimal / PARA
  convention inherited from `evil-read-arxiv`; paper-wiki should not
  impose a personal-knowledge-management style on users who do not
  follow one. Defaults are now friendly; users who do use PARA can
  override `daily_subdir` per-recipe.
- Bundled recipes (`recipes/daily-arxiv.yaml`,
  `recipes/weekly-deep-dive.yaml`) updated to demonstrate the friendly
  defaults; an inline comment shows how Johnny.Decimal users override.

#### Added
- `paperwiki.config.layout` module with three default subdir constants
  (`DAILY_SUBDIR`, `SOURCES_SUBDIR`, `WIKI_SUBDIR`) used by reporters
  and the upcoming wiki backend.
- `Wiki/.drafts/` added to `.gitignore` for the upcoming wiki feature.

### Migration from earlier installs

If you have an existing setup that relied on the old default
`10_Daily` subdir, either:

- **Keep the numeric prefix**: pin `daily_subdir: 10_Daily` in your
  recipe's `obsidian` reporter config, or
- **Migrate to the friendly default**: `mv ~/Vault/10_Daily
  ~/Vault/Daily` and let the new default pick up.

The dedup filter scans recursively and reads frontmatter, so renaming
the directory does not break dedup.

## [0.1.0] — 2026-04-25

### Added
- Initial release. Phases 0 through 5 of the foundation plan:
  plugin scaffolding, core domain models and protocols, async pipeline
  orchestrator, source plugins (arXiv, Semantic Scholar), filter
  plugins (recency, relevance, dedup), composite scorer, reporters
  (Markdown, Obsidian-flavored), recipe system, runners (digest,
  diagnostics), and three SKILLs (setup, digest, analyze).
- 281 tests, 93% coverage.
