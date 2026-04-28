# Changelog

All notable changes to **paper-wiki** are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

The plugin protocol stays `@experimental` until v1.0; minor versions
before then may break it.

## [Unreleased]

## [0.3.25] - 2026-04-28

### Fixed

- **`paperwiki update` had THREE silent no-op bugs** — `_cache_version()`,
  `_drop_from_installed_plugins()`, and `_drop_from_enabled_plugins()`
  in `src/paperwiki/cli.py` all assumed the underlying JSON used a
  `list[dict]` shape, but Claude Code 2.1.119 actually uses a
  `dict[plugin_id, ...]` shape:
  - `installed_plugins.json["plugins"]` = `dict[plugin_id, list[install_entry]]`
  - `settings.json["enabledPlugins"]` and
    `settings.local.json["enabledPlugins"]` = `dict[plugin_id, bool]`
  
  So `paperwiki update` always saw "no install detected" (cache version
  returned `None`) and never cleaned `installed_plugins.json` or
  `settings.json` enabledPlugins. The cache rename worked because that
  ran on disk; the JSON cleanup never did. Result: every "successful"
  `paperwiki update` left stale entries that caused `/plugin install`
  to short-circuit "already installed globally" (the very thing
  `paperwiki update` was built to prevent).

  Rewrote all three functions against the real Claude Code 2.1.119
  schema. Test fixtures updated to use real shapes.

### Tests

- Existing `tests/unit/test_cli.py` fixtures rewritten to use real
  dict shapes (was `list[{"name": ..., "id": ...}]` — wrong).
- Regression coverage: `paperwiki update` against a state with
  paper-wiki present in all three shape-correct files actually drops
  all three entries.

## [0.3.24] - 2026-04-28

### Changed

- **`paperwiki update` first-line wording trimmed.** Was
  `paper-wiki upgraded marketplace 0.3.20 → 0.3.23` (with the awkward
  `marketplace (not installed)` placeholder when nothing was cached).
  Now `paper-wiki: 0.3.20 → 0.3.23` (or `paper-wiki: not installed →
  0.3.23` when no current install). Concise X → Y format that matches
  the user's mental model of what an upgrade message should look like.

## [0.3.23] - 2026-04-28

### Fixed

- **Task 9.19 — `s2.parse.skip` log noise silenced.** Four "sparse record"
  branches in `_parse_entry` (missing title/abstract, bad publication date,
  no authors, no usable id) downgraded from `WARNING` to `DEBUG`. The
  `model validation` branch stays at `WARNING` — that indicates a real schema
  mismatch, not a normal sparse S2 record. A single `INFO` summary line
  (`s2.parse.skipped_summary`) is now emitted at the end of each fetch when
  at least one entry was skipped, carrying per-reason counts for power users
  running `--verbose`. Users running daily digests no longer see 3+ spurious
  WARNING lines on every run.

### Added

- **Task 9.20 — digest SKILL surfaces per-paper extract-images summary.**
  Process Step 7a now always emits a per-paper summary block after running
  extract-images for each top-N paper, using four outcome classifications:
  success-with-figures / success-no-figures / skipped-non-arxiv /
  failed-with-error. No image extraction failure is silently absorbed.
  Users see exactly which paper had what result and why.

- **Task 9.21 — `paperwiki migrate-recipe` CLI subcommand and runner.**
  New `paperwiki.runners.migrate_recipe` module and `paperwiki migrate-recipe`
  CLI subcommand surgically update stale personal recipes to the latest
  template keywords without re-running the full setup wizard. The initial
  migration table covers v0.3.17 (drops `foundation model` from
  `biomedical-pathology`). Always idempotent; creates a timestamped backup
  before any write. The `/paper-wiki:migrate-recipe` SKILL and slash command
  wrap the runner with a dry-run-first flow and AskUserQuestion confirmation.
  Setup SKILL Branch 1 ("Keep current config") now runs a stale-keyword
  heuristic and offers a fifth option to migrate immediately.

### Changed

