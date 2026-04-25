# Phase 6 + Phase 7 Plan

**Date**: 2026-04-25
**Status**: Draft
**Companion files**: [`tasks/todo.md`](todo.md), [`.omc/plans/00-foundation-plan.md`](../.omc/plans/00-foundation-plan.md), [`SPEC.md`](../SPEC.md)

This plan supersedes the old, undersized "Phase 6 — Wiki backend" entry in
the foundation plan. It combines three threads:

1. **Wiki redesign** to match the Karpathy / kytmanov LLM-Wiki concept
   (Ingest / Query / Lint / Compile, two-tier `Sources` vs `Wiki` layout,
   per-page frontmatter status + confidence).
2. **Vault-layout cleanup** to drop the inherited `10_Daily / 20_Research`
   numeric prefixes — paper-wiki is a *plugin*, not a vault organizer,
   and should not impose Johnny.Decimal / PARA conventions on users.
3. **Paperclip integration** — wire the gxl.ai paperclip MCP + CLI in as
   an optional source for biomedical literature, opening up the medical
   research vertical without rewriting our pipeline.

---

## 1. Executive summary

### Phase 6 — Wiki Backend (revised)

Three vertical slices:

- **6.1 Vault-layout cleanup** *(touch existing reporters + recipes)*
  - Default `daily_subdir = "Daily"` (was `10_Daily`).
  - Default `papers_subdir = "Sources"` (new constant).
  - Default `wiki_subdir = "Wiki"` (new constant).
  - All paths configurable per recipe; numeric prefixes documented
    as opt-in for Johnny.Decimal users, not required.

- **6.2 Wiki backend implementation**
  - `MarkdownWikiBackend` (implements `WikiBackend` protocol).
  - Frontmatter convention for sources + concepts (status, confidence,
    sources, related_concepts).
  - 4 runners (file I/O only): `wiki_ingest_plan`, `wiki_query`,
    `wiki_lint`, `wiki_compile`.
  - 4 SKILLs that drive synthesis via Claude: `paperwiki:wiki-ingest`,
    `paperwiki:wiki-query`, `paperwiki:wiki-lint`, `paperwiki:wiki-compile`.
  - `index.md` + `_log.md` auto-maintenance.

- **6.3 Wiki / dedup integration**
  - `MarkdownVaultKeyLoader` reads concept frontmatter `sources:` field
    so concepts dedup against future digests.
  - `analyze` SKILL upgraded to write into `Sources/` and trigger
    `wiki-ingest` to keep concepts current.
  - `digest` reporter gains an optional wiki backend hook so daily
    runs can land top-K papers as `Wiki/sources/<id>.md`.

### Phase 7 — Paperclip integration

Three vertical slices:

- **7.1 Paperclip MCP wiring** *(zero Python code)*
  - Document `claude mcp add --transport http paperclip ...`
  - `paperwiki:setup` SKILL detects whether paperclip MCP is registered
    and offers to register it. Auth handled by `paperclip login`.

- **7.2 `PaperclipSource` source plugin**
  - Subprocess wrapper around the paperclip CLI (more portable than
    direct HTTP because the CLI handles auth/cache).
  - Returns canonical `Paper` objects via the existing source protocol.
  - Graceful degrade if paperclip is not installed.
  - Bundled recipe `recipes/biomedical-weekly.yaml`.

- **7.3 `paperwiki:bio-search` SKILL**
  - Interactive biomedical literature exploration via paperclip MCP.
  - Optionally upserts results into the wiki as new sources.

---

## 2. Why this matters

### Wiki redesign

Our original Phase 6 was just "MarkdownWikiBackend + query CLI". Reading
Karpathy's gist and kytmanov's reference impl shows the wiki concept is
*the* differentiating value of `paper-wiki` — not a nice-to-have. The
plugin's name is *paper-wiki*; we should ship the wiki story as a first-
class feature, not an afterthought.

The Karpathy three-operation pattern (Ingest / Query / Lint) maps cleanly
onto our SKILL + Python-runner split: runners do file I/O, Claude Code
does synthesis. We get the kytmanov experience without running a local
LLM.

### Vault-layout cleanup

The `10_Daily / 20_Research` prefixes were inherited from
`evil-read-arxiv`'s defaults. They are Johnny.Decimal / PARA conventions
that:

