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

- [x] All 6.2.1 – 6.2.12 shipped (see prior plan revisions for detail).
- [x] **Gate**: tests green; `claude plugin validate .` green.

## Phase 6.3 — Wiki / dedup integration ✅

- [x] All 6.3.1 – 6.3.6 shipped.
- [x] **Gate**: dedup tests still pass; new integration tests green;
  CHANGELOG updated.

---

## Phase 7.1 — Paperclip MCP wiring ✅

- [x] **7.1.1**, **7.1.2**, **7.1.3** shipped.
- [x] **Gate**: setup SKILL parametrized smoke test passes.

## Phase 7.2 — `PaperclipSource` plugin ✅

- [x] **7.2.1 – 7.2.5** shipped.
- [x] **Gate**: tests green; recipe loads; CHANGELOG updated.

## Phase 7.3 — `paperwiki:bio-search` SKILL ✅

- [x] **7.3.1 – 7.3.3** shipped.
- [x] **Gate**: parametrized smoke test green; plugin validate green.

---

## Phase 8 — PDF download + text extraction (candidate, v0.5.0)

> Promote from candidate once Phase 9 stabilizes. Full design in
> [`tasks/plan.md`](plan.md) §9.

(Items 8.1.1 – 8.7.1 unchanged from prior plan; deferred until Phase 9
ships and we have empirical signal that abstract-only flow is
insufficient.)

---

## Phase 9 — Digest quality (active, v0.3.6 → v0.3.18)

> Full design in [`tasks/plan.md`](plan.md) §10.
> Goal: kill the placeholder-prose, stale-namespace, no-images,
> SKILL-orchestration-hang, and per-release-regression failure modes
> the user has hit on three successive fresh-vault digest runs
> (v0.3.5, v0.3.10, v0.3.12).

### Phase 9 — Releases v0.3.6 → v0.3.12 (shipped) ✅

