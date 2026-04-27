# Phase 6 + 7 + 9 Task List

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

## Phase 7.1 — Paperclip MCP wiring ✅

- [x] **7.1.1** Extend `diagnostics` runner to detect registered MCP
  servers via `claude mcp list` (subprocess). New report field:
  `mcp_servers: [str]`.
- [x] **7.1.2** Update `setup` SKILL to surface paperclip presence /
  absence and offer the registration command (`claude mcp add ...`)
  without auto-running.
- [x] **7.1.3** Add `docs/paperclip-setup.md` with registration steps
  and a link to upstream docs.
- [x] **Gate**: setup SKILL passes parametrized smoke test;
  manual smoke test deferred (requires real paperclip account).

## Phase 7.2 — `PaperclipSource` plugin ✅

- [x] **7.2.1** Add `src/paperwiki/plugins/sources/paperclip.py`
  subprocess wrapper.
- [x] **7.2.2** Tests under
  `tests/unit/plugins/sources/test_paperclip.py` mock at
  `asyncio.create_subprocess_exec`; 13 tests cover happy path +
  4 error paths.
- [x] **7.2.3** Wire the plugin into `paperwiki.config.recipe`
  `_build_source`.
- [x] **7.2.4** New recipe `recipes/biomedical-weekly.yaml`.
- [x] **7.2.5** Parametrized bundled-recipes test picks it up.
- [x] **Gate**: tests green; recipe loads; CHANGELOG updated.

## Phase 7.3 — `paperwiki:bio-search` SKILL ✅

- [x] **7.3.1** Add `skills/bio-search/SKILL.md` (six-section anatomy).
- [x] **7.3.2** Add `.claude/commands/bio-search.md`.
- [x] **7.3.3** Document the SKILL in `README.md` as optional.
- [x] **Gate**: parametrized smoke test green; plugin validate green.

---

## Phase 8 — PDF download + text extraction (candidate, v0.4.0)

> Promote from candidate once Phase 7 ships and we have empirical
> signal that the abstract-only flow is leaving deeper analyses on
> the table. Full design in [`tasks/plan.md`](plan.md) §9.

### Phase 8.1 — Foundation: fetch + extract helpers

- [ ] **8.1.1** Add `src/paperwiki/_internal/pdf.py` with
  `fetch_pdf(url, dest, *, http_client)` — idempotent, 1/sec
  token-bucket rate-limited, surfaces HTTP errors as
  `IntegrationError`.
- [ ] **8.1.2** Add `extract_text(pdf_path)` using `pypdf`; pages
  joined by `\f` form feeds.
- [ ] **8.1.3** Pin `pypdf>=4.0`. Commit `tests/fixtures/sample.pdf`
  (~2 KB). Add `Wiki/.cache/` to `.gitignore`.

### Phase 8.2 — `fetch_pdf` runner

- [ ] **8.2.1** Add `paperwiki.runners.fetch_pdf` Typer app. Reads
  `Wiki/sources/<id>.md` frontmatter for `pdf_url`; downloads;
  extracts; updates frontmatter (`pdf_cached`, `text_chars`); emits
  JSON.
- [ ] **8.2.2** Tests: happy path, missing source, missing pdf_url,
  HTTP 404, malformed PDF, idempotent re-run, `--force` re-fetch.
- [ ] **8.2.3** Update `MarkdownWikiBackend.upsert_paper` to write
  `pdf_url` into source frontmatter when `paper.pdf_url` is set.

### Phase 8.3 — Frontmatter markers + cache exclusion

- [ ] **8.3.1** Extend `SourceSummary` with `pdf_cached: bool` and
  `text_chars: int | None`. Defaults preserve legacy compatibility.
- [ ] **8.3.2** `wiki_lint` ignores `Wiki/.cache/`: cache files never
  resolve `BROKEN_LINK` and never count as `OVERSIZED`. Pinned by
  test.

### Phase 8.4 — `analyze` SKILL grounded in cached PDF text

- [ ] **8.4.1** Update `skills/analyze/SKILL.md`: invoke
  `fetch_pdf` first; if `text_chars >= 1000`, ground analysis in
  cached text; otherwise fall back to abstract with `confidence`
  capped at 0.4.
- [ ] **8.4.2** Smoke test asserts SKILL references `fetch_pdf` +
  the confidence cap.

### Phase 8.5 — `/paper-wiki:fetch-pdf` batch SKILL