- **Task 9.23 — digest SKILL "Score reasoning" is now interpretive, not
  transcriptive.** Process Step 8 contract updated: Score reasoning must be
  1–2 sentences that explain WHY the paper scores the way it does, acknowledge
  specific limits (e.g. "rigor held back by brand-new arXiv"), and cite
  specific topic matches. Restating the four sub-score numbers verbatim is
  explicitly forbidden. New Common Rationalizations rows and a Red Flag pin
  the contract against drift.

### Tests

- 6 new tests (3 × 9.19 unit, 2 × 9.21 smoke + 4 × 9.21 config/runner, 1 × 9.20 smoke,
  1 × 9.23 smoke).

## [0.3.22] - 2026-04-28

### Changed

- **`paperwiki update` output trimmed** for cleaner UX. Removed the
  trailing two-line technical explanation about `/plugin install`'s
  short-circuit / cleared JSON entries — the next-steps list above
  carries the actionable info; the explanation read like internal
  debug rationale leaking into user-facing output.

## [0.3.21] - 2026-04-28

### Fixed

- **`paperwiki` command not found after install** (Task 9.27). v0.3.20 shipped
  the `paperwiki` console-script entry-point but the venv that contains it
  (`~/.claude/plugins/cache/paper-wiki/paper-wiki/<version>/.venv/bin/paperwiki`)
  is not on the user's PATH, causing `zsh: command not found: paperwiki` when
  trying to use the v0.3.20 upgrade flow.

### Added

- **Auto-installed `~/.local/bin/paperwiki` shim** (Task 9.27).
  `hooks/ensure-env.sh` now installs a version-agnostic shim at
  `~/.local/bin/paperwiki` on every Claude Code SessionStart. The shim
  auto-discovers the latest installed plugin version so future paper-wiki
  upgrades update the venv binary AND the shim invocation seamlessly.
  If `~/.local/bin` is not on the user's PATH, a one-time warning is emitted
  with the exact line to add to their shell rc (non-blocking; marker file
  `~/.local/bin/.paperwiki-path-warned` prevents repeated noise).
  Existing manually-installed shims are preserved — the hook rewrites only
  on stale/missing/foreign content (tag-line grep guard).

### Tests

- `tests/test_smoke.py`: four new tests pin the shim emission block in
  `hooks/ensure-env.sh` — static tag check, idempotency guard pattern,
  PATH-warning marker, and a full integration run in a temp HOME directory.

## [0.3.20] - 2026-04-28

### Added

- **3-priority image extraction** (Task 9.25). `paperwiki._internal.arxiv_source`
  now extracts figures via three cascading strategies:
  (1) figure dirs in the arXiv source tarball (existing, now with min-size filter
  `>200px` on at least one axis preserving v0.3.16 commit `c7d5df4`);
  (2) standalone PDFs at the tarball root converted to PNG via PyMuPDF (new);
  (3) caption-aware crops of the compiled paper PDF when TikZ is detected and
  fewer than 2 figures were found via P1+P2 (new). New runtime dependency:
  `pymupdf>=1.24` (AGPL, compatible with GPL-3.0). The `extract_paper_images`
  runner now writes `Wiki/sources/<id>/images/index.md` with per-figure source
  class (`arxiv-source` / `pdf-figure` / `tikz-cropped`) and emits a `sources`
  sub-dict in its JSON output. Recovers figures from ~80% of arXiv papers (vs
  ~30% on v0.3.19). Reference: github.com/juliye2025/evil-read-arxiv.
- **`paperwiki` console-script** (Task 9.26). New `src/paperwiki/cli.py` exposes
  `paperwiki update`, `paperwiki status`, and `paperwiki uninstall` subcommands.
  `paperwiki update` ends the manual JSON-cleanup ritual every release has
  required: it refreshes the marketplace clone, compares versions, and on drift
  renames the stale cache to `<ver>.bak.<UTC-timestamp>` and prunes
  `installed_plugins.json` plus both `settings.json` / `settings.local.json`
  `enabledPlugins` entries so the subsequent `/plugin install` does a real
  install without the "already installed globally" short-circuit.
  README "Upgrading" section rewritten to lead with `paperwiki update` as the
  primary path; manual flow retained as a fallback footnote.

### Tests