- [x] **v0.3.6** — 9.1 + 9.2 + 9.6 (namespace + skeleton markers + invariant test)
- [x] **v0.3.7** — 9.3 + 9.7 (Today's Overview synthesis + auto-bootstrap docs)
- [x] **v0.3.8** — 9.8 (standard upgrade flow + `"skills"` declaration)
- [x] **v0.3.9** — 9.10 (runner accepts `--auto-bootstrap`, creates stubs)
- [x] **v0.3.10** — digest SKILL: imperative auto-chain (no "shall I?" prompt)
- [x] **v0.3.11** — wiki-ingest SKILL: append `--auto-bootstrap` to runner CLI; forbid inline-Python fallback
- [x] **v0.3.12** — quiet runner DEBUG noise + downgrade `dedup.vault.missing` to DEBUG

### Phase 9 — Release v0.3.13 (citation folding moves to runner)

- [ ] **9.13 — Move citation folding from SKILL to runner.** Plan §10.2 Task 9.13.
  Complexity **L**. Extend `paperwiki.runners.wiki_ingest_plan` (or split into a
  new `wiki_ingest` runner — see plan §10.8) to also FOLD the source's
  `canonical_id` into each affected concept's `sources:` list as a
  deterministic YAML mutation. New runner CLI:
  `python -m paperwiki.runners.wiki_ingest <vault> <canonical-id>
  [--auto-bootstrap] [--fold-citations]`. The `--fold-citations` mode
  reads each concept's frontmatter, appends `canonical_id` to the
  `sources:` list (idempotent — skip if already present), bumps
  `last_synthesized` to today, and re-writes the file. NO LLM. The
  existing concept body is preserved verbatim. JSON output gains a
  `folded_citations: list[str]` field listing concept names whose
  `sources` list grew. The wiki-ingest SKILL Step 4 (LLM-synthesize
  updated body + Edit) is REPLACED with a runner pass-through — only
  triggered explicitly when the user wants prose synthesis (manual
  invocations); auto-chained digest calls only fold citations.
  **Acceptance check**: `python -m paperwiki.runners.wiki_ingest
  <vault> arxiv:2506.13063 --auto-bootstrap --fold-citations` succeeds
  on a vault where two concepts already exist; both concepts gain the
  `arxiv:2506.13063` entry in their `sources:` frontmatter; concept
  bodies are unchanged byte-for-byte; SKILL.md no longer contains
  `Read 2 files (ctrl+o to expand)` style Edit-tool dances.
- [ ] **9.16 — Update SKILLs to USE runners, not orchestrate them.** Plan §10.2
  Task 9.16. Complexity **M**. Once 9.13 lands, the digest SKILL Process
  Step 8 simplifies to a single `subprocess.run` per paper that invokes
  `wiki_ingest --auto-bootstrap --fold-citations` — no SKILL-side
  Edits, no Read+Edit dance, no LLM in the loop. The wiki-ingest
  SKILL's "Auto-bootstrap mode" section becomes a four-line runner
  invocation summary. Keep prose-synthesis path (full-body update via
  Claude) as the EXPLICIT manual `/paper-wiki:wiki-ingest <id>`
  branch — opt-in for users who want a quality concept article rebuild,
  NOT auto-chained from digest.
  **Acceptance check**: `grep -n "Edit\|Read.*concept" skills/wiki-ingest/SKILL.md`
  for the auto-bootstrap path returns zero hits; manual smoke (fresh
  vault → digest → auto-chain) completes in < 30 seconds with no LLM
  Edits in the transcript.
- [ ] **v0.3.13 Gate**: `pytest -q`, `ruff check`, `mypy --strict`,
  `claude plugin validate .` all green; CHANGELOG `[0.3.13]` entry;
  version bump in `pyproject.toml`, `__init__.py`, `plugin.json`;
  tag `v0.3.13`.

### Phase 9 — Release v0.3.14 (end-to-end smoke test)

- [ ] **9.14 — Add an end-to-end smoke test exercising the full pipeline.**
  Plan §10.2 Task 9.14. Complexity **M**. New
  `tests/integration/test_full_digest_auto_chain.py`. Uses a temp vault
  + a stub `Source` plugin emitting 3 deterministic Papers (no
  network) + the real `RelevanceFilter`, `CompositeScorer`,
  `MarkdownReporter`, `ObsidianReporter(wiki_backend=true)`,
  `MarkdownWikiBackend`. Recipe declares `auto_ingest_top: 3`. Asserts:
  (a) digest produces 10 recommendations, (b) the 3 expected source
  files land in `Wiki/sources/`, (c) **the `wiki_ingest` runner is
  invoked subprocess-style (or in-process) with `--auto-bootstrap
  --fold-citations` for each top-3 paper**, (d) 3 stub concepts get
  created (`auto_created: true`), (e) each affected concept's
  `sources:` list contains the source's canonical_id, (f) NO Claude
  Edit/Read tool calls are recorded — only Python file I/O. Pin: this
  test runs in CI on every commit and is the floor that catches every
  per-release regression.
  **Acceptance check**: `pytest -q tests/integration/test_full_digest_auto_chain.py`
  passes; deliberately breaking the `--fold-citations` flag in the
  runner makes this test fail with a precise message about which
  concept is missing the source citation.
- [ ] **v0.3.14 Gate**: same as v0.3.13 gate; manual fresh-vault smoke
  passes (digest → auto-chain → result on disk in < 30s); tag `v0.3.14`.

### Phase 9 — Release v0.3.15 (centralized logger + --verbose)

- [ ] **9.15 — Centralize logger config + `--verbose` flag.** Plan §10.2
  Task 9.15. Complexity **S**. Add `src/paperwiki/_internal/logging.py`
  with `configure_runner_logging(verbose: bool, *, default_level:
  str = "INFO")`. Removes loguru's default DEBUG sink and re-adds a
  stderr sink at INFO (or DEBUG when `verbose=True`); pins
  `paperwiki.plugins.filters.dedup`, `paperwiki._internal.arxiv_source`
  to WARNING by default. Every runner's `main()` calls
  `configure_runner_logging(verbose=verbose_flag)` as the first line.
  Add `--verbose / -v` Typer option to all runners (`digest`,
  `wiki_ingest`, `wiki_lint`, `wiki_compile`, `wiki_query`,
  `extract_paper_images`, `migrate_sources`, `diagnostics`). Add
  `PAPERWIKI_LOG_LEVEL` env var override for the SessionStart-hook /
  CI use case. New unit test
  `tests/unit/_internal/test_logging.py::test_configure_runner_logging_default_level_is_info`
  pins the contract.
  **Acceptance check**: fresh-vault `/paper-wiki:digest daily` shows
  zero DEBUG lines on stdout/stderr by default; `--verbose` re-enables
  DEBUG; `PAPERWIKI_LOG_LEVEL=WARNING` silences INFO.
- [ ] **v0.3.15 Gate**: same as v0.3.13 gate; CHANGELOG `[0.3.15]`
  entry; tag `v0.3.15`.

### Phase 9 — Release v0.3.16 (per-paper Detailed report + auto images)

- [ ] **9.4 — Per-paper Detailed report synthesis.** Plan §10.2 Task 9.4
  (originally targeted v0.3.10). Complexity **M-L**. Extend
  `skills/digest/SKILL.md` Process with a per-paper synthesis step:
  each `<!-- paper-wiki:per-paper-slot:{canonical_id} -->` marker
  becomes a "Why this matters" + "Key takeaways" + "Score reasoning"
  block. Default to batched-prompt; fall back to per-paper when batch
  exceeds context window. Add Common Rationalizations row about
  inventing claims. Add `test_digest_skill_describes_per_paper_synthesis`
  smoke test. CRITICAL: this synthesis step happens AFTER the auto-chain
  runner returns, so a SKILL hang here doesn't block the on-disk
  citation-folding work — see §10.10 (Task 9.18).
  **Acceptance check**: SKILL.md mentions `paper-wiki:per-paper-slot`
  and "Detailed report"; manual run shows synthesized per-paper prose
  with no marker remaining; if SKILL is interrupted mid-synthesis, the
  digest file is still on disk with all per-paper slots filled by
  whatever has been written so far.
- [ ] **9.5 — Auto image extraction for auto_ingest_top papers.**
  Plan §10.2 Task 9.5 (originally targeted v0.3.10). Complexity **S**.
  Extend `skills/digest/SKILL.md` Process to chain
  `/paper-wiki:extract-images <canonical-id>` for each of the
  `min(auto_ingest_top, top_k)` papers BEFORE the wiki-ingest chain.
  Skip non-`arxiv:` ids with a one-liner. Add
  `test_digest_skill_chains_extract_images` smoke test.
  **Acceptance check**: SKILL.md Process names `extract-images` and
  `wiki-ingest` in the right order; manual run with `auto_ingest_top=3`
  populates `Wiki/sources/<id>/images/` for top-3 papers; the next
  digest run inlines `![[...|700]]` teasers in those entries.
- [ ] **v0.3.16 Gate**: same as v0.3.13 gate; manual full-cycle smoke
  test (run digest twice on a fresh vault; second run should have
  inline figures + per-paper synthesis); tag `v0.3.16`.

### Phase 9 — Release v0.3.17 (concept matching threshold + auto-stub UX)

- [ ] **9.9 — Concept matching threshold + recipe tightening.** Plan
  §10.2 Task 9.9. Complexity **M**. Extend
  `CompositeScorer._compute_relevance` to populate
  `ScoreBreakdown.notes["topic_strengths"]` with per-topic strength
  using the same saturating curve (`1 - 0.5**hits`). Update
  `MarkdownWikiBackend.upsert_paper` to accept
  `topic_strength_threshold: float = 0.3` and filter
  `matched_topics` → `related_concepts` accordingly. Plumb a
  `wiki_topic_strength_threshold` recipe-config field on the
  `obsidian` reporter. Tighten `skills/setup/SKILL.md` Q2 keyword
  template for "Biomedical & Pathology" — drop `foundation model`,
  consolidate the WSI duplicates, add biomedical-specific terms;
  add a Common Rationalizations row about generic-keyword leakage.
  Add smoke tests `test_composite_scorer_emits_per_topic_strengths`,
  `test_wiki_upsert_source_filters_by_topic_strength`,
  `test_setup_skill_biomedical_keywords_exclude_generic_terms`.
  **Acceptance check**: a manually-rebuilt personal recipe via
  `/paper-wiki:setup` Branch 2 → Topics → Biomedical & Pathology
  no longer contains `foundation model`; running the daily digest
  with the new threshold keeps an `OccDirector`-style autonomous-driving
  paper out of the `biomedical-pathology` concept's `sources:` list.
- [ ] **9.12 — Auto-stub UX (sentinel body + wiki-lint message).**
  Plan §10.2 Task 9.12. Complexity **S**. Update
  `AUTO_CREATED_SENTINEL_BODY` in
  `paperwiki.runners._stub_constants` to a two-paragraph version that
  explicitly tells the user to run `/paper-wiki:wiki-ingest <source-id>`
  to fold real content in. Update `skills/wiki-lint/SKILL.md` Process
  Step 2 to clarify that auto-created stubs are intentionally empty
  until wiki-ingest is invoked. Add smoke tests
  `test_auto_created_sentinel_body_explains_next_step`,
  `test_wiki_lint_explains_auto_stub_intent`.
  **Acceptance check**: opening any new auto-stub shows the
  two-paragraph guidance; `/paper-wiki:wiki-lint` "Needs review"
  message contains the intent clarification.
- [ ] **v0.3.17 Gate**: same as v0.3.13 gate; manual smoke (fresh
  vault, run digest, inspect `biomedical-pathology` concept's source
  list — should be empty or biomedical-only; open an auto-stub and
  confirm new sentinel guidance); tag `v0.3.17`.

### Phase 9 — Release v0.3.18 (defensive concurrency + digest-overview separation)

- [ ] **9.17 — Defensive concurrency lock.** Plan §10.2 Task 9.17.
  Complexity **S-M**. Add `src/paperwiki/_internal/locking.py` with
  `acquire_vault_lock(vault_path: Path, *, timeout_s: float = 5.0,
  stale_after_s: float = 300.0)` context manager. Writes
  `<vault>/.paperwiki.lock` containing `{pid, host, started_at,
  runner_name}` JSON. Releases on exit. Reclaims stale locks
  (`stale_after_s` exceeded — the previous holder crashed). Every
  vault-mutating runner (`wiki_ingest`, `wiki_compile`,
  `migrate_sources`, the obsidian reporter when `wiki_backend=true`)
  acquires the lock for the duration of mutation. Read-only runners
  (`wiki_query`, `wiki_lint`, `diagnostics`) do NOT lock. Two
  parallel digest runs against the same vault produce a clear
  `UserError("vault is locked by pid=...; retry in N seconds or rm
  <path>/.paperwiki.lock if stale")`. New unit tests
  `test_lock_blocks_concurrent_writers`,
  `test_lock_is_released_on_exception`,
  `test_stale_lock_is_reclaimed`.
  **Acceptance check**: `pytest -q tests/unit/_internal/test_locking.py`
  passes; manual: open two terminals, run `python -m
  paperwiki.runners.wiki_ingest <vault> <id>` simultaneously — second
  invocation exits 1 with the lock-held message instead of corrupting
  shared state.
- [ ] **9.18 — Make Today's Overview synthesis crash-safe.**
  Plan §10.2 Task 9.18. Complexity **S**. Document in
  `skills/digest/SKILL.md` Process that the on-disk digest file
  must be COMPLETE (per-paper sections written, all per-paper slot
  markers present) BEFORE the SKILL begins overview synthesis. The
  overview-slot marker SURVIVES on disk if the SKILL crashes mid-pass —
  user re-running the SKILL re-fills only the slot, doesn't re-run the
  pipeline. Add Common Rationalizations row about "I'll synthesize the
  overview before flushing per-paper sections — it's faster". Add
  smoke test `test_digest_skill_synthesizes_overview_after_pipeline_complete`.
  **Acceptance check**: SKILL.md Process explicitly orders pipeline
  flush → per-paper synthesis → overview synthesis; manual: SIGINT
  the SKILL during overview synthesis, re-run; only overview slot is
  re-filled, per-paper sections preserved verbatim.
- [ ] **v0.3.18 Gate**: same as v0.3.13 gate; manual two-terminal
  smoke (concurrent digest = clean error, no corruption); manual
  SIGINT smoke (mid-overview crash → re-run = idempotent fill); tag
  `v0.3.18`.

### Phase 9 — Release v0.3.19 (figures inside Detailed reports + top-N gating)

- [ ] **9.22 — Inline figures in synthesized Detailed reports.**
  Plan §10.17 Task 9.22. Complexity **S-M**. Extend
  `skills/digest/SKILL.md` Process Step 8 contract: when synthesizing
  the Detailed report for a paper whose `Wiki/sources/<id>/images/`
  directory has at least one extracted figure, add a `**Figures.**`
  block between Key takeaways and Score reasoning containing 1–2
  Obsidian `![[<source_filename>/images/<name>|600]]` embeds.
  Selection heuristic: 1 file if directory has ≤ 2 figures; 2 files
  if 3+; prefer alphabetical-first names matching `fig1.*` /
  `figure_1.*` / `teaser.*`. Distinct from the existing card-teaser
  embed (`|700` size at the card level vs `|600` inside the
  synthesized block). Add Common Rationalizations rows: "Card
  teaser already shows a figure" and "I'll embed all 7 architecture
  diagrams". Add smoke test
  `test_digest_skill_embeds_figures_in_detailed_report`. Pure SKILL
  prose change; no Python edits.
  **Acceptance check**: SKILL.md mentions "Figures" embed contract,
  alphabetical-sort + `fig1`/`teaser` heuristic, `|600` size; manual
  smoke against a fresh vault confirms top-N papers with extracted
  figures get inline embeds inside their synthesized Detailed report.
- [ ] **9.24 — Detailed reports gated by `auto_ingest_top`.**
  Plan §10.19 Task 9.24. Complexity **S**. Update
  `skills/digest/SKILL.md` Process Step 8 to synthesize Detailed
  reports ONLY for the top `min(auto_ingest_top, top_k)` papers; for
  papers ranked below, replace the
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->` marker with a
  one-line teaser: `_Run /paper-wiki:analyze <canonical-id> for a
  deep dive on this paper._`. When `auto_ingest_top == 0`, ALL slots
  get the teaser (no synthesis). Add Common Rationalizations row:
  "I synthesized Detailed reports for all 10 papers — more value
  for the user." → "Wrong. `auto_ingest_top` controls treatment
  depth." Add Red Flag. Add smoke test
  `test_digest_skill_gates_detailed_reports_by_auto_ingest_top`.
  Pure SKILL prose change; no Python edits, no reporter plumbing
  (Option 1 from the design doc).
  **Acceptance check**: with `auto_ingest_top: 3` and `top_k: 10`,
  digest file has 3 synthesized Detailed reports + 7 teaser lines;
  with `auto_ingest_top: 0`, digest file has 10 teaser lines and
  zero synthesis.
- [ ] **v0.3.19 Gate**: same as v0.3.13 gate; manual smoke (run
  digest with `auto_ingest_top: 3` against fresh vault — confirm
  top-3 Detailed reports have inline `![[...]]` figure embeds AND
  papers #4–#10 show only the analyze-link teaser); CHANGELOG
  `[0.3.19]` entry; version bump in `pyproject.toml`,
  `__init__.py`, `plugin.json`; tag `v0.3.19`.

### Phase 9 — Release v0.3.20 (image extraction quality leap, 9.25)

- [ ] **9.25 — Improve `extract-paper-images` per evil-read-arxiv reference.**
  Plan §10.20 Task 9.25. Complexity **M-L** (90-120 min). Reference repo
  at `/Users/fangyi/Projects/evil-read-arxiv/extract-paper-images/`
  (SKILL.md + scripts/extract_images.py) — read both BEFORE implementing.
  Add PyMuPDF (`pymupdf>=1.24`) to `pyproject.toml`. Extend
  `paperwiki._internal.arxiv_source` with 3-priority fallback chain:
  (1) figure dirs (existing); (2) standalone PDF figures at source root
  → convert to PNG via `fitz.open(pdf).get_pixmap(matrix=Matrix(3,3))`;
  (3) TikZ detection (`\begin{tikzpicture}` / `pgfplots` in `.tex`) →
  caption-aware crop of paper PDF at "Figure N:" text-block boundaries.
  Generate `images/index.md` manifest with source classes
  (`arxiv-source` / `pdf-figure` / `pdf-extraction` / `tikz-cropped`).
  Min-size filter (>200px on at least one axis) applies to all
  priorities. Cap K=8 cropped figures per paper. Surface per-priority
  count in JSON output. Add `tests/unit/_internal/test_arxiv_source.py`
  fixtures for each priority + min-size edge.
  **Acceptance check**: AC-9.25.1 through 9.25.6 all pass; v0.3.18
  smoke #1 paper that gave 0 images now yields ≥1 figure via Priority
  2 or 3.
- [ ] **9.26 — `paperwiki update` CLI for in-place plugin upgrade.**
  Plan §10.21 Task 9.26. Complexity **S-M** (30-45 min). Reference:
  OMC's `omc update` (architecturally identical purpose). Add
  `[project.scripts] paperwiki = "paperwiki.cli:main"` to
  `pyproject.toml`; create `src/paperwiki/cli.py` Typer app with
  `update` / `status` / `uninstall` subcommands. `update` does:
  (1) `git pull` marketplace clone, (2) compare versions, (3) on
  drift rename cache to `.bak.<UTC-ts>` + drop entries from
  `installed_plugins.json` + `settings.json`/`settings.local.json`
  enabledPlugins, (4) print fresh-session install instructions.
  Idempotent. README "Upgrading" section rewritten to lead with
  `paperwiki update`; manual JSON-cleanup flow demoted to footnote.
  Add `tests/unit/test_cli.py` (typer CliRunner + tmp_path fixtures)
  covering: stale cache (mutation + exit 0), up-to-date (no-op),
  missing marketplace clone (exit 2), malformed JSON (exit 1).
  **Acceptance check**: AC-9.26.1 through 9.26.7 pass; manual smoke
  on user's actual machine — `paperwiki update` then fresh `claude`
  + `/plugin install paper-wiki@paper-wiki` succeeds WITHOUT "already
  installed" short-circuit.
- [ ] **v0.3.20 Gate**: same as v0.3.13 gate; manual smoke
  combinations: (a) re-run digest on a fresh vault and confirm
  `Wiki/sources/<id>/images/` populates for ≥80% of arXiv papers
  (vs ~30% today, demonstrates 9.25); (b) `paperwiki update` →
  fresh `claude` → `/plugin install paper-wiki@paper-wiki` works in
  one shot, no JSON editing required (demonstrates 9.26); CHANGELOG
  `[0.3.20]` entry noting PyMuPDF dependency + license compatibility +
  the `paperwiki` console-script; version bump in `pyproject.toml`,
  `__init__.py`, `plugin.json`; tag `v0.3.20`.

### Phase 9 — Release v0.3.21 (interpretive Score reasoning + recipe migration)

- [ ] **9.23 — Insightful Score reasoning (synthesized, not transcribed).**
  Plan §10.18 Task 9.23. Complexity **S**. Rewrite the digest SKILL
  Process Step 8 contract for the "Score reasoning" line: 1–2
  sentences of interpretation (NOT a paraphrase of the four
  sub-scores from the metadata callout). Forbid pure number-restating;
  require WHY interpretation, acknowledgement of limits ("rigor 0.50
  because brand-new"), and citation of specific evidence (topic
  match, recency, dataset release). Add Common Rationalizations
  rows: "I'll just list the sub-scores — it's accurate." (wrong) and
  "If the score is moderate, there's nothing interesting to say."
  (also wrong). Add Red Flag entry: "Score reasoning starts with
  the composite number and just restates the four sub-scores in
  parentheses → STOP." Add smoke test
  `test_digest_skill_score_reasoning_is_interpretive_not_transcriptive`.
  Pure SKILL prose change.
  **Acceptance check**: SKILL.md Process Step 8 mentions "interpret",
  "1–2 sentences", and the forbidden number-restating pattern;
  manual smoke confirms 3 different Score reasoning lines (high /
  medium / low score brackets) read as opinion-bearing
  interpretations, not paraphrases.
- [ ] **9.21 — Personal recipe migration after v0.3.17 keyword updates.**
  Plan §10.16 Task 9.21. Complexity **M**. Add new runner
  `paperwiki.runners.migrate_recipe` with CLI:
  `python -m paperwiki.runners.migrate_recipe <recipe-path>
  [--dry-run] [--target-version 0.3.17]`. Reads the recipe YAML,
  computes per-topic keyword diff against
  `paperwiki.config.recipe_migrations` canonical map, applies
  surgical updates after backing up to
  `<recipe-path>.bak.<YYYYMMDDHHMMSS>`. Preserves user-edited
  fields (`vault_path`, `api_key_env`, `auto_ingest_top`, custom
  5th topics, `top_k`). Idempotent. Emits JSON
  `{recipe_path, target_version, applied_changes:
  [{topic, removed_keywords, added_keywords}], backup_path}`. Add
  new SKILL `skills/migrate-recipe/SKILL.md` (six-section anatomy)
  + `.claude/commands/migrate-recipe.md`. Setup SKILL Branch 1 gains
  a stale-recipe heuristic check after "Keep current config" → asks
  via AskUserQuestion to migrate. Tests: unit tests for runner
  happy path / dry-run / idempotent re-run / custom 5th topic
  preservation / backup creation; smoke test for SKILL anatomy;
  smoke test asserting `0.3.17` target drops `foundation model`
  from `biomedical-pathology`.
  **Acceptance check**: running `migrate-recipe` on a stale recipe
  diffs the keyword changes, backs up the original, applies the
  diff in place; re-running emits `applied_changes: []` (idempotent);
  custom 5th topic and other user fields preserved; setup SKILL
  Branch 1 surfaces the migration prompt when the heuristic matches.
- [ ] **v0.3.21 Gate**: same as v0.3.13 gate; manual smoke (run
  `migrate-recipe` against the user's existing
  `~/.config/paper-wiki/recipes/daily.yaml` — observe diff applied,
  backup created, subsequent digest stops routing remote-sensing
  papers into `biomedical-pathology`); CHANGELOG `[0.3.21]` entry;
  version bump; tag `v0.3.21`.

### Phase 9 — Release v0.3.22 (cleanup: log levels + extract-images failure UX)

- [ ] **9.19 — Quiet `s2.parse.skip` warnings on sparse S2 records.**
  Plan §10.14 Task 9.19. Complexity **S**. In
  `src/paperwiki/plugins/sources/semantic_scholar.py::_parse_entry`,
  downgrade the four "sparse record" branches (lines 175, 180, 193,
  198) from `logger.warning` to `logger.debug`. Keep the
  `model validation` branch at line 219 at WARNING — that's a real
  schema mismatch. In `_parse_response` (or `fetch`), accumulate a
  per-reason histogram and emit one
  `logger.info("s2.parse.skipped_summary", count=N, by_reason={...})`
  line per fetch when `count > 0`. Add unit tests
  `test_semantic_scholar_skip_branches_log_at_debug_level` and
  `test_semantic_scholar_emits_skip_summary_at_info_level`.
  **Acceptance check**: fresh-vault `/paper-wiki:digest daily` shows
  zero `WARNING | s2.parse.skip` lines on stdout/stderr; with
  `--verbose`, per-entry DEBUG lines reappear plus the summary INFO
  line; structured-log key `s2.parse.skipped_summary` is filterable
  by power users.
- [ ] **9.20 — Surface `extract-images` failure details to the user.**
  Plan §10.15 Task 9.20. Complexity **S**. Extend
  `skills/digest/SKILL.md` Process Step 7a: ALWAYS emit a per-paper
  summary block in the SKILL's terminal output after the
  extract-images auto-chain, regardless of success / failure.
  Format names each paper with one of four classifications:
  success-with-figures / success-no-figures / network-fail /
  non-arxiv-skip. Add Common Rationalizations row: "I'll skip the
  summary if all extractions succeeded — it's noise." → "Wrong.
  Always emit the block." Add smoke test
  `test_digest_skill_emits_extract_images_summary` asserting the
  SKILL Process documents the four classifications and the
  per-paper format. Pure SKILL prose change; no Python edits.
  **Acceptance check**: SKILL.md Process Step 7a mentions all four
  classifications + the per-paper format; manual smoke with one
  known-404 arxiv id surfaces the failure reason in the SKILL
  terminal output, naming the paper.
- [ ] **v0.3.22 Gate**: same as v0.3.13 gate; manual smoke (fresh
  vault, run digest — confirm S2 WARNINGs are gone and
  extract-images per-paper summary block is emitted); CHANGELOG
  `[0.3.22]` entry; version bump; tag `v0.3.22`.

### Phase 9 — Final checklist

- [ ] All 9.x slice gates green (9.1-9.12 ✅; 9.13-9.24 pending).
- [ ] `pytest --cov=paperwiki --cov-report=term-missing` ≥ 90% overall.
- [ ] `mypy --strict src` clean.
- [ ] `ruff check src tests` clean.
- [ ] `ruff format --check src tests` clean.
- [ ] `claude plugin validate .` passes.
- [ ] CHANGELOG entries for `[0.3.13]` through `[0.3.22]` complete.
- [ ] Tag each release in turn: `v0.3.13` → `v0.3.22`.
- [ ] **Hard floor**: `tests/integration/test_full_digest_auto_chain.py`
  (Task 9.14) green at every commit on every branch.

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
  - `0.3.6` → `0.3.12` shipped ✅
  - `0.3.13` → `0.3.18` after Phase 9 (first round)
  - `0.3.19` → `0.3.22` after Phase 9 (this round, v0.3.18 smoke findings + evil-read-arxiv image-quality reference)
  - `0.5.0` after Phase 8 (when promoted from candidate)
- [ ] README, SPEC §3, recipes/README updated.
- [ ] Tag `v0.2.0` after Phase 6 ✅, `v0.3.0` after Phase 7 ✅,
  `v0.3.5` after README rewrite ✅, `v0.3.6` – `v0.3.12` shipped ✅,
  then `v0.3.13` – `v0.3.18` per Phase 9 (first round), then
  `v0.3.19` – `v0.3.22` per Phase 9 (this round), then `v0.5.0`
  after Phase 8 (if promoted).