- [ ] **8.5.1** Add `skills/fetch-pdf/SKILL.md` (six-section anatomy)
  + `.claude/commands/fetch-pdf.md`. Walks `Wiki/sources/*.md`,
  queues missing fetches, summarizes outcome.
- [ ] **8.5.2** Parametrized smoke test passes for the new SKILL.

### Phase 8.6 — Cache lifecycle / GC

- [ ] **8.6.1** Add `paperwiki.runners.gc_pdf_cache <vault>
  [--max-files N=50] [--max-mb M=500] [--dry-run]`. LRU by mtime;
  preserves entries `last_synthesized` within last 30 days. Tests
  cover count-trim, size-trim, dry-run, preservation rule.

### Phase 8.7 — Reporter polish

- [ ] **8.7.1** When `wiki_backend=True`, append a one-line
  "Run `/paper-wiki:fetch-pdf <id>` to deepen" hint to each source
  body. Hint disappears after the source is upserted with
  `pdf_cached: true`.

### Phase 8 — Gate

- [ ] All 8.x slice tests green.
- [ ] Coverage ≥ 90% on new modules.
- [ ] `mypy --strict`, `ruff check`, `ruff format --check`,
  `claude plugin validate .` green.
- [ ] `CHANGELOG.md` cuts `[0.4.0]`. Version bump in
  `pyproject.toml`, `__init__.py`, `plugin.json`. Tag `v0.4.0`.

---

## Phase 9 — Digest quality (active, v0.3.6 → v0.3.8)

> Full design in [`tasks/plan.md`](plan.md) §10.
> Goal: kill the placeholder-prose / stale-namespace / no-images
> regressions a user observed in `digest daily` on a fresh vault.
> Three small releases, six tasks, ~3 hours of focused work.

### Phase 9 — Release v0.3.6 (namespace + skeleton cleanup)

- [ ] **9.1 — Namespace mechanical fix.** Plan §10.2 Task 9.1.
  Complexity **M**. Replace every `/paperwiki:` with `/paper-wiki:`
  across `src/`, `skills/`, `recipes/`, `docs/`, `SPEC.md`,
  `.claude/commands/`, plus the per-paper assertion strings in
  `tests/unit/plugins/{reporters,backends}/`,
  `tests/unit/runners/test_extract_paper_images.py`,
  `tests/integration/test_digest_wiki_handoff.py`,
  `tests/test_smoke.py` (28 hits in tests). Skip `CHANGELOG.md`
  historical entries and `.claude/worktrees/`.
  **Acceptance check**: `grep -rn '/paperwiki:' src skills recipes
  docs SPEC.md .claude/commands` returns zero hits; `pytest -q` green.
- [ ] **9.2 — Runner emits clean skeleton markers.** Plan §10.2 Task
  9.2. Complexity **S**. Replace prose stubs in
  `src/paperwiki/plugins/reporters/obsidian.py::_render_overview_callout`
  and `_render_recommendation` "Detailed report" branch with HTML
  comment markers `<!-- paper-wiki:overview-slot -->` and
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->`. Update existing
  tests (`tests/unit/plugins/reporters/test_obsidian.py:135-145, 168-172`)
  + add `test_skeleton_markers_are_machine_targetable`.
  **Acceptance check**: rendered digest contains exactly one overview
  marker and one per-paper marker per recommendation; old prose stubs
  gone.
- [ ] **9.6 — Invariant test for stale namespace.** Plan §10.2 Task 9.6.
  Complexity **S**. Add `tests/test_smoke.py::test_no_stale_paperwiki_namespace`
  scanning `src/`, `skills/`, `recipes/`, `docs/`, `SPEC.md`,
  `.claude/commands/`. Land in the same commit as 9.1 so CI stays
  green.
  **Acceptance check**: test passes after 9.1; manually breaking one
  file produces a failure listing the file + line.
- [ ] **v0.3.6 Gate**: `pytest -q`, `ruff check`, `mypy --strict`,
  `claude plugin validate .` all green; CHANGELOG `[0.3.6]` entry;
  version bump in `pyproject.toml`, `__init__.py`, `plugin.json`;
  tag `v0.3.6`.

### Phase 9 — Release v0.3.7 (Today's Overview synthesis)

- [ ] **9.3 — Today's Overview synthesis pass.** Plan §10.2 Task 9.3.
  Complexity **M**. Extend `skills/digest/SKILL.md` Process with a
  step (between summary and auto-ingest-top) that reads the digest
  file from disk, replaces `<!-- paper-wiki:overview-slot -->` with
  60-200 words of synthesized cross-paper prose citing `#N` indices.
  Add SKILL Common Rationalizations row about hallucinating trends.
  Add `test_digest_skill_describes_overview_synthesis` smoke test.
  **Acceptance check**: SKILL.md contains both `paper-wiki:overview-slot`
  and "Today's Overview"; manual run on `daily` recipe yields prose
  with at least one `#N` reference matching an entry below.