- `tests/unit/_internal/test_arxiv_source.py`: adds Priority-2 root-PDF,
  Priority-3 TikZ-crop, min-size filter, and `_has_tikz` fixtures (12 new).
- `tests/unit/runners/test_extract_paper_images.py`: adds `TestIndexManifest`
  covering `index.md` presence and `sources` JSON field (3 new).
- `tests/unit/test_cli.py` (new): 6 CLI-flow tests via `typer.testing.CliRunner`
  for stale-cache upgrade, up-to-date no-op, missing marketplace clone (exit 2),
  corrupt JSON (exit 1), `status` output, and `uninstall` teardown.
- Smoke tests pin CLI surface (`test_paperwiki_cli_help_lists_subcommands`),
  module imports, `ExtractResult.sources`, and pyproject declarations.

## [0.3.19] - 2026-04-27

### Added

- **Inline figures in Detailed reports** (Task 9.22). Detailed report synthesis
  now embeds the first 1-2 alphabetically-sorted figures from
  `Wiki/sources/<id>/images/` via `![[Wiki/sources/<id>/images/<file>|600]]`
  inside the synthesized block, between Key takeaways and Score reasoning.
  Distinct from the existing card teaser (`|700`) before the Abstract — both
  placements are intentional. Figures are silently skipped for papers with no
  extracted images (e.g. `paperclip:` / `s2:` ids with no arXiv source bundle).
- 5 new smoke tests pin both contracts (inline figures + `auto_ingest_top`
  gating).

### Changed

- **Detailed report synthesis gated by `auto_ingest_top`** (Task 9.24). Only
  the top-N papers (where N = `auto_ingest_top`) get the full Detailed report
  block (Why this matters + Key takeaways + inline figures + Score reasoning).
  Papers ranked below the threshold get a single-line teaser:
  `_Run /paper-wiki:analyze <id> for a deep dive into this paper, or
  /paper-wiki:wiki-ingest <id> to fold it into your concept articles._`
  Setting `auto_ingest_top: 0` makes ALL papers show the teaser (no synthesis).
  Users who want all-paper synthesis can set `auto_ingest_top` to their full
  `top_k` value.

## [0.3.18] - 2026-04-27

### Added

- **Vault advisory lock** (Task 9.17). New `src/paperwiki/_internal/locking.py`
  provides the `acquire_vault_lock(vault_path)` async context manager. All
  mutating runners (`wiki_ingest_plan`, `wiki_compile`, `migrate_sources`) and
  `ObsidianReporter` (when `wiki_backend=True`) acquire the lock before writing
  to `Wiki/`. Concurrent runs now fail immediately with `VaultLockError` (exit
  code 1) instead of producing interleaved partial state.
- **Today's Overview synthesized last** (Task 9.18). The digest SKILL Process
  reorders Steps 7–9: auto-chain (extract-images + wiki-ingest) → per-paper
  Detailed report synthesis → Today's Overview synthesis. The overview is now
  the final LLM pass so it can reference concepts and figures produced by the
  earlier steps. A new Common Rationalizations note ("Do this last") anchors
  the contract.
- Unit tests for `acquire_vault_lock`: lock file creation, sequential
  re-acquisition, parent-dir creation, release-on-exception.
- Smoke tests `test_vault_lock_module_exists` and
  `test_digest_skill_overview_synthesis_comes_after_auto_chain_and_per_paper`
  pin both contracts.

## [0.3.17] - 2026-04-27

### Added

- **Concept-matching threshold** (Task 9.9). `CompositeScorer.score()` now
  serialises per-topic strengths into `ScoreBreakdown.notes["topic_strengths"]`
  as a JSON `dict[str, float]`. `MarkdownWikiBackend.upsert_paper()` accepts a
  new `topic_strength_threshold` parameter (default `0.0`); topics whose
  per-topic strength falls below the threshold are excluded from
  `related_concepts` frontmatter. `ObsidianReporter` exposes
  `wiki_topic_strength_threshold` (default `0.3`) and plumbs it through to
  `upsert_paper`.