- Force ugly wikilinks (`[[20_Research/Papers/Foundation_Model]]`).
- Tax users who do not use that system.
- Add zero value to non-PARA users.

We are a plugin, not a vault organizer. Defaults should be friendly;
PARA stays opt-in.

### Paperclip integration

paperclip is purpose-built for AI agents querying biomedical literature
(8M+ papers across bioRxiv / PubMed Central / etc.). Two facts make it
a great fit:

1. **It already speaks MCP** (`claude mcp add ...`). We are a Claude Code
   plugin. Zero glue code required for SKILL access.
2. **Hybrid BM25 + embedding search** — gives us bio-domain coverage
   without us building/hosting an index. paperclip handles auth,
   storage, ranking; we orchestrate.

Risks (license / paid SaaS) are managed by treating paperclip as
**optional opt-in**, not a hard dependency.

---

## 3. Phase 6 — Wiki backend (revised)

### 6.1 Vault-layout cleanup

#### Acceptance criteria

- **AC-6.1.1** `ObsidianReporter.daily_subdir` defaults to `"Daily"`.
  Existing tests pass after fixture updates.
- **AC-6.1.2** New module-level constants
  `paperwiki.config.layout.{DAILY_SUBDIR, SOURCES_SUBDIR, WIKI_SUBDIR}`
  document the friendly defaults; reporters and runners reference them.
- **AC-6.1.3** Bundled recipes (`recipes/*.yaml`) use the new defaults
  in their commented examples; PARA users still see how to override.
- **AC-6.1.4** README + `docs/recipes.md` add a paragraph clarifying
  that any subdir is configurable; numeric prefixes are an opt-in
  Johnny.Decimal convention, not required.
- **AC-6.1.5** `.gitignore` adds `Wiki/.drafts/` (project-local default).

#### Verification

- `pytest -q` green after `daily_subdir` default change (existing
  ObsidianReporter tests will need fixture path updates).
- Manual: load each bundled recipe and confirm output paths use the
  friendly defaults unless overridden.

#### Implementation steps

1. Add `src/paperwiki/config/layout.py` with module-level constants.
2. Update `ObsidianReporter.__init__` default; reference the constant.
3. Update bundled recipes' inline comments to use new defaults.
4. Update `recipes/README.md`, top-level `README.md`, and SPEC §3 to
   reflect the new defaults.
5. Update existing tests (Obsidian reporter, integration end-to-end)
   for the new default path.

---

### 6.2 Wiki backend implementation

#### 6.2.1 Frontmatter convention

Two flavors of wiki page, both under `Wiki/`:

**`Wiki/sources/<canonical_id>.md`** — short summary of one paper, one
file per ingested source.

```yaml
title: "PRISM2: Unlocking Multi-Modal General Pathology AI"
canonical_id: "arxiv:2506.13063"
status: reviewed             # draft | reviewed | stale
confidence: 0.85             # 0.0 - 1.0
tags: [foundation-model, pathology]
related_concepts: ["[[Vision-Language Foundation Models]]"]
last_synthesized: 2026-04-25
```

**`Wiki/concepts/<concept-name>.md`** — synthesized topic article that
references multiple sources.

```yaml
title: "Vision-Language Foundation Models"
status: reviewed
confidence: 0.7
sources: ["arxiv:2506.13063", "arxiv:0001.0001"]
related_concepts: ["[[Multimodal Reasoning]]", "[[Foundation Models]]"]
last_synthesized: 2026-04-25
```

#### 6.2.2 `MarkdownWikiBackend`

Implements the `WikiBackend` protocol declared in
`paperwiki/core/protocols.py`. New file:
`src/paperwiki/plugins/backends/markdown_wiki.py`.

```python
class MarkdownWikiBackend:
    """Persists wiki sources + concepts as Markdown files."""

    def __init__(self, vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR): ...

    async def upsert_source(self, rec: Recommendation) -> Path: ...
    async def upsert_concept(
        self, name: str, body: str, *, sources: list[str],
        confidence: float, status: str = "draft",
    ) -> Path: ...
    async def query(self, q: str) -> list[Recommendation]: ...
    async def list_concepts(self) -> list[ConceptSummary]: ...
    async def list_sources(self) -> list[SourceSummary]: ...
```

Notes:

- `upsert_*` is idempotent: re-ingesting the same paper updates
  `last_synthesized` and `confidence` without duplicating the file.
- The backend never invents content — concept bodies come from the
  SKILL caller (Claude). It only writes well-formed Markdown.
- Concept names are normalized to filename-safe targets via the same
  `title_to_wikilink_target` helper used in `ObsidianReporter`.

#### 6.2.3 Four runners (file I/O only)

All runners satisfy SPEC §4: zero LLM calls.

| Runner | Job | Output |
|--------|-----|--------|
| `paperwiki.runners.wiki_ingest_plan` | Given a new source id, list affected concepts that should be re-synthesized. | JSON: `{source: ..., affected_concepts: [...], new_concepts_suggested: [...]}` |
| `paperwiki.runners.wiki_query` | Keyword search across `Wiki/concepts/*.md` and `Wiki/sources/*.md`. | JSON: `[{path, title, snippet, frontmatter}]` |
| `paperwiki.runners.wiki_lint` | Health checks (orphan pages, stale entries, oversized files, broken wikilinks, status mismatches). | JSON report |
| `paperwiki.runners.wiki_compile` | Regenerate `Wiki/index.md` and validate concept cross-links from frontmatter. | Side-effect: rewrites `index.md` |

#### 6.2.4 Four SKILLs (LLM does synthesis)

All follow the six-section anatomy.

| SKILL | Slash command | Workflow |
|-------|--------------|----------|
| `wiki-ingest` | `/paperwiki:wiki-ingest <source-id>` | Run ingest_plan, fetch source content from Sources, regenerate each affected concept article via Claude synthesis, write back through `MarkdownWikiBackend.upsert_concept`. |
| `wiki-query` | `/paperwiki:wiki-query <question>` | Run wiki_query, synthesize answer with citations to specific concept files, suggest follow-up queries. |
| `wiki-lint` | `/paperwiki:wiki-lint` | Run wiki_lint, surface findings, offer to fix orphans/stale items in batch. |
| `wiki-compile` | `/paperwiki:wiki-compile` | Run wiki_compile, then regenerate the natural-language summary at the top of `index.md` via Claude. |

#### 6.2.5 `index.md` shape

Auto-maintained file at `Wiki/index.md`:

```markdown
---
generated_by: "paper-wiki/<version>"
last_compiled: 2026-04-25
concepts: 8
sources: 23
---

# Wiki Index

_Auto-generated. Edit at your own risk; `/paperwiki:wiki-compile` overwrites this file._

## Concepts

- [[Vision-Language Foundation Models]] — 7 sources, confidence 0.85
- [[Multimodal Reasoning]] — 4 sources, confidence 0.7
- ...

## Sources

| Date | Title | Concepts |
| ---- | ----- | -------- |
| 2026-04-20 | [[arxiv-2506.13063]] | [[Vision-Language Foundation Models]] |
| ...
```

#### 6.2.6 `_log.md` shape

Append-only chronicle of operations; one line per op:

```markdown
- 2026-04-25T12:30:00Z `wiki-ingest` arxiv:2506.13063 → 2 concepts updated
- 2026-04-25T12:35:00Z `wiki-compile` 8 concepts, 23 sources
- 2026-04-25T13:01:00Z `wiki-lint` 1 stale, 0 orphans
```

#### Acceptance criteria

- **AC-6.2.1** `MarkdownWikiBackend` satisfies `WikiBackend` protocol;
  unit tests cover `upsert_source`, `upsert_concept`, idempotence,
  filename normalization, frontmatter round-trip.
- **AC-6.2.2** Four runners produce parseable JSON on stdout, exit 0
  on success, exit 1 on `UserError`.
- **AC-6.2.3** Four SKILLs follow the six-section anatomy and pass
  the existing parametrized smoke test.
- **AC-6.2.4** `wiki_lint` detects: orphan concept (no source
  references), stale entry (`last_synthesized` > 90 days old), oversized
  page (> 600 lines), broken wikilink (target doesn't exist or isn't a
  concept), status mismatch (frontmatter `status: reviewed` but
  confidence < 0.5).
- **AC-6.2.5** `wiki_compile` rewrites `index.md` deterministically:
  same vault state → same file bytes.
- **AC-6.2.6** `wiki_query` returns ≤ 10 hits ranked by simple BM25-ish
  score (term frequency × inverse document frequency on title +
  frontmatter tags). No embeddings.
