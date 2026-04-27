# Changelog

All notable changes to **paper-wiki** are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

The plugin protocol stays `@experimental` until v1.0; minor versions
before then may break it.

## [Unreleased]

## [0.3.10] - 2026-04-27

### Fixed

- **digest SKILL no longer asks "shall I chain wiki-ingest?"** when
  `auto_ingest_top: N` is set. The recipe field IS the user's
  pre-approval — re-prompting every digest defeats the configuration.
  v0.3.10 makes the contract imperative ("**immediately and without
  asking the user**") and adds a Common Rationalizations row killing
  the "I'll ask first to be safe" instinct.

### Tests

- New `test_digest_skill_forbids_asking_before_auto_chain` pins the
  contract.

## [0.3.9] - 2026-04-27

### Fixed

- **`wiki-ingest` runner now actually accepts `--auto-bootstrap`** as advertised by the
  SKILL since v0.3.7. Previously the runner ignored the flag entirely; the SKILL fell back
  to writing inline Python (`asyncio.run(MarkdownWikiBackend.upsert_concept(...))` blocks)
  to manually create stubs, which was fragile and bypassed runner architecture per SPEC §6.
  Auto-chained digest invocations now go through the proper runner path.

### Added

- **`paperwiki.runners._stub_constants` module** exposes `AUTO_CREATED_SENTINEL_BODY` and
  `AUTO_CREATED_FRONTMATTER_FIELDS` as a single source of truth — wiki-ingest writes them,
  future wiki-lint changes (Task 9.12) will detect them, no string-literal drift possible.

### Changed

- **`skills/wiki-ingest/SKILL.md`** Process simplified: the runner now handles
  `--auto-bootstrap` directly. No inline-Python fallback fragments required.
- **`skills/digest/SKILL.md`** Step 8 (auto-chain wiki-ingest): the chained command
  invokes the runner directly with `--auto-bootstrap`; no `<<PY ... PY>>` blocks.

### Tests

- `test_wiki_ingest_plan_auto_bootstrap_creates_stubs_for_missing_concepts` — with empty
  `Wiki/concepts/`, invoking the runner with `auto_bootstrap=True` for a source that
  suggests N concepts creates N stub files, each with `auto_created: true` frontmatter and
  the sentinel body.
- `test_wiki_ingest_plan_auto_bootstrap_then_updates_concepts` — after stubs are created,
  the update loop folds the source's `canonical_id` into each stub's `sources:` list;
  output plan has both `created_stubs` and `affected_concepts` populated.
- `test_wiki_ingest_plan_auto_bootstrap_skips_existing_concepts` — pre-existing concept
  (without `auto_created`) is NOT given `auto_created: true`; user content preserved.
- `test_wiki_ingest_plan_without_auto_bootstrap_preserves_existing_safeguard` — without
  the flag, fresh vault returns `affected_concepts: []`, `suggested_concepts: [...]`, no
  files created.
- `test_stub_constants_module_exposes_sentinel_and_frontmatter` — asserts the constants
  module exists and exposes both `AUTO_CREATED_SENTINEL_BODY` and
  `AUTO_CREATED_FRONTMATTER_FIELDS`.
- `test_wiki_ingest_runner_accepts_auto_bootstrap_flag` — `python -m
  paperwiki.runners.wiki_ingest_plan --help` shows `--auto-bootstrap` in help text.

## [0.3.8] - 2026-04-27

### Fixed

- **`.claude-plugin/plugin.json` was missing the `"skills": "./skills/"` declaration**
  that Claude Code uses to locate SKILL files. Without it, `/plugin install` could
  leave the metadata in an inconsistent state (cache populated but slash commands
  unresolvable), leading to the "already installed globally" + "Unknown command" failure
  mode reported repeatedly during 0.3.5–0.3.7 upgrades. With the declaration in place,
  the standard `/plugin uninstall paper-wiki@paper-wiki` +
  `/plugin install paper-wiki@paper-wiki` flow works without any manual cache cleanup.

### Documentation

- **README's upgrade section rewritten** to describe the standard flow:
  `/plugin uninstall paper-wiki@paper-wiki` + `/plugin install paper-wiki@paper-wiki` +
  fully exit + start a fresh `claude` session (not `claude -c`). Removed the manual
  `rm -rf` cache instructions that were workarounds for the bug above.
- Troubleshooting row for "already installed but Unknown command" updated: the cure is
  now the standard uninstall + reinstall flow; manual JSON editing is mentioned only as
  a last-resort fallback.

### Tests

- `test_plugin_manifest_declares_skills_directory` — pins the `"skills"` declaration
  so future refactors cannot accidentally drop it.
- `test_readme_documents_standard_upgrade_flow` — asserts README contains the literal
  `/plugin uninstall` and `/plugin install` commands and the `claude -c` warning.
- `test_readme_does_not_recommend_manual_cache_nuke` — asserts README does not tell
  users to `rm -rf` the plugin cache as part of normal upgrades.

### Note

The previous v0.3.5–0.3.7 workarounds (`rm -rf ~/.claude/plugins/cache/paper-wiki/`
and manual `installed_plugins.json` edits) were diagnostic workarounds for the missing
`"skills"` declaration — not best practice. Existing users upgrading to 0.3.8 should
NOT need to nuke; the standard uninstall + reinstall flow above is sufficient.

### Deferred to v0.3.9

- Task 9.4 (per-paper Detailed report synthesis) and Task 9.5 (auto image extraction)
  were originally planned for v0.3.8 but are pushed to v0.3.9 so this release stays
  small and focused on the upgrade-UX fix.

## [0.3.7] - 2026-04-27

### Added

- **digest SKILL now synthesizes the "Today's Overview" callout** instead of
  leaving an empty slot. After the deterministic runner writes the digest
  skeleton, the SKILL re-reads the file and replaces
  `<!-- paper-wiki:overview-slot -->` with 60–200 words of cross-paper prose
  covering top trends, quality / score distribution, and suggested reading
  order — every claim cited with `#N` paper-index markers. New SKILL Common
  Rationalizations + Red Flags pin the contract: don't claim a trend from one
  paper; don't skip `#N` cites; don't invent topics not in the digest.
- **`--auto-bootstrap` mode for `wiki-ingest` SKILL.** When invoked with this
  flag (only by digest auto-chain — manual `/paper-wiki:wiki-ingest <id>` keeps
  the existing confirmation prompt), missing concept articles are auto-stubbed
  with `auto_created: true` frontmatter + sentinel body before the normal update
  loop runs. Net effect: fresh-vault digests no longer dead-end on paper #1 with
  `affected_concepts: []` — auto-chain creates stubs for top-N papers and folds
  source citations in.
- **`wiki-lint` SKILL surfaces concept articles with `auto_created: true`** in a
  dedicated "Needs review (auto-created stubs)" section, separate from
  broken-link / orphan reports. Users can prune en masse via the sentinel body
  string or remove with `rm <vault>/Wiki/concepts/<name>.md`.
- **Tests**: `test_wiki_ingest_skill_describes_auto_bootstrap_mode`,
  `test_digest_skill_passes_auto_bootstrap_to_wiki_ingest`,
  `test_wiki_lint_skill_surfaces_auto_created_stubs`,
  `test_digest_skill_describes_overview_synthesis` — 4 new smoke tests pin the
  contracts.

## [0.3.6] - 2026-04-27

### Fixed

- **99 stale `/paperwiki:` slash-command references** replaced with the correct
  `/paper-wiki:` namespace (with hyphen) across `src/`, `skills/`, `recipes/`,
  `docs/`, `SPEC.md`, and `.claude/commands/` — 26 files in total. Commands like
  `/paperwiki:setup` would have failed at runtime because the Claude Code plugin
  is registered as `paper-wiki`, not `paperwiki`. CHANGELOG entries (this file)
  are intentionally exempt — they describe historical reality.

### Heads-up

- **Source stubs in existing user vaults** (`<vault>/Wiki/sources/<id>.md`)
  generated by paper-wiki ≤ 0.3.5 may contain stale `/paperwiki:` strings baked
  into the body. Run `/paper-wiki:migrate-sources` to upgrade them, or accept
  they will remain until you next analyze each paper.

### Changed

- **Obsidian reporter no longer emits prose placeholder text** in the
  "Today's Overview" callout or each paper's "Detailed report" section. Both are
  now empty machine-targetable HTML-comment markers:
  `<!-- paper-wiki:overview-slot -->` and
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->`. Subsequent digest SKILL
  synthesis passes (planned for v0.3.7 and v0.3.8) will replace these markers
  with synthesized content. Net effect: digests no longer mislead users with
  "Run SKILL after this runner" text — they contain empty slots until SKILL
  synthesis lands.

### Added

- **Regression test `test_no_stale_paperwiki_namespace`** scans `src/`,
  `skills/`, `recipes/`, `docs/`, `SPEC.md`, and `.claude/commands/` for the bad
  `/paperwiki:` pattern; fails with a `file:line` breakdown if any reappear.
  `CHANGELOG.md` is exempt.
- **Three new obsidian reporter contract tests**:
  `test_obsidian_reporter_emits_overview_slot_marker`,
  `test_obsidian_reporter_emits_per_paper_slot_markers`, and
  `test_obsidian_reporter_does_not_emit_legacy_placeholder_prose` — pin the new
  HTML-comment slot skeleton so future changes cannot silently regress to prose
  stubs.

## [0.3.5] - 2026-04-26

### Documentation

- **README rewritten for v0.3.x reality.** Slash-command namespace corrected
  to `/paper-wiki:` throughout (was `/paperwiki:` in 13 places). First-run
  walkthrough now leads with the interactive setup wizard (rather than the
  v0.2-era manual bash flow). Added paperclip MCP user-scope + OAuth setup,
  advanced `PAPERWIKI_CONFIG_DIR` note promoted to Install section, rich digest
  output description (`### Detailed report`, inline figures, Obsidian callouts),
  `auto_ingest_top` chaining note in SKILLs table, and operational
  troubleshooting table for plugin cache mismatches, MCP hot-reload, and
  pre-v0.3.4 wizard schema bugs.

## [0.3.4] - 2026-04-26

### Fixed

- **setup SKILL was violating the AskUserQuestion schema in multiple ways** — too
  many options (auto-split into "Topics (1)/(2)" tabs), missing `header` field
  (caused garbage chip labels like "Custom kw"), manually added redundant "Other"
  / "Cancel" options (Claude Code injects these automatically), and faked
  multi-select via re-prompting instead of using `multiSelect: true`. Each branch
  now provides a fully-specified AskUserQuestion call with `header` (≤ 12 chars),
  per-option `description`, and proper `multiSelect` flag where applicable.

### Changed

- **Topic selection collapsed from 10 fine-grained options to 4 themed buckets**
  (Vision & Multimodal / Biomedical & Pathology / Agents & Reasoning / NLP &
  Language) with `multiSelect: true`. Custom keywords now go through Claude
  Code's auto-provided "Other" input rather than a separate follow-up question.
  Each bucket maps to a curated keyword list and arXiv category set in the
  resulting recipe.

## [0.3.3] - 2026-04-26

### Changed

- **setup SKILL now uses Claude Code's AskUserQuestion tool for every choice** —
  provides a structured selection UI instead of plain prose options. Eight
  explicit call points cover: already-configured detection (4 options), edit-one-piece
  drill-down (5 options), Q1 vault path (auto-detected candidates + Other),
  Q2 topics multi-select (10 options, re-prompted until Done), Q3 S2 API key
  (3 options), Q4 auto-ingest depth (4 options), Q5 paperclip (3 options),
  and final save confirmation (3 options). Aligns with the OMC convention.

## [0.3.2] — 2026-04-26

### Changed (BREAKING for personal config)

- **User config dir renamed** from `~/.config/paperwiki/` to
  `~/.config/paper-wiki/` for XDG and plugin-name consistency (the
  plugin is named `paper-wiki`, so the config dir now matches).
  Migrate with:
  ```bash
  mv ~/.config/paperwiki ~/.config/paper-wiki
  ```
  This is a hard cut — no migration shim. paper-wiki is pre-1.0 with
  effectively one user (the dev).

### Added

- **`PAPERWIKI_CONFIG_DIR` environment variable** — override the config
  directory location; useful for dotfiles workflows or non-standard
  setups (e.g. `~/dotfiles/paper-wiki/`). Resolution priority:
  1. `$PAPERWIKI_CONFIG_DIR` — if set, use as-is
  2. `$XDG_CONFIG_HOME/paper-wiki` — if `XDG_CONFIG_HOME` is set
  3. `~/.config/paper-wiki` — default fallback

## [0.3.1] — 2026-04-25

### Fixed
- **`PaperclipSource` rewritten against the real paperclip 0.2.x CLI.**
  v0.3.0 shipped a plugin built against an assumed `--json` flag and
  imaginary `--source biorxiv,pmc` arguments — the real CLI has no JSON
  output and uses `-T TYPE`, `--journal NAME`, `--since Nd` instead.
  The plugin now follows paperclip's actual two-step flow:
  1. `paperclip search QUERY -n N [--since Nd] [--journal NAME] [-T TYPE]`
     captures a session id of the form `[s_<hex>]` from stdout.
  2. `paperclip results <session_id> --save <tmpfile.csv>` exports the
     structured CSV (`title,authors,id,source,date,url,abstract`).
  Recipe config keys for `PaperclipSource` change from `sources: [...]`
  to `since_days: int`, `journal: str`, `document_type: str`.
- **Empty paperclip abstracts no longer drop the paper.** Real CSV
  exports frequently ship empty `abstract` cells; the plugin now
  substitutes `_(no abstract available from paperclip)_` so dedup,
  scoring, and the wiki backend keep the entry while making the gap
  visible to the user.
- `recipes/biomedical-weekly.yaml` config keys updated to match the
  real CLI surface area (`since_days: 7` replacing the imaginary
  `sources: [biorxiv, medrxiv, pmc]` list).

### Verified end-to-end
- Live smoke test against real paperclip 0.2.0 with the query
  `"CRISPR base editing"`: 3/3 hits parsed cleanly; one had a real
  abstract, two used the placeholder.
- `diagnostics.mcp_servers` correctly enumerates `claude mcp list`
  output on a real machine.

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