- **Auto-stub UX** (Task 9.12). `AUTO_CREATED_SENTINEL_BODY` is now a
  two-paragraph sentinel: the first paragraph marks the stub as intentionally
  empty and names `/paper-wiki:wiki-ingest` as the next step; the second
  paragraph points at `/paper-wiki:wiki-lint` for discovery. The wiki-lint
  SKILL Process Step 2 and the wiki-ingest SKILL Auto-bootstrap section mirror
  this wording so users see a consistent explanation across all surfaces.
- **Setup SKILL keyword hygiene**: the Biomedical & Pathology topic drops
  `foundation model` (cross-domain noise) and collapses duplicate WSI variants
  (`whole-slide image` / `whole slide image`) to a single entry. A new Common
  Rationalizations row warns against generic cross-domain keywords.
- Unit tests for per-topic strength emission (`test_composite_scorer_emits_per_topic_strengths`,
  `test_unmatched_topic_has_zero_strength`) and threshold filtering
  (`test_topic_strength_threshold_filters_matched_topics`,
  `test_zero_threshold_keeps_all_matched_topics`,
  `test_missing_topic_strengths_falls_back_to_all_topics`).
- Smoke tests `test_composite_scorer_emits_per_topic_strengths`,
  `test_wiki_upsert_source_filters_by_topic_strength`,
  `test_wiki_ingest_sentinel_body_explains_next_step`,
  `test_wiki_lint_explains_auto_stub_intent`, and
  `test_setup_skill_biomedical_keywords_exclude_generic_terms`.

## [0.3.16] - 2026-04-27

### Added

- **Per-paper Detailed report synthesis** (Task 9.4). The digest SKILL
  Process Step 9 now fills each `<!-- paper-wiki:per-paper-slot:{id} -->`
  marker with a synthesized Detailed report: "Why this matters" framing,
  2–4 "Key takeaways" bullets from the abstract (never invented), and a
  "Score reasoning" line. Claims must cite `#N` markers; batched prompts
  are the default to amortize cost.
- **Auto-chain image extraction** (Task 9.5). The digest SKILL auto-chain
  now runs `extract_paper_images` **before** `wiki-ingest` for each top-N
  `arxiv:` paper, so figures are on disk when `_try_inline_teaser` is
  invoked on the next digest run. Non-arXiv ids are skipped with a one-line
  reason; failures do not abort the digest.
- Smoke tests `test_digest_skill_describes_per_paper_synthesis` and
  `test_digest_skill_chains_extract_images` pin both contracts.

## [0.3.15] - 2026-04-27

### Added

- **Centralized logger configuration** (`src/paperwiki/_internal/logging.py`).
  New `configure_runner_logging(*, verbose, default_level)` function resets
  loguru's sinks and re-configures a single stderr sink at INFO by default.
  Honors `PAPERWIKI_LOG_LEVEL` env var as the highest-priority override so CI
  and hooks can silence runners with one variable.
- **`--verbose / -v` flag** on every runner (`digest`, `wiki_ingest_plan`,
  `wiki_compile`, `wiki_query`, `wiki_lint`, `extract_paper_images`,
  `migrate_sources`, `diagnostics`). Passing `--verbose` enables DEBUG-level
  logging; default remains INFO (no debug noise on normal runs).
- **Unit tests** `tests/unit/_internal/test_logging.py` pin the three
  configure contracts: INFO default, `--verbose` enables DEBUG, and
  `PAPERWIKI_LOG_LEVEL=WARNING` silences INFO.

### Fixed

- Chatty internal modules (`paperwiki.plugins.filters.dedup`,
  `paperwiki._internal.arxiv_source`) are now disabled at INFO level by
  default; they only surface output when `--verbose` is passed or
  `PAPERWIKI_LOG_LEVEL=DEBUG` is set.

## [0.3.14] - 2026-04-27

### Added

- **`tests/integration/test_full_digest_auto_chain.py` end-to-end smoke test.**
  Single test that drives the full digest → auto-chain pipeline against a
  tmp vault using stubbed sources (Option B: in-process `StubSource`,
  no recipe YAML or network calls). Asserts every contract added in
  v0.3.6–v0.3.13: daily digest file on disk, `<!-- paper-wiki:overview-slot -->`
  marker, per-paper slot markers, Wiki source stubs, `wiki_ingest_plan`
  subprocess exits 0, JSON has `created_stubs` + `folded_citations`, concepts
  already seen fold instead of re-stub, idempotent `sources:` lists (no
  duplicates), no DEBUG/WARNING in subprocess stderr, and full test runtime
  < 15 s. Acts as a CI hard gate so future releases can't silently regress
  the pipeline.