- [ ] **9.7 — Auto-ingest bootstrap on fresh vault.** Plan §10.2 Task
  9.7. Complexity **S-M**. Extend `skills/wiki-ingest/SKILL.md` with
  an `--auto-bootstrap` mode that auto-stubs missing concept articles
  (`auto_created: true` frontmatter + sentinel "_Auto-created during
  digest auto-ingest. Lint with /paper-wiki:wiki-lint to flag for
  review._" body) before the update loop runs. Update
  `skills/digest/SKILL.md` Process step 7 to pass `--auto-bootstrap`
  for every auto-chained call. Update `skills/wiki-lint/SKILL.md` to
  surface `auto_created: true` stubs in a dedicated "needs review"
  bucket. Add `test_wiki_ingest_skill_describes_auto_bootstrap_mode`
  and `test_digest_skill_passes_auto_bootstrap_to_wiki_ingest` smoke
  tests.
  **Acceptance check**: wiki-ingest SKILL.md documents the flag +
  sentinel; digest SKILL auto-chain passes the flag; manual
  `rm -rf <vault>/Wiki && /paper-wiki:digest daily` with
  `auto_ingest_top: 3` creates 3 stubs and updates them without any
  confirmation prompt; subsequent `/paper-wiki:wiki-lint` flags those
  stubs in a "needs review" section.
- [ ] **v0.3.7 Gate**: same as v0.3.6 gate; manual digest smoke test
  on a fresh vault produces a meaningful overview AND auto-ingest
  creates concept stubs end-to-end without prompts; tag `v0.3.7`.

### Phase 9 — Release v0.3.8 (upgrade UX)

- [ ] **9.8 — Standard upgrade flow (OMC-style).** Plan §10.2 Task 9.8.
  Complexity **S**. Add `"skills": "./skills/"` to
  `.claude-plugin/plugin.json`; rewrite README upgrade section to
  document standard `/plugin uninstall paper-wiki@paper-wiki` + `/plugin
  install paper-wiki@paper-wiki` + fresh `claude` session flow; remove
  `rm -rf cache` language. Add three contract smoke tests:
  `test_plugin_manifest_declares_skills_directory`,
  `test_readme_documents_standard_upgrade_flow`,
  `test_readme_does_not_recommend_manual_cache_nuke`. Version bump
  0.3.7 → 0.3.8. CHANGELOG `[0.3.8]` entry.
  **Acceptance check**: `pytest -x -q` green; `ruff check` clean;
  `mypy --strict` clean; plugin.json has `"skills"` field.
- [ ] **v0.3.8 Gate**: `pytest -q`, `ruff check`, `mypy --strict`,
  `claude plugin validate .` all green; CHANGELOG `[0.3.8]` entry;
  version bump in `pyproject.toml`, `__init__.py`, `plugin.json`;
  tag `v0.3.8`.

### Phase 9 — Release v0.3.9 (close auto-bootstrap runner gap)

- [ ] **9.10 — Implement `--auto-bootstrap` properly in the runner.**
  Plan §10.2 Task 9.10. Complexity **M**. Extend
  `paperwiki.runners.wiki_ingest_plan` to accept `--auto-bootstrap`:
  when set and `source_exists`, create `Wiki/concepts/<name>.md`
  stubs (frontmatter `auto_created: true`, sentinel body) for every
  entry in `suggested_concepts`; move stubbed names into
  `affected_concepts`; add `created_stubs: list[str]` to the JSON
  output. Simplify the `skills/wiki-ingest/SKILL.md` Auto-bootstrap
  Process to a runner pass-through; remove the inline-Python
  `MarkdownWikiBackend.upsert_concept` fallback prose. Add Common
  Rationalizations row about bypassing the runner. Add unit tests:
  `test_auto_bootstrap_creates_stubs_for_suggested_concepts`,
  `test_auto_bootstrap_skips_existing_concepts`,
  `test_auto_bootstrap_no_op_when_source_missing`,
  `test_auto_bootstrap_unset_preserves_legacy_behavior`. Update
  smoke test `test_wiki_ingest_skill_describes_auto_bootstrap_mode`
  to assert the runner-invocation form, not the upsert_concept form.
  **Acceptance check**: `python -m paperwiki.runners.wiki_ingest_plan
  <vault> <id> --auto-bootstrap` creates stubs and emits
  `created_stubs` in JSON; manual `rm -rf <vault>/Wiki && /paper-wiki:digest
  daily` with `auto_ingest_top: 3` shows no inline-Python fallback in
  the SKILL trace.
- [ ] **v0.3.9 Gate**: same as v0.3.6 gate; manual auto-bootstrap
  smoke test on a fresh vault produces 3 stubs via the runner with
  no `asyncio.run` fallback observed; CHANGELOG `[0.3.9]` entry
  notes the new `created_stubs` JSON field; tag `v0.3.9`.

### Phase 9 — Release v0.3.10 (per-paper synthesis + auto images)

- [ ] **9.4 — Per-paper Detailed report synthesis.** Plan §10.2 Task
  9.4. Complexity **M-L**. Extend `skills/digest/SKILL.md` Process
  with a per-paper synthesis step: each
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->` marker becomes
  a "Why this matters" + "Key takeaways" + "Score reasoning" block.
  Default to batched-prompt; fall back to per-paper when batch
  exceeds context window. Add Common Rationalizations row about
  inventing claims. Add `test_digest_skill_describes_per_paper_synthesis`
  smoke test.
  **Acceptance check**: SKILL.md mentions `paper-wiki:per-paper-slot`
  and "Detailed report" and forbids the historical
  `/paper-wiki:analyze`-as-fallback prose; manual run shows synthesized
  per-paper prose with no marker remaining.
- [ ] **9.5 — Auto image extraction for auto_ingest_top papers.**
  Plan §10.2 Task 9.5. Complexity **S**. Extend
  `skills/digest/SKILL.md` Process to chain
  `/paper-wiki:extract-images <canonical-id>` for each of the
  `min(auto_ingest_top, top_k)` papers BEFORE the wiki-ingest chain.
  Skip non-`arxiv:` ids with a one-liner. Add
  `test_digest_skill_chains_extract_images` smoke test.
  **Acceptance check**: SKILL.md Process names `extract-images` and
  `wiki-ingest` in the right order; manual run with `auto_ingest_top=3`
  populates `Wiki/sources/<id>/images/` for top-3 papers; the next
  digest run inlines `![[...|700]]` teasers in those entries.
- [ ] **v0.3.10 Gate**: same as v0.3.6 gate; manual full-cycle smoke
  test (run digest twice on a fresh vault; second run should have
  inline figures + per-paper synthesis); tag `v0.3.10`.

### Phase 9 — Release v0.3.11 (digest quality refinements)

- [ ] **9.9 — Concept matching threshold + recipe tightening.** Plan
  §10.2 Task 9.9. Complexity **M**. Extend
  `CompositeScorer._compute_relevance` to populate
  `ScoreBreakdown.notes["topic_strengths"]` with per-topic strength
  using the same saturating curve (`1 - 0.5**hits`). Update
  `MarkdownWikiBackend.upsert_source` to accept
  `topic_strength_threshold: float = 0.3` and filter
  `matched_topics` → `related_concepts` accordingly. Plumb a
  `wiki_topic_strength_threshold` recipe-config field on the
  `obsidian` reporter. Tighten `skills/setup/SKILL.md` Q2 keyword
  template for "Biomedical & Pathology" — drop `foundation model`,
  consolidate the WSI duplicates, add biomedical-specific terms;
  add a Common Rationalizations row about generic-keyword leakage.
  Add smoke tests
  `test_composite_scorer_emits_per_topic_strengths`,
  `test_wiki_upsert_source_filters_by_topic_strength`,
  `test_setup_skill_biomedical_keywords_exclude_generic_terms`.
  **Acceptance check**: a manually-rebuilt personal recipe via
  `/paper-wiki:setup` Branch 2 → Topics → Biomedical & Pathology
  no longer contains `foundation model`; running the daily digest
  with the new threshold keeps an `OccDirector`-style autonomous-driving
  paper out of the `biomedical-pathology` concept's `sources:` list.
- [ ] **9.11 — Quiet `dedup.vault.missing` warnings on absent paths.**
  Plan §10.2 Task 9.11. Complexity **S**. Downgrade
  `src/paperwiki/plugins/filters/dedup.py:160` from
  `logger.warning("dedup.vault.missing", path=...)` to
  `logger.info("dedup.vault.absent", path=..., note="vault path
  not yet created; dedup uses empty key set")`. Keep the OSError
  branch at line 170 at WARNING. Add
  `test_dedup_loader_logs_info_when_vault_path_absent`.
  **Acceptance check**: fresh-vault `/paper-wiki:digest daily`
  surfaces zero `WARNING` lines for missing vault paths; the
  structured log still records the event at INFO with the
  `dedup.vault.absent` event name.
- [ ] **9.12 — Improve auto-stub UX (sentinel body + wiki-lint
  message).** Plan §10.2 Task 9.12. Complexity **S**. Update the
  `skills/wiki-ingest/SKILL.md` Auto-bootstrap sentinel body to a
  two-paragraph version that explicitly tells the user to run
  `/paper-wiki:wiki-ingest <source-id>` to fold real content in.
  Update `skills/wiki-lint/SKILL.md` Process Step 2 to clarify that
  auto-created stubs are intentionally empty until wiki-ingest is
  invoked. If Task 9.10 has shipped, define the sentinel as a shared
  constant in `paperwiki.runners._stub_constants` referenced by both
  the runner and the SKILL test. Add smoke tests
  `test_wiki_ingest_sentinel_body_explains_next_step`,
  `test_wiki_lint_explains_auto_stub_intent`.
  **Acceptance check**: opening any new auto-stub shows the
  two-paragraph guidance; `/paper-wiki:wiki-lint` "Needs review"
  message contains the intent clarification.
- [ ] **v0.3.11 Gate**: same as v0.3.6 gate; manual smoke (fresh
  vault, run digest, inspect `biomedical-pathology` concept's
  source list — should be empty or biomedical-only; check log
  output for zero `WARNING` lines on missing vault paths; open an
  auto-stub and confirm new sentinel guidance); tag `v0.3.11`.

### Phase 9 — Final checklist

- [ ] All 9.x slice gates green.
- [ ] `pytest --cov=paperwiki --cov-report=term-missing` ≥ 90% overall.
- [ ] `mypy --strict src` clean.
- [ ] `ruff check src tests` clean.
- [ ] `ruff format --check src tests` clean.
- [ ] `claude plugin validate .` passes.
- [ ] CHANGELOG entries for `[0.3.6]`, `[0.3.7]`, `[0.3.8]`, `[0.3.9]`,
  `[0.3.10]`, `[0.3.11]` complete.
- [ ] Tag each release in turn: `v0.3.6`, `v0.3.7`, `v0.3.8`, `v0.3.9`,
  `v0.3.10`, `v0.3.11`.

---

## Final phase-completion checklist

- [ ] All slice gates green.
- [ ] `pytest --cov=paperwiki --cov-report=term-missing` ≥ 90% overall.
- [ ] `mypy --strict src` clean.
- [ ] `ruff check src tests` clean.
- [ ] `ruff format --check src tests` clean.
- [ ] `claude plugin validate .` passes.
- [ ] CHANGELOG complete; SemVer bumps in `pyproject.toml`,
  `__version__`, `plugin.json`:
  - `0.2.0` after Phase 6 ✅
  - `0.3.0` after Phase 7 ✅
  - `0.3.5` after README rewrite ✅
  - `0.3.6` → `0.3.7` → `0.3.8` → `0.3.9` → `0.3.10` → `0.3.11` after
    Phase 9 (digest quality)
  - `0.4.0` after Phase 8 (when promoted from candidate)
- [ ] README, SPEC §3, recipes/README updated.
- [ ] Tag `v0.2.0` after Phase 6 ✅, `v0.3.0` after Phase 7 ✅,
  `v0.3.5` after README rewrite ✅, then `v0.3.6` / `v0.3.7` /
  `v0.3.8` / `v0.3.9` / `v0.3.10` / `v0.3.11` per Phase 9, then
  `v0.4.0` after Phase 8 (if promoted).