- **AC-6.2.7** Integration test: end-to-end `wiki-ingest` of a stub
  source updates exactly one concept article + appends one `_log.md`
  line.
- **AC-6.2.8** Coverage ≥ 90% on new modules.

#### Verification

- `pytest -q` green; new tests in `tests/unit/plugins/backends/`,
  `tests/unit/runners/test_wiki_*.py`, `tests/integration/test_wiki_flow.py`.
- `claude plugin validate .` passes after new SKILLs land.
- Manual: run a synthetic ingest end-to-end, inspect `index.md`,
  `_log.md`, and a concept article for shape conformance.

---

### 6.3 Wiki / dedup integration

#### Acceptance criteria

- **AC-6.3.1** `MarkdownVaultKeyLoader` reads `sources:` from concept
  frontmatter and `canonical_id` from source frontmatter; concepts
  appear in dedup keys via every source they list.
- **AC-6.3.2** `analyze` SKILL writes to
  `{vault}/Sources/<canonical_id>.md` instead of
  `20_Research/Papers/<title>.md`.
- **AC-6.3.3** `analyze` SKILL ends with an explicit handoff to
  `wiki-ingest` so the wiki stays current.
- **AC-6.3.4** `digest` reporter gains optional `wiki_backend: true`
  flag in recipe; when set, the digest writes a copy of each top-K
  paper as a `Wiki/sources/` file.
- **AC-6.3.5** `wiki_lint` recognizes papers that are in `Sources/`
  but not referenced by any concept ("dangling sources") and offers
  to ingest them.

#### Verification

- Existing dedup tests still pass with the new layout.
- New integration test: run a digest with `wiki_backend: true`, then
  run `wiki_lint`, assert dangling-sources count matches digest size.

---

## 4. Phase 7 — Paperclip integration

### 7.1 Paperclip MCP wiring

#### Acceptance criteria

- **AC-7.1.1** `setup` SKILL detects via
  `claude mcp list` whether `paperclip` is registered.
- **AC-7.1.2** If not registered, the SKILL offers the registration
  command without auto-running it (auth is sensitive; user opts in).