## [0.3.13] - 2026-04-27

### Fixed

- **4-minute hang in digest auto-chain.** Previously, after the runner created
  stubs, the SKILL had to Read each pre-existing concept file and run `Edit` to
  fold the source citation in — when this hit Edit's "File must be read first"
  pre-condition and LLM retry loops, it could hang for minutes. The runner now
  folds citations atomically as part of `--auto-bootstrap`, eliminating the
  SKILL-side Edit dance.

### Added

- **`folded_citations: list[str]` field in `wiki_ingest_plan` JSON output.**
  Lists concept names whose `sources:` list was updated with this source's
  canonical_id (idempotent — no-op if already present).

### Changed

- **wiki-ingest SKILL Step 4 split into 4 (auto-bootstrap path) and 4b
  (manual path).** Auto-bootstrap path: just report runner's
  `folded_citations`, no LLM work. Manual path: existing
  prose-synthesis flow (unchanged). Step 5 already had the
  auto-bootstrap-skip clause from v0.3.11.

### Tests

- 7 new unit tests pin the citation-folding contract: append,
  idempotence, body preservation, frontmatter preservation,
  `last_synthesized` bump, empty-vault no-op, combined with
  `created_stubs`.
- 1 smoke test pins the SKILL contract that the auto-chain path no
  longer Edits files.

## [0.3.12] - 2026-04-27

### Fixed

- **Quiet runner DEBUG noise leaking to user transcript.** The
  `wiki_ingest_plan` runner emitted a `logger.debug(
  "wiki_ingest_plan.stub_created", ...)` per stub created. With loguru's
  default DEBUG level, this leaked into every digest auto-chain run as
  three lines per paper of `2026-... | DEBUG | __main__:_bootstrap_
  missing_concepts:217 - wiki_ingest_plan.stub_created`. The
  `created_stubs` field in the JSON output already conveys the same
  information; deleted the redundant log call.
- **Quiet `dedup.vault.missing` warnings on fresh-vault first-run.**
  (Plan Task 9.11 partial.) When a recipe references vault subdirs that
  don't exist yet (the dominant case during first-time setup), the
  dedup loader logged WARNING for each missing path — three scary lines
  before the real work even started. Downgraded to DEBUG; a real
  misconfiguration still surfaces as zero dedup entries which the
  digest SKILL Red Flags catch.

## [0.3.11] - 2026-04-27

### Fixed

- **wiki-ingest SKILL now actually invokes the runner with
  `--auto-bootstrap`** when called by digest auto-chain. v0.3.9 added
  the flag to the runner; v0.3.10 made digest pass `--auto-bootstrap`
  in the SKILL prose; but the wiki-ingest SKILL.md Step 2 still showed
  the runner CLI shape WITHOUT the flag, so the LLM dropped the flag
  when invoking the runner — falling back to `<<PYEOF python -c ...`
  inline blocks to manually create stubs (the very black magic v0.3.9
  was supposed to replace). Step 2 now explicitly says "append
  `--auto-bootstrap` to the CLI when caller passed the flag", and Step 5
  explicitly says "if you used `--auto-bootstrap` in Step 2, SKIP this
  step entirely; do NOT write inline Python".
- **CI `ruff format --check`**: `_stub_constants.py` and
  `test_wiki_ingest_plan_auto_bootstrap.py` (added in v0.3.9) failed
  format check on the v0.3.10 release. Reformatted both files.

### Tests

- `test_wiki_ingest_skill_appends_auto_bootstrap_flag_to_runner_cli`
  pins Step 2's flag-append pattern.
- `test_wiki_ingest_skill_forbids_inline_python_fallback` pins Step 5's
  no-inline-Python contract so the v0.3.7 black-magic regression can't
  resurface.

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
