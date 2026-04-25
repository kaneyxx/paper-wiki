# Phase 6 + 7 Task List

Source: [`tasks/plan.md`](plan.md). Each item is one logical commit.
Tick boxes as work lands. Verification gate between every numbered
slice (lint / mypy / pytest / `claude plugin validate`).

---

## Phase 6.1 — Vault-layout cleanup ✅

- [x] **6.1.1** Add `src/paperwiki/config/layout.py` with constants
  `DAILY_SUBDIR = "Daily"`, `SOURCES_SUBDIR = "Sources"`,
  `WIKI_SUBDIR = "Wiki"`. Module docstring documents the rationale.
- [x] **6.1.2** Update `ObsidianReporter.__init__` default
  `daily_subdir="Daily"`; reference `DAILY_SUBDIR`. Update existing
  tests' fixture paths and snapshots.
- [x] **6.1.3** Update `recipes/daily-arxiv.yaml`,
  `recipes/weekly-deep-dive.yaml` so the inline examples use the
  friendly defaults.
- [x] **6.1.4** Add `Wiki/.drafts/` to `.gitignore`.
- [x] **6.1.5** README + `recipes/README.md` + SPEC §3 paragraph on
  "subdirs are configurable; numeric prefixes are opt-in for
  Johnny.Decimal users".
- [x] **6.1.6** CHANGELOG entry: `feat(layout)!: drop numeric subdir
  prefixes; default to friendly names`. Note breaking change.
- [x] **Gate**: `pytest -q`, lint, type-check, plugin validate all green.

## Phase 6.2 — Wiki backend implementation ✅

- [x] **6.2.1** Add `src/paperwiki/plugins/backends/__init__.py` and
  `markdown_wiki.py` containing `MarkdownWikiBackend`. Include
  filename normalization helpers, frontmatter round-trip helpers.
- [x] **6.2.2** Add `tests/unit/plugins/backends/test_markdown_wiki.py`
  covering: `upsert_source` writes file with correct frontmatter,
  `upsert_concept` writes file with `sources:` list, idempotence
  (re-upsert updates `last_synthesized`), filename normalization,
  protocol satisfaction, list_concepts/list_sources discovery.
- [x] **6.2.3** Add `paperwiki.runners.wiki_query` runner + tests.
- [x] **6.2.4** Add `paperwiki.runners.wiki_lint` runner + tests.
- [x] **6.2.5** Add `paperwiki.runners.wiki_compile` runner + tests.
- [x] **6.2.6** Add `paperwiki.runners.wiki_ingest_plan` runner + tests.
- [x] **6.2.7** Add SKILL `skills/wiki-query/SKILL.md` + slash command.
- [x] **6.2.8** Add SKILL `skills/wiki-lint/SKILL.md` + slash command.
- [x] **6.2.9** Add SKILL `skills/wiki-compile/SKILL.md` + slash command.
- [x] **6.2.10** Add SKILL `skills/wiki-ingest/SKILL.md` + slash command.
- [x] **6.2.11** Add `tests/integration/test_wiki_flow.py` exercising
  end-to-end flow.
- [x] **6.2.12** `docs/wiki.md` with Ingest / Query / Lint / Compile
  diagrams + frontmatter reference.
- [x] **Gate**: tests green; `claude plugin validate .` green.

## Phase 6.3 — Wiki / dedup integration ✅

- [x] **6.3.1** Extend `MarkdownVaultKeyLoader` to read `sources:` from
  concept frontmatter; concepts contribute their listed
  `canonical_id`s to dedup keys.
- [x] **6.3.2** Update `analyze` SKILL to write into `Sources/` (use
  `SOURCES_SUBDIR` constant) and call `wiki-ingest` afterwards.
- [x] **6.3.3** Add `wiki_backend: bool` flag (default `false`) to
  the `obsidian` reporter; when true, the digest writes top-K
  papers into `Wiki/sources/` via `MarkdownWikiBackend`.
- [x] **6.3.4** Extend `wiki_lint` to flag "dangling sources"
  (sources not referenced by any concept).
- [x] **6.3.5** Update bundled recipes' comments to demonstrate
  `wiki_backend: true` in `daily-arxiv.yaml`.
- [x] **6.3.6** Add `tests/integration/test_digest_wiki_handoff.py`:
  digest with wiki backend → wiki_lint reports dangling-sources
  count matching top-K size.
- [x] **Gate**: dedup tests still pass; new integration tests green;
  CHANGELOG updated.

---

## Phase 7.1 — Paperclip MCP wiring

- [ ] **7.1.1** Extend `diagnostics` runner to detect registered MCP
  servers via `claude mcp list` (subprocess). New report field:
  `mcp_servers: [str]`.
- [ ] **7.1.2** Update `setup` SKILL to surface paperclip presence /
  absence and offer the registration command (`claude mcp add ...`)
  without auto-running.
- [ ] **7.1.3** Add `docs/paperclip-setup.md` with registration steps
  and a link to upstream docs.
- [ ] **Gate**: setup SKILL still passes parametrized smoke test;
  manual smoke test in a clean Claude Code instance.

## Phase 7.2 — `PaperclipSource` plugin

- [ ] **7.2.1** Add `src/paperwiki/plugins/sources/paperclip.py`
  subprocess wrapper. Maps results to `Paper` with the right
  canonical namespace (`arxiv:` when available, otherwise
  `paperclip:bio_<id>` / `paperclip:pmc_<id>`).
- [ ] **7.2.2** Tests under
  `tests/unit/plugins/sources/test_paperclip.py` use `monkeypatch`
  on `asyncio.create_subprocess_exec`; no real network. Cover:
  binary missing → IntegrationError, non-zero exit → IntegrationError
  with stderr surfaced, JSON parsing errors,
  arxiv-id-when-available canonical mapping.
- [ ] **7.2.3** Wire the plugin into `paperwiki.config.recipe`
  `_build_source` so recipes can name `paperclip` like any other
  source.
- [ ] **7.2.4** New recipe `recipes/biomedical-weekly.yaml` with
  paperclip + dedup + wiki backend.
- [ ] **7.2.5** Bundled-recipes integration test parametrizes over
  `recipes/*.yaml` already; ensure the new recipe loads.
- [ ] **Gate**: tests green; recipe loads; CHANGELOG updated.

## Phase 7.3 — `paperwiki:bio-search` SKILL

- [ ] **7.3.1** Add `skills/bio-search/SKILL.md` (six-section
  anatomy). Mentions paperclip MCP triggers; documents graceful
  fallback when MCP missing.
- [ ] **7.3.2** Add `.claude/commands/bio-search.md`.
- [ ] **7.3.3** Document the SKILL in `README.md` (Quick Start
  section) as an optional advanced feature.
- [ ] **Gate**: parametrized smoke test green; plugin validate green;
  manual smoke test by a paid paperclip user.

---

## Final phase-completion checklist

- [ ] All slice gates green.
- [ ] `pytest --cov=paperwiki --cov-report=term-missing` ≥ 90% overall.
- [ ] `mypy --strict src` clean.
- [ ] `ruff check src tests` clean.
- [ ] `ruff format --check src tests` clean.
- [ ] `claude plugin validate .` passes.
- [ ] CHANGELOG complete; SemVer bump (0.2.0 for Phase 6, 0.3.0 for
  Phase 7) in `pyproject.toml`, `__version__`, `plugin.json`,
  `marketplace.json`.
- [ ] README, SPEC §3, recipes/README updated.
- [ ] Tag `v0.2.0` after Phase 6, `v0.3.0` after Phase 7.