- **AC-7.1.3** `docs/paperclip-setup.md` documents:
  registration, `paperclip login`, free vs paid tier (link to
  paperclip docs; we don't duplicate their pricing terms).
- **AC-7.1.4** Adding paperclip is **never required** for paper-wiki
  to function; all SKILLs short-circuit gracefully when paperclip is
  absent.

#### Verification

- Manual: register paperclip in a clean Claude Code instance, verify
  SKILL detection.
- `tests/unit/runners/test_diagnostics.py` extended to expose a
  `mcp_servers` list; integration test asserts `paperclip` shows up
  when registered.

---

### 7.2 `PaperclipSource` source plugin

#### Design

Subprocess-based wrapper around the paperclip CLI:

```python
class PaperclipSource:
    name = "paperclip"

    def __init__(
        self,
        query: str,
        *,
        limit: int = 20,
        sources: list[str] | None = None,  # ["biorxiv", "pmc"]
        paperclip_bin: str = "paperclip",
        timeout_seconds: float = 60.0,
    ): ...

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        # asyncio.create_subprocess_exec("paperclip", "search", ...)
        # parse JSON stdout, map each result to Paper(canonical_id="paperclip:<id>", ...)
```

#### Acceptance criteria

- **AC-7.2.1** Plugin satisfies `Source` protocol.
- **AC-7.2.2** Maps paperclip identifiers to a new canonical namespace:
  `paperclip:bio_<id>` for bioRxiv hits, `paperclip:pmc_<id>` for
  PubMed Central. Where paperclip exposes the original arXiv id,
  prefer `arxiv:<id>` so dedup converges with `ArxivSource`.
- **AC-7.2.3** If `paperclip` binary is missing, raise
  `IntegrationError` with "paperclip not installed; see
  docs/paperclip-setup.md".
- **AC-7.2.4** If `paperclip search` exits non-zero, surface stderr
  in the `IntegrationError` message.
- **AC-7.2.5** Unit tests use `monkeypatch` on
  `asyncio.create_subprocess_exec` with a synthetic JSON response
  fixture; no real network in CI.
- **AC-7.2.6** New recipe `recipes/biomedical-weekly.yaml` demonstrates
  the source.

#### Verification

- `pytest tests/unit/plugins/sources/test_paperclip.py` green.
- Manual: paid paperclip user runs the recipe, confirms papers land
  in their digest.

---

### 7.3 `paperwiki:bio-search` SKILL

#### Design

A SKILL that walks Claude through interactive bio-paper exploration via
the paperclip MCP tools (`search`, `grep`, `map`, `from`). Optionally
hands results to `wiki-ingest` to file them in the wiki.

#### Acceptance criteria

- **AC-7.3.1** SKILL frontmatter mentions paperclip MCP triggers
  ("biomedical paper", "search bioRxiv", "PubMed search").
- **AC-7.3.2** SKILL fails gracefully with an actionable error when
  paperclip MCP is not registered.
- **AC-7.3.3** Six-section anatomy passes the parametrized smoke test.
- **AC-7.3.4** Slash command `/paperwiki:bio-search` lives in
  `.claude/commands/bio-search.md`.

#### Verification

- `pytest tests/test_smoke.py` parametrized SKILL tests pass for the
  new `bio-search` SKILL.
- `claude plugin validate .` passes.
- Manual: paid paperclip user invokes the SKILL, runs through a
  multi-step exploration, confirms results land in `Wiki/sources/`
  when the user opts to ingest.

---

## 5. Cross-cutting concerns

### 5.1 Documentation updates

- `README.md` Quick Start section gains: install, setup, `digest`,
  `wiki-query`, `bio-search` (optional).
- `docs/wiki.md` (new) explains the Ingest / Query / Lint / Compile
  loop, with diagrams.
- `docs/paperclip-setup.md` (new).
- `SPEC.md` §3 layout updated with new default subdirs, §4 manifests
  unchanged, §6 boundaries unchanged.
- `CHANGELOG.md` entries for every commit per Conventional Commits.

### 5.2 Backwards compatibility

- The default subdir change (`10_Daily` → `Daily`) is a breaking change
  for anyone who already pointed at the old layout. Phase 6.1 lands as
  v0.2.0 with a migration note in CHANGELOG.
- `MarkdownVaultKeyLoader` continues to work with existing vaults
  because it scans recursively and reads frontmatter — no path
  hard-coding.

### 5.3 Testing strategy

- All new file I/O uses `tmp_path`.
- All new HTTP / subprocess uses mocks.
- New SKILLs honor the parametrized frontmatter / anatomy tests.
- Integration tests sit under `tests/integration/`:
  - `test_wiki_flow.py` — full ingest → query → lint cycle on a
    synthetic vault.
  - `test_paperclip_source.py` — subprocess-mocked end-to-end.

### 5.4 Sequencing

Phase 6 lands first because:

- `analyze` SKILL (Phase 5 stub) needs the wiki backend to be useful.
- `digest`'s wiki integration depends on the backend.
- Paperclip is a *source* (Phase 2 layer); shipping it before the
  wiki backend means bio papers land in the same dead-end the analyze
  SKILL had — no wiki to file them in.

Within Phase 6: 6.1 → 6.2 → 6.3. Within Phase 7: 7.1 → 7.2 → 7.3.

---

## 6. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Vault layout change breaks existing users | Confused users on update | v0.2.0 release, CHANGELOG migration note, CLI flag `--legacy-layout` if needed |
| Wiki frontmatter convention drifts from kytmanov | Lost interoperability with that ecosystem | Keep the field names (`status`, `confidence`, `sources`) identical; document in `docs/wiki.md` |
| `wiki_lint` produces too many false positives | User stops trusting the SKILL | Severity levels (info / warn / error); only show `error` by default |
| Paperclip becomes paid-only / shuts down | Plugin user-facing failure | Optional opt-in; never a hard dep; diagnostics SKILL surfaces absence cleanly |
| Paperclip MCP API changes | `bio-search` SKILL breaks | SKILL invokes via MCP tool names which paperclip controls; pin the SKILL to a version comment, watch upstream |
| `wiki_compile` rewrites `index.md` aggressively, clobbers user edits | Lost manual edits | Strong "do not edit" warning at the top + frontmatter `generated_by`; document `_log.md` as the audit trail |
| Wiki concept name collisions across capitalization | Two notes for the same concept | Normalize concept names via lowercased title key in `WikiBackend.upsert_concept` |
| LLM-driven wiki-ingest regenerates a concept the user just hand-edited | Their edits get overwritten | Honor `status: reviewed` — Claude SKILL must read frontmatter and skip / merge instead of overwriting; surface conflicts |
| Phase 6 scope sprawl | Phase 6 never lands | 6.1 / 6.2 / 6.3 as independent commits, each shippable on its own |

---

## 7. Verification gates between phases

After each numbered slice:

- All existing tests still pass.
- New tests cover the slice's acceptance criteria.
- `ruff check`, `ruff format --check`, `mypy --strict` green.
- `claude plugin validate .` green.
- Coverage stays ≥ 90% overall.
- README + SPEC + CHANGELOG updated.
- Conventional Commits used; one commit per logical slice (smaller
  is fine; bigger is not).

---

## 8. Out of scope (for Phases 6–7)

- Multi-user / team wikis.
- Vector / embedding search inside the wiki (Karpathy's whole point is
  that we do not need this at ~100-source scale).
- Replacing paperclip with our own bioRxiv index.
- Full citation graph (cite -> cited) — concept ↔ source links are
  enough for v0.x.
- ~~LLM-generated PDF parsing~~ — promoted into **Phase 8 candidate**
  below. Still LLM-free on the Python side (extraction only); Claude
  Code does any synthesis on top of the extracted text.

---

## 9. Phase 8 — PDF download + text extraction (candidate)

**Status**: Draft, tentative. Targets v0.4.0 after Phase 7 ships v0.3.0.
Promote to active once paperclip lands and we have empirical signal on
how often the abstract-only flow leaves users wanting deeper analysis.

### 9.0 Why this matters

`v0.2.0` ships `Wiki/sources/<id>.md` files whose body is just
`title + authors + landing_url + abstract`. The `analyze` SKILL inherits
the same limitation: deep-analysis prose is grounded in the abstract,
not the paper. For pathology / VLM / agents work where the meat is in
methods and ablations, abstracts are not enough.

The fix is to give SKILLs *eyes on the PDF* without asking Python to do
LLM work. Python:

1. Downloads the PDF (idempotently, with backoff).
2. Extracts plain text via `pypdf`.
3. Writes the text to a sibling cache file.

Claude Code SKILLs:

1. Read the cached text instead of the abstract when present.
2. Write deeper, citation-grounded prose into `Sources/` and concept
   articles.

This stays inside SPEC §6 boundaries (no LLM in Python).

### 9.1 Architectural decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cache location | `{vault}/Wiki/.cache/pdfs/<canonical>.pdf` and<br>`{vault}/Wiki/.cache/text/<canonical>.txt` | Project-local, gitignored (already), scoped to one vault. |
| PDF library | `pypdf>=4.0` | Pure-Python, BSD-3, no native deps. Good enough for arXiv text. Can swap to `pdfplumber` later if needed. |
| Trigger model | **Lazy / opt-in** — fetched only when SKILL or runner requests | Don't blow disk on every digest; respect user agency. |
| Concurrency | Single fetch at a time per SKILL invocation; rate-limit 1/sec for arXiv | Polite citizen of upstream services. |
| Failure handling | PDF unavailable / parse fails → frontmatter `pdf_cached: false`, fall back to abstract; SKILL caps `confidence` at 0.4 | Don't break the wiki when a PDF 404s. |
| Frontmatter contract | `Wiki/sources/<id>.md` frontmatter gains `pdf_cached: bool` and `text_chars: int \| null` | Other runners/SKILLs know whether full text is available without re-fetching. |
| Test fixture | Commit a tiny pre-baked `tests/fixtures/sample.pdf` (~2 KB) | Avoids a heavy `reportlab` dev dependency. |
| GC | `paperwiki.runners.gc_pdf_cache` LRU by mtime, configurable `--max-files` (default 50) and `--max-mb` (default 500) | Bounded disk usage; opt-in cleanup. |

### 9.2 Vertical slices

#### 9.2.1 PDF fetch + text-extract foundation *(no user-visible change yet)*

- **8.1.1** Add `src/paperwiki/_internal/pdf.py`:
  - `async def fetch_pdf(url: str, dest: Path, *, http_client: AsyncClient) -> Path`
    — idempotent (skip if `dest.exists()` and non-empty); honors a 1/sec
    rate-limit token bucket; surfaces HTTP errors as
    `IntegrationError`.
- **8.1.2** Add `extract_text(pdf_path: Path) -> str` using `pypdf`.
  Returns the concatenation of every page's text, with `\f` form feeds
  between pages so SKILLs can split on page breaks if useful.
- **8.1.3** Pin `pypdf>=4.0` in `pyproject.toml`. Commit a 2 KB
  `tests/fixtures/sample.pdf`. Add `Wiki/.cache/` to `.gitignore`.

##### Acceptance
- **AC-8.1.1** `fetch_pdf` happy-path test passes; idempotent re-run
  performs zero HTTP calls.
- **AC-8.1.2** `extract_text(tests/fixtures/sample.pdf)` returns a
  deterministic non-empty string covering both pages.
- **AC-8.1.3** `pypdf` is the only new runtime dep; total install
  size delta < 1 MB.

#### 9.2.2 `paperwiki.runners.fetch_pdf` runner

- **8.2.1** Add the runner. CLI:
  ```
  python -m paperwiki.runners.fetch_pdf <vault> <canonical-id>
       [--force] [--no-text]
  ```
  Reads `Wiki/sources/<id>.md` frontmatter to find `pdf_url`. Downloads
  via `_internal.pdf.fetch_pdf`. Extracts via `extract_text`. Updates
  frontmatter with `pdf_cached: true` and `text_chars: <n>`. Emits JSON
  `{pdf_path, text_path, char_count, status, cached}` on stdout.
- **8.2.2** Tests cover: happy path, source file missing, `pdf_url`
  missing in frontmatter, HTTP 404, malformed PDF, idempotent re-run
  (skip if `pdf_cached` is already true unless `--force`).
- **8.2.3** Update `MarkdownWikiBackend.upsert_paper` to include
  `pdf_url` in frontmatter when `paper.pdf_url` is set; this is a
  pre-req for the runner to find it.

##### Acceptance
- **AC-8.2.1** Runner exits 0 on success, 3 (`IntegrationError`) on
  HTTP failure, 2 (`UserError`) on missing source file or missing
  `pdf_url`.
- **AC-8.2.2** Re-running on a cached source is a no-op (zero HTTP,
  zero re-extract) unless `--force` is passed.

#### 9.2.3 Frontmatter markers + `wiki_lint` cache exclusion

- **8.3.1** `MarkdownWikiBackend.list_sources` reads the new
  `pdf_cached` and `text_chars` fields into `SourceSummary`. Defaults
  remain false / null when absent so legacy files still parse.
- **8.3.2** `wiki_lint` ignores files under `Wiki/.cache/`: never count
  cache files toward `BROKEN_LINK` resolution, never glob into them
  during `OVERSIZED` checks. New test pins this so a future refactor
  can't break it silently.

##### Acceptance
- **AC-8.3.1** `SourceSummary` exposes `pdf_cached: bool` and
  `text_chars: int | None`.
- **AC-8.3.2** A vault with a 50 MB cached text file under
  `Wiki/.cache/text/` produces zero `OVERSIZED` findings.

#### 9.2.4 `analyze` SKILL grounded in cached PDF text

- **8.4.1** Update `skills/analyze/SKILL.md` Step 3:
  > Invoke `paperwiki.runners.fetch_pdf <canonical-id>` before writing
  > the analysis. If the JSON returns `text_chars >= 1000`, ground the
  > six sections in that text. Otherwise fall back to the abstract and
  > cap `confidence` at `0.4` so `wiki_lint` flags
  > `STATUS_MISMATCH` if the user marks it `reviewed` prematurely.
- **8.4.2** Smoke test asserts the SKILL references both
  `fetch_pdf` and the confidence cap.

##### Acceptance
- **AC-8.4.1** SKILL smoke test green.
- **AC-8.4.2** Manual: running `/paperwiki:analyze arxiv:2506.13063`
  produces a note that quotes from the *body* of the paper, not just
  the abstract. (Manual because the LLM half is human-judged.)

#### 9.2.5 `/paperwiki:fetch-pdf` batch SKILL

- **8.5.1** Add `skills/fetch-pdf/SKILL.md` (six-section anatomy) +
  `.claude/commands/fetch-pdf.md`. Workflow:
  1. Walk `Wiki/sources/*.md`; collect ids whose `pdf_cached` is false.
  2. If > 10 pending, ask user to confirm before fetching.
  3. Loop over ids, invoking `paperwiki.runners.fetch_pdf` per id;
     log failures but continue.
  4. Summarize: N succeeded, M failed (with reasons), total MB cached.
- **8.5.2** Parametrized smoke test passes for the new SKILL.

##### Acceptance
- **AC-8.5.1** Slash command lands; SKILL frontmatter and anatomy
  pass smoke tests.
- **AC-8.5.2** SKILL stops gracefully (non-zero summary, exit 0) when
  the runner reports `IntegrationError` for individual ids; never
  aborts the whole batch on a single 404.

#### 9.2.6 Cache lifecycle / GC

- **8.6.1** Add `paperwiki.runners.gc_pdf_cache`:
  ```
  python -m paperwiki.runners.gc_pdf_cache <vault>
       [--max-files N=50] [--max-mb M=500] [--dry-run]
  ```
  LRU by mtime. Always preserves entries whose source's
  `last_synthesized` is within the last 30 days. Emits JSON
  `{deleted: [...], kept: int, freed_mb: float}`.
- **AC-8.6.1** Test covers trim by count, trim by size, dry-run mode,
  preservation of recently synthesized entries.

#### 9.2.7 Wiki-backend integration polish

- **8.7.1** When `ObsidianReporter.wiki_backend=True`, append a single
  hint line to each source's body:
  ```
  > _Full text not yet fetched. Run `/paperwiki:fetch-pdf
  > <canonical-id>` to deepen this entry._
  ```
  Removed automatically the next time the source is upserted with
  `pdf_cached: true`.

#### Gate (Phase 8)
- All 8.x slice tests green.
- New tests bring coverage of `_internal/pdf.py` and the new runners
  to ≥ 90%.
- `mypy --strict`, `ruff`, `claude plugin validate .` all green.
- `CHANGELOG.md` cuts `[0.4.0]`. Version bump in `pyproject.toml`,
  `__init__.py`, `plugin.json`. Tag `v0.4.0`.

### 9.3 Risks (Phase 8)

| Risk | Impact | Mitigation |
|------|--------|------------|
| Bulk PDF fetch hits arXiv rate-limit and 429s | Users see errors mid-batch | 1/sec token bucket per process; surface 429 with retry-after suggestion. |
| pypdf misreads math-heavy LaTeX-rendered PDFs | Garbled text feeds Claude | Text extract is best-effort; SKILL caps `confidence` at 0.4 when extraction is suspicious (e.g., `text_chars / page_count < 200`). |
| Cache balloons to many GB | User disk pressure | `gc_pdf_cache` runner; documented default `--max-mb 500`. |
| Users commit `Wiki/.cache/` accidentally | PR bloat / leaked PDFs | `Wiki/.cache/` already in `.gitignore`; SPEC §3 mentions it. |
| pypdf license / supply-chain risk | New runtime dep | BSD-3, widely audited; pin a version range, not `*`. |

### 9.4 Out of scope (Phase 8)

- OCR for scanned-image PDFs.
- Figure / table extraction.
- Citation graph extraction from PDF body.
- Image extraction (paperclip / `paper-analyze` covers this in their
  own ecosystems).

---

## Appendix A — Karpathy / kytmanov references

- **Concept**: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- **Reference impl**: https://github.com/kytmanov/obsidian-llm-wiki-local
- **Differences from kytmanov**:
  - We do **not** use SQLite; markdown frontmatter + git history serve
    the same role.
  - We do **not** ship a multi-LLM provider abstraction; Claude Code
    is the only LLM surface (per SPEC §6 boundaries).
  - We do **not** run a watcher daemon; SKILLs are user-triggered.
  - We **do** adopt the `raw/wiki/` two-tier split (named `Sources/`
    and `Wiki/` here for clarity) and the frontmatter convention
    (`status`, `confidence`).

## Appendix B — Paperclip references

- **Blog**: https://gxl.ai/blog/paperclip
- **Install**: `curl -fsSL https://paperclip.gxl.ai/install.sh | bash`
- **MCP**: `claude mcp add --transport http paperclip https://paperclip.gxl.ai/mcp`
- **Stance**: optional opt-in; never a hard dependency.
