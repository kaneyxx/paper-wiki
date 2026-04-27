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

### Phase 9 — Final checklist

- [ ] All 9.x slice gates green (9.1-9.12 ✅; 9.13-9.18 pending).
- [ ] `pytest --cov=paperwiki --cov-report=term-missing` ≥ 90% overall.
- [ ] `mypy --strict src` clean.
- [ ] `ruff check src tests` clean.
- [ ] `ruff format --check src tests` clean.
- [ ] `claude plugin validate .` passes.
- [ ] CHANGELOG entries for `[0.3.13]` through `[0.3.18]` complete.
- [ ] Tag each release in turn: `v0.3.13` → `v0.3.18`.
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
  - `0.3.13` → `0.3.18` after Phase 9 (this round)
  - `0.5.0` after Phase 8 (when promoted from candidate)
- [ ] README, SPEC §3, recipes/README updated.
- [ ] Tag `v0.2.0` after Phase 6 ✅, `v0.3.0` after Phase 7 ✅,
  `v0.3.5` after README rewrite ✅, `v0.3.6` – `v0.3.12` shipped ✅,
  then `v0.3.13` – `v0.3.18` per Phase 9, then `v0.5.0` after
  Phase 8 (if promoted).
