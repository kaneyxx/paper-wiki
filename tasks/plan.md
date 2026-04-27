# Phase 6 + Phase 7 Plan

**Date**: 2026-04-25 (original) · 2026-04-27 (Phase 9 added)
**Status**: Phases 6.x + 7.x shipped (v0.3.5). Phase 8 candidate. Phase 9 active.
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

> **2026-04-27 update.** Phase 9 (digest quality) appended at the bottom.
> Sections 1–8 unchanged from the v0.3.5 snapshot.

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
| `wiki-ingest` | `/paper-wiki:wiki-ingest <source-id>` | Run ingest_plan, fetch source content from Sources, regenerate each affected concept article via Claude synthesis, write back through `MarkdownWikiBackend.upsert_concept`. |
| `wiki-query` | `/paper-wiki:wiki-query <question>` | Run wiki_query, synthesize answer with citations to specific concept files, suggest follow-up queries. |
| `wiki-lint` | `/paper-wiki:wiki-lint` | Run wiki_lint, surface findings, offer to fix orphans/stale items in batch. |
| `wiki-compile` | `/paper-wiki:wiki-compile` | Run wiki_compile, then regenerate the natural-language summary at the top of `index.md` via Claude. |

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

_Auto-generated. Edit at your own risk; `/paper-wiki:wiki-compile` overwrites this file._

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
- **AC-7.3.4** Slash command `/paper-wiki:bio-search` lives in
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
- **AC-8.4.2** Manual: running `/paper-wiki:analyze arxiv:2506.13063`
  produces a note that quotes from the *body* of the paper, not just
  the abstract. (Manual because the LLM half is human-judged.)

#### 9.2.5 `/paper-wiki:fetch-pdf` batch SKILL

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
  > _Full text not yet fetched. Run `/paper-wiki:fetch-pdf
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

## 10. Phase 9 — Digest quality (active, targets v0.3.6 → v0.3.8)

**Status**: Active. Targets a chain of three small releases that fix the
quality regressions a user just observed in `digest daily` against a
fresh vault on 2026-04-27.

### 10.0 Problem statement

The user ran `/paper-wiki:digest daily` and got an output digest at
`~/Documents/Paper-Wiki/Daily/2026-04-27-paper-digest.md` with four
distinct quality bugs. Each is rooted in a **placeholder pointing at a
SKILL the user has to manually invoke** — but the SKILL is the thing
that already invoked the runner, so nothing ever fills the placeholder.

#### 10.0.1 Bug list (with evidence)

1. **"Today's Overview" callout is a static placeholder, with the wrong
   namespace.** `src/paperwiki/plugins/reporters/obsidian.py:91-98`:

   ```python
   def _render_overview_callout() -> str:
       """Top-of-digest synthesis placeholder (Claude side fills it in)."""
       return (
           "> [!summary] Today's Overview\n"
           "> _Run `/paperwiki:digest` SKILL after this runner to fill in the\n"
           "> cross-paper synthesis here — overall trends, quality distribution,\n"
           "> research hotspots, suggested reading order._\n"
       )
   ```
   — stale `/paperwiki:` namespace and a self-referential instruction
   ("run the SKILL after this runner" — but the SKILL *is* the caller).
   The SKILL Process never goes back to fill it in, so every digest has
   a permanent stub at the top.

2. **Per-paper "Detailed report" is also a stub pointing at
   `/paperwiki:analyze`** (`obsidian.py:175-180`):
   ```python
   detailed = (
       "### Detailed report\n\n"
       f"_Run `/paperwiki:analyze {canonical_id}` for a six-section deep-dive "
       f"in ``Sources/``, or click [[{source_filename}]] to jump to the "
       "wiki source stub (which holds figures, abstract, and your notes)._"
   )
   ```
   Same architecture failure: the user has to invoke another SKILL per
   paper to actually get a richer summary. Same `/paperwiki:` namespace
   bug.

3. **Inline figure teaser never fires.** `_try_inline_teaser`
   (`obsidian.py:193-211`) probes `<vault>/Wiki/sources/<id>/images/` for
   pre-extracted figures, but the digest runner never calls
   `extract_paper_images`. The directory is empty on a fresh vault, so
   every digest has zero images.

4. **Stale `/paperwiki:` namespace is not just in the reporter — it's
   spread across SKILLs, runners, recipes, docs, and even tests.**
   `grep` (excluding worktrees) finds **128 occurrences across 34
   files**. Top offenders:
   - `skills/bio-search/SKILL.md` (12)
   - `SPEC.md` (11)
   - `skills/extract-images/SKILL.md` (8)
   - `skills/digest/SKILL.md` (7)
   - `skills/analyze/SKILL.md` (7)
   - `skills/migrate-sources/SKILL.md` (6)
   - …plus `markdown_wiki.py` (3, in source-stub body), `obsidian.py` (4),
     `runners/wiki_lint.py` (1), `runners/diagnostics.py` (1),
     `recipes/*.yaml` (4 total), `docs/*.md` (8 total), `.claude/commands/*.md` (8 total).

   Tests already pin the README contract (`tests/test_smoke.py:400-409`),
   but there's no invariant test pinning the rest of the bundled assets.
   The README test passes today only because someone fixed README in
   v0.3.5 by hand.

   The stale namespace not only confuses the user (they may try to type
   `/paperwiki:` and get nothing); it *also* corrupts every source stub
   that `MarkdownWikiBackend._default_source_body` writes
   (`markdown_wiki.py:313, 319`), and every `wiki_lint` finding text
   (`wiki_lint.py:120`).

#### 10.0.2 Architecture context

paper-wiki has a clean SPEC §6 split:

- **Python is LLM-free** — pure deterministic Source → Filter → Scorer →
  Reporter pipeline.
- **Claude (via SKILLs) does synthesis** — post-processing on top of the
  deterministic output.

So fixes fall into four orthogonal levers:

- **(A) Extend the digest SKILL Process** to do a "fill placeholders"
  LLM-synthesis pass *after* the runner finishes. SPEC-blessed; this is
  exactly the boundary the SPEC §6 split exists for.
- **(B) Have the runner emit cleaner skeletons** (just the section
  headings) so the SKILL fills empty slots rather than overwriting
  filler prose. Cleaner separation; avoids "is this the runner's stub or
  Claude's prose" confusion in source diffs.
- **(C) Auto-extract images** for the auto-ingest-top papers, so
  `_try_inline_teaser` actually has something to inline.
- **(D) Mechanical namespace fix** for the stale `/paperwiki:` strings.

### 10.1 Architecture decision (combination of A + B + C + D)

We adopt **all four levers**, sliced so each ships one user-visible
improvement end-to-end. Rationale per lever:

- **(A) is non-negotiable.** Without it, the user keeps getting
  permanent placeholders. SPEC §6 says synthesis lives in SKILLs, so
  this is the right place.
- **(B) reduces LLM token cost** for (A). If the runner emits a clean
  empty `### Detailed report` heading instead of a multi-line
  placeholder, the SKILL's "fill placeholders" pass has less to undo
  and the diff is auditable. (B) is small and lands first.
- **(C) is a one-line addition** to the digest SKILL Process: chain
  `extract-images` for the auto-ingest-top papers. The runner already
  exists (`extract_paper_images`); we just need the SKILL to call it.
- **(D) is mechanical** but blocks (A) credibility: if the digest
  SKILL's synthesized prose says "Run `/paper-wiki:analyze`" but the
  underlying SKILL.md says `/paperwiki:`, the user will doubt either.
  Land (D) first as a "boring infrastructure release" (v0.3.6) so the
  rest of the work sits on a clean namespace baseline.

The combined plan ships across **3 successive minor releases**:

- **v0.3.6 — Namespace + skeleton cleanup.** Slices D + B (deterministic,
  low-risk, high-leverage; lands together because they touch similar
  files).
- **v0.3.7 — Today's Overview synthesis.** Slice A1 (the cross-paper
  synthesis pass — one LLM call per digest).
- **v0.3.8 — Per-paper Detailed report + auto images.** Slices A2 + C
  (per-paper synthesis pass — N LLM calls per digest, where N = top_k;
  plus auto image extraction for auto_ingest_top papers).

Reason for the split: A2 is the only slice with materially new LLM
cost. Shipping A1 alone first lets the user feel the win from one
synthesis pass before we add per-paper passes; if they hate the new
behavior we can adjust the contract before A2.

### 10.2 Vertical task slicing

Six tasks across two phases. Each ships an independently testable
improvement.

#### Task 9.1 — Mechanical namespace fix (D) → v0.3.6

**Scope**: replace every `/paperwiki:` with `/paper-wiki:` across
SKILLs, runners, recipes, docs, slash commands, and source-stub
bodies. Test files keep one literal `/paperwiki:` reference inside the
new invariant test (10.6).

**Files** (34 outside `.claude/worktrees/`):

- `src/paperwiki/plugins/reporters/obsidian.py` — 4 hits (overview
  callout + detailed-report stub).
- `src/paperwiki/plugins/backends/markdown_wiki.py` — 3 hits (source
  stub body for Key Takeaways + Figures hints).
- `src/paperwiki/runners/wiki_lint.py` — 1 hit (finding message text).
- `src/paperwiki/runners/diagnostics.py` — 1 hit.
- `src/paperwiki/runners/extract_paper_images.py` — 2 hits (docstring).
- `src/paperwiki/runners/wiki_compile.py` — 1 hit.
- `src/paperwiki/config/recipe.py` — 1 hit (comment).
- `skills/*/SKILL.md` — 11 SKILLs, 53 hits combined.
- `.claude/commands/*.md` — 4 slash commands, 8 hits.
- `recipes/*.yaml` — 2 recipes, 4 hits.
- `docs/wiki.md` (5 hits), `docs/paperclip-setup.md` (3 hits).
- `SPEC.md` (11 hits — including command-table rows).
- `CHANGELOG.md` (3 hits in older entries — leave intact, they describe
  history; only fix forward).
- `tasks/plan.md` + `tasks/todo.md` (rebuild the references when this
  plan itself is rewritten — already done in this rewrite).
- `tests/test_smoke.py`, `tests/unit/plugins/{reporters,backends}/*`,
  `tests/unit/runners/*`, `tests/integration/test_digest_wiki_handoff.py`
  — 14 hits combined. Most are assertion strings of the form
  `assert "/paperwiki:wiki-ingest" in body`; flip to `/paper-wiki:`.

**Acceptance criteria**:

- **AC-9.1.1** Zero `/paperwiki:\w+` matches under `src/`, `skills/`,
  `recipes/`, `docs/`, `SPEC.md`, `.claude/commands/`. `CHANGELOG.md`
  is exempt for its existing historical entries.
- **AC-9.1.2** Existing tests still green after the rewrite (asserting
  the new namespace).
- **AC-9.1.3** New invariant test (`test_no_stale_paperwiki_namespace`,
  see 10.6) pinning the contract.

**Verification**:

- `pytest -q tests/test_smoke.py::test_no_stale_paperwiki_namespace`
  green (after the new test is added).
- `pytest -q` overall green.
- Manual: `grep -rn '/paperwiki:' src skills recipes docs SPEC.md
  .claude/commands` returns zero hits.
- `claude plugin validate .` green.

**Complexity**: M (large diff, but mechanical — `sed -i` on a curated
file list, then run tests).

**Dependencies**: none (foundation work; everything else builds on
the clean namespace).

**Risk**: low. Rollback = `git revert`. Mitigation = ship the new
invariant test in the same commit so any future regression fails CI
before merge.

---

#### Task 9.2 — Runner emits clean skeletons (B) → v0.3.6

**Scope**: replace the prose placeholders in
`obsidian.py::_render_overview_callout` and
`obsidian.py::_render_recommendation` with **clean, signaled skeleton
markers** that downstream Claude code can target deterministically:

- "Today's Overview" callout becomes a single `> [!summary] Today's
  Overview` heading + an HTML comment marker
  `<!-- paper-wiki:overview-slot -->` inside an empty body. No prose.
  Reason: a non-prose marker is unambiguous; the SKILL fills the slot
  by replacing the marker without any "is this old prose or not"
  fuzzy match.
- "Detailed report" subsection becomes a single `### Detailed report`
  heading + an HTML comment marker
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->`. Same reason.

**Acceptance criteria**:

- **AC-9.2.1** `render_obsidian_digest` output contains exactly
  `<!-- paper-wiki:overview-slot -->` once per digest (or zero times
  when `recommendations` is empty).
- **AC-9.2.2** Output contains
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->` exactly once per
  recommendation.
- **AC-9.2.3** Existing test
  `test_today_overview_placeholder_at_top` (`tests/unit/plugins/reporters/test_obsidian.py:135-145`)
  is updated to assert on the new marker shape; the heading
  `Today's Overview` still exists, the prose stub is gone.
- **AC-9.2.4** Existing test
  `test_per_paper_has_detailed_report_wikilink`
  (same file, line 168-172) is updated: assert on
  `### Detailed report` and the per-paper slot marker; the
  `/paper-wiki:analyze` fallback in the assertion is removed.
- **AC-9.2.5** A new test
  `test_skeleton_markers_are_machine_targetable` asserts the marker
  shapes are consistent and findable by a regex like
  `^<!-- paper-wiki:[\w-]+(:.*)? -->$`.

**Verification**:

- `pytest -q tests/unit/plugins/reporters/test_obsidian.py` green.
- Manual: render a digest with 3 recommendations; confirm 1 overview
  marker + 3 per-paper markers, no prose stubs.

**Complexity**: S (≤30 LoC change in the reporter, ~3 test edits, 1
new test).

**Dependencies**: prefers Task 9.1 to land first so the new comment
strings don't need a follow-up rewrite.

**Risk**: medium-low. Existing user vaults that have OLD digests with
the prose stub keep them — we don't rewrite history. New digests get
the new shape.
Rollback = revert the reporter change; the SKILL slot-fill code (Task
9.3+) gracefully falls back to "no synthesis if no marker found".

---

#### Task 9.3 — Today's Overview synthesis pass in digest SKILL (A1) → v0.3.7

**Scope**: extend `skills/digest/SKILL.md` Process with a new step that
runs *after* the runner returns and *before* the optional auto-ingest
chain. The new step:

1. Read the freshly-written digest file from disk.
2. If it contains `<!-- paper-wiki:overview-slot -->`, synthesize a
   cross-paper overview from the recipe's `top_k` recommendations.
   The synthesis covers:
   - Topic clustering ("3 papers on VLA models, 2 on diffusion").
   - Quality distribution (avg composite score, range, outliers).
   - Research-hotspot signal (which matched topics dominate).
   - Suggested reading order (by composite score, optionally tweaked
     for "novel-first" vs "high-impact-first" recipes).
3. Replace the marker (and the empty body of the
   `> [!summary] Today's Overview` callout) with the synthesized prose.
4. Save the file back.

**Constraints**:

- The SKILL must read the recommendations from the same in-memory
  result the runner emitted (via reading the file or, simpler, via
  the runner stdout structured-log line `digest.complete`). The
  current runner already logs `recommendations=N` and `counters=...`;
  if more detail is needed, extend the log line to JSON the top-K
  papers — but **don't add a second runner**. SPEC §6 keeps Python
  deterministic.
- Synthesized overview MUST cite paper indices (`#1`, `#2`, …) so the
  user can scroll back to verify. Never invent numbers.
- Synthesized overview is bounded: ≤ 200 words, no per-paper bullets
  (those live in the per-paper sections).
- If the digest has 0 or 1 recommendations, replace the marker with a
  one-liner ("No recommendations matched today" / "Single match;
  see #1 below") instead of a faux-overview.

**Acceptance criteria**:

- **AC-9.3.1** `skills/digest/SKILL.md` Process gains an explicit step
  ("step 7: synthesize Today's Overview") between the existing summary
  step and the auto-ingest-top step.
- **AC-9.3.2** SKILL Verification section adds: "Today's Overview
  callout has prose, not the slot marker, and cites paper indices that
  exist in the same file".
- **AC-9.3.3** New parametrized smoke test asserts the SKILL.md
  contains both `paper-wiki:overview-slot` (the marker name) and
  "Today's Overview" so future refactors can't drop the contract
  silently.
- **AC-9.3.4** Manual: run the `daily` recipe end-to-end on a fresh
  vault; the resulting file's `> [!summary] Today's Overview` callout
  has 60-200 words of synthesized prose with at least one `#N`
  reference matching an actual entry below. (Manual because LLM output
  is human-judged.)

**Verification**:

- `pytest -q tests/test_smoke.py::test_digest_skill_describes_overview_synthesis`
  green.
- Manual smoke: as above.

**Complexity**: M (SKILL prose is ~30-50 lines new content; one new
smoke test; runner stdout schema may need a small extension to expose
recommendations to the SKILL).

**Dependencies**:
- Hard: Task 9.2 (the marker exists).
- Soft: Task 9.1 (so the SKILL Process doesn't itself contain stale
  `/paperwiki:` references).

**Risk**: medium. LLM output quality is variable; if Claude generates
an overview that contradicts the per-paper entries, the user loses
trust in both. Mitigation: SKILL Common Rationalizations table
explicitly lists "I'll guess at trend names without rereading the
abstracts" as a wrong answer; SKILL Verification step requires the
overview to cite `#N` indices (cheap correctness check).
Rollback: revert the SKILL.md change. Runner output stays usable; the
slot marker just stays in the file as an orphan comment, harmless.

---

#### Task 9.4 — Per-paper Detailed report synthesis (A2) → v0.3.8

**Scope**: extend the digest SKILL Process again to fill each
per-paper `<!-- paper-wiki:per-paper-slot:{canonical_id} -->` marker
with a richer summary than the abstract:

- 2-3 sentence "Why this matters" framing.
- 2-4 bullet "Key takeaways" (concrete claims from the abstract; never
  invented).
- 1-line "Score reasoning" plain-English explanation of the composite
  score breakdown ("Scores high because relevance is 0.92 — multiple
  exact topic matches, modest novelty 0.55").

**Constraints**:

- Each per-paper section gets ONE LLM call. For `top_k=10`, that's 10
  calls per digest. The SKILL should batch these (one prompt, 10
  outputs) when feasible to amortize cost.
- The SKILL **must not** invent claims that aren't in the abstract.
  Common Rationalizations table calls this out explicitly.
- "Detailed report" stays distinct from "Abstract" (which the runner
  still inlines verbatim above). It's a synthesized layer, not a
  rewrite.

**Acceptance criteria**:

- **AC-9.4.1** SKILL.md Process step 7 (or 8, after the overview pass)
  adds: "fill each per-paper slot marker with synthesized Detailed
  report".
- **AC-9.4.2** SKILL Common Rationalizations table adds a row about
  inventing per-paper claims.
- **AC-9.4.3** New smoke test pins the contract: SKILL.md mentions
  both `paper-wiki:per-paper-slot` and "Detailed report" and bans
  the historical `/paper-wiki:analyze`-as-fallback prose.
- **AC-9.4.4** Manual: run the recipe; each `### Detailed report`
  subsection has 3-6 lines of synthesized prose with no `<!-- -->`
  marker remaining.

**Verification**:

- `pytest -q tests/test_smoke.py::test_digest_skill_describes_per_paper_synthesis`
  green.
- Manual smoke: as above.

**Complexity**: M-L (per-paper synthesis is the heaviest LLM step;
SKILL prose grows; the bracketing of cost via batching needs to be
spelled out).

**Dependencies**:
- Hard: Task 9.2 (the per-paper marker exists).
- Soft: Task 9.3 (sequenced after the overview pass for a coherent
  digest-fill order).

**Risk**: medium-high. This is the slice with the largest LLM-cost
delta. Mitigation: SKILL Common Rationalizations covers cost ("I'll
just send 10 separate prompts" / "I'll skip top_k=10 and only do
top 3" — both wrong); SKILL Process step says batched-prompt is the
default and per-paper-prompt is the fallback when batching exceeds
the context window.
Rollback: revert SKILL.md. Slot markers stay; harmless.

---

#### Task 9.5 — Auto image extraction for auto_ingest_top papers (C) → v0.3.8

**Scope**: extend the digest SKILL Process to chain
`/paper-wiki:extract-images <canonical-id>` for each paper in
`min(auto_ingest_top, top_k)` *before* the wiki-ingest chain. This
makes `_try_inline_teaser` actually work — the digest gets real
inline figures for the auto-ingested top papers.

**Constraints**:

- Only run for `arxiv:` canonical ids. Surface a one-liner skip
  reason for `paperclip:` / `s2:` ids.
- Continue on failure (a 404 source tarball is not a digest failure).
- Cache hits are normal — no warning when the runner reports
  `cached=true`.
- The chain order is: **extract-images first, wiki-ingest second**.
  Extract-images runs before wiki-ingest so the figures are present
  when `_try_inline_teaser` is later invoked on the next digest run.
  (The current digest never re-renders, so the figures appear *next*
  digest; the user sees the win on day 2. That's fine; we'll document
  it.)

**Acceptance criteria**:

- **AC-9.5.1** `skills/digest/SKILL.md` step "Auto-chain wiki-ingest"
  becomes "Auto-chain extract-images + wiki-ingest" with the new
  ordering.
- **AC-9.5.2** SKILL Common Rationalizations adds: "Skipping image
  extraction because Obsidian renders without it" — wrong, the user
  wants figures.
- **AC-9.5.3** Smoke test asserts the SKILL mentions both
  `extract-images` AND `wiki-ingest` in the right order in the
  Process section.
- **AC-9.5.4** Manual: run the recipe with `auto_ingest_top=3` on a
  fresh vault; confirm `Wiki/sources/<id>/images/` is populated for
  the top-3 papers; confirm the **next** digest run has inline
  `![[...|700]]` teasers in those 3 entries.

**Verification**:

- `pytest -q tests/test_smoke.py::test_digest_skill_chains_extract_images`
  green.
- Manual smoke: as above.

**Complexity**: S (SKILL prose change only; runner already exists).

**Dependencies**:
- Hard: Task 9.1 (the SKILL Process must reference
  `/paper-wiki:extract-images`, not the stale namespace).

**Risk**: low. arXiv source tarballs are rate-limited but the runner
already handles that (cache + 1/sec budget). Rollback = revert
SKILL.md.

**Note**: this slice uses ONLY the existing extract-images runner +
SKILL — no new Python code. The SKILL prose is the entire deliverable.

---

#### Task 9.6 — Invariant test for stale namespace (D-companion) → v0.3.6

**Scope**: add a new test in `tests/test_smoke.py` named
`test_no_stale_paperwiki_namespace` that pins zero `/paperwiki:\w+`
matches across the bundle. Mirrors the existing
`test_readme_uses_correct_slash_command_namespace` (test_smoke.py:400)
but expanded to cover SKILLs, runners, recipes, docs, SPEC, and slash
commands.

**Acceptance criteria**:

- **AC-9.6.1** Test scans these roots: `src/`, `skills/`, `recipes/`,
  `docs/`, `.claude/commands/`, plus the top-level `SPEC.md`. Skips
  `tests/`, `CHANGELOG.md`, `.claude/worktrees/`, and `tasks/` (the
  last because plan files rewrite the namespace as part of editing
  history).
- **AC-9.6.2** Test fails with a list of files + line numbers when
  any `/paperwiki:` literal is found (so the failure message points
  at exactly what to fix).
- **AC-9.6.3** Test passes after Task 9.1 lands.

**Verification**:

- `pytest -q tests/test_smoke.py::test_no_stale_paperwiki_namespace`
  green after Task 9.1 lands; red before.

**Complexity**: S (one ~30 LoC test).

**Dependencies**:
- Hard: Task 9.1 (the test would fail today; we add it in the same
  commit as the rewrite so CI stays green).

**Risk**: very low. Rollback = delete the test.

---

#### Task 9.7 — Auto-ingest bootstrap on fresh vault → v0.3.7

**Problem (discovered during 9.0 recon, after the v0.3.5 digest run)**:
When a user runs `/paper-wiki:digest daily` against a vault with no
`Wiki/concepts/` articles yet (fresh setup, or first-ever digest), the
`auto_ingest_top` chain hits a dead-end. `wiki-ingest` returns
`affected_concepts: []` for every paper because no concept article
exists to update, and the SKILL refuses to silently create new ones
(design decision: new concepts require user confirmation). Net effect:
every fresh-vault digest stops auto-ingest after paper #1 with
"stopped — wiki_ingest_plan returned affected_concepts: []".

This is a hard UX gate: the demo flow (install → setup → digest →
auto-ingest fills the wiki) breaks at step 3.

**Solution**: Extend the `wiki-ingest` SKILL with an `--auto-bootstrap`
invocation mode. In this mode:

- Missing concept articles named in the `suggested_new_concepts` list
  are auto-stubbed before the update loop: frontmatter (`name`, `tags`,
  `created`, `auto_created: true`) plus a one-line sentinel body —
  `_Auto-created during digest auto-ingest. Lint with /paper-wiki:wiki-lint
  to flag for review._`.
- After stubbing, the normal wiki-ingest update loop runs, finds the
  newly-stubbed concept, and folds the source citation in.
- A summary line is emitted: `"created N stubs, updated M concepts"`.

The digest SKILL Process step 7 (auto-chain wiki-ingest) is updated to
pass `--auto-bootstrap` for every chained call. Manual
`/paper-wiki:wiki-ingest <id>` invocations stay non-bootstrap — the
existing safeguard remains for interactive use.

**Acceptance criteria**:

- **AC-9.7.1** `skills/wiki-ingest/SKILL.md` documents the
  `--auto-bootstrap` flag, when to use it, the auto-stub frontmatter
  shape, and the sentinel body template.
- **AC-9.7.2** `skills/digest/SKILL.md` Process step 7 passes
  `--auto-bootstrap` for all auto-chained `wiki-ingest` invocations.
- **AC-9.7.3** Smoke test
  `test_wiki_ingest_skill_describes_auto_bootstrap_mode` asserts the
  flag, sentinel body, `auto_created: true` frontmatter, and "stub
  then update" two-step are documented.
- **AC-9.7.4** Smoke test
  `test_digest_skill_passes_auto_bootstrap_to_wiki_ingest` asserts the
  flag appears in the digest SKILL auto-chain step.
- **AC-9.7.5** Manual smoke: `rm -rf <vault>/Wiki`, run digest with
  `auto_ingest_top: 3`, observe 3 new concept stubs created and 3
  source-to-concept citations populated, no manual confirmation
  prompts.
- **AC-9.7.6** wiki-lint flags concept articles with
  `auto_created: true` as "needs human review" rather than as broken
  orphans.

**Verification**:

- `pytest tests/test_smoke.py -k bootstrap` green.
- Manual smoke as above.
- `/paper-wiki:wiki-lint` after the smoke surfaces the auto-created
  stubs in a dedicated "needs review" section.

**Complexity**: S-M (~30 min). Two SKILL.md edits, two smoke tests, and
a small wiki-lint adjustment to recognise the `auto_created` flag.

**Dependencies**:

- Hard: Task 9.1 (namespace fix) — keeps `/paper-wiki:wiki-ingest`
  references consistent across the new doc.
- Soft: independent of 9.2 / 9.3 (different files).

**Risk**: medium. Auto-stubs could pollute the vault with empty
articles if a user explores topics they later abandon. Mitigation: the
`auto_created: true` frontmatter + sentinel body string make stubs
machine-detectable; wiki-lint surfaces them in a dedicated bucket the
user can prune en masse.

---

#### Task 9.8 — Standard upgrade flow (OMC-style) → v0.3.8

**Problem (discovered during v0.3.5–0.3.7 upgrade cycle)**:
paper-wiki's `.claude-plugin/plugin.json` was missing the `"skills":
"./skills/"` declaration that Claude Code uses to locate SKILL files at
install time. Without it, `/plugin install` could leave the cache
populated but the plugin metadata unable to resolve SKILL paths —
producing the "already installed globally" + "Unknown command" failure
mode that appeared repeatedly during 0.3.5–0.3.7 upgrades. The
workaround was manual `rm -rf ~/.claude/plugins/cache/paper-wiki/` plus
JSON editing — fragile and undiscoverable.

OMC's `plugin.json` carries the declaration:

```json
"skills": "./skills/"
```

paper-wiki must do the same.

**Solution**:

1. Add `"skills": "./skills/"` to `.claude-plugin/plugin.json`. This
   tells the Claude Code plugin loader where SKILLs live, making
   `/plugin install` and `/plugin uninstall` + reinstall fully
   idempotent.
2. Rewrite the README upgrade section to document the **standard**
   flow: `/plugin uninstall paper-wiki@paper-wiki` +
   `/plugin install paper-wiki@paper-wiki` + fresh `claude` session.
   Remove all language that instructs users to manually `rm -rf` cache
   or edit JSON files (those were workarounds for the missing
   declaration).
3. Add three contract tests that pin the new shape so future
   refactors cannot drop the declaration or regress the upgrade docs.

**Acceptance criteria**:

- **AC-9.8.1** `.claude-plugin/plugin.json` has a `"skills"` field
  whose value is `"./skills/"` (or starts with `./skills`).
- **AC-9.8.2** README contains the literal commands
  `/plugin uninstall paper-wiki@paper-wiki` and
  `/plugin install paper-wiki@paper-wiki` and the warning about
  `claude -c` for post-upgrade sessions.
- **AC-9.8.3** README does NOT contain `rm -rf` paired with
  `cache/paper-wiki` as a normal upgrade step (manual JSON editing may
  appear as a last-resort fallback note, but not in the primary flow).
- **AC-9.8.4** `test_plugin_manifest_declares_skills_directory` green.
- **AC-9.8.5** `test_readme_documents_standard_upgrade_flow` green.
- **AC-9.8.6** `test_readme_does_not_recommend_manual_cache_nuke` green.
- **AC-9.8.7** Full test suite passes (`pytest -x -q`); `ruff check`
  and `mypy --strict` clean.

**Verification**:

- `pytest tests/test_smoke.py -k "upgrade or skills_directory or
  cache_nuke"` green.
- After v0.3.8 publishes to GitHub:
  `/plugin uninstall paper-wiki@paper-wiki` →
  `/plugin install paper-wiki@paper-wiki` →
  fully exit + `claude` (no `-c`) →
  `/paper-wiki:setup` resolves. No manual JSON editing required.

**Complexity**: S (~15 min). One-line JSON fix + README prose +
3 smoke tests. No Python source changes.

**Dependencies**:
- None. Independent of 9.1–9.7; can ship standalone as v0.3.8.

**Risk**: very low. The JSON fix is a one-field addition; rollback =
remove the field. README change is documentation-only. Tests are
read-only assertions.

**Note**: tasks 9.4 (per-paper synthesis) and 9.5 (auto image
extraction), originally planned for v0.3.8, are deferred to v0.3.10 so
v0.3.8 stays small and focused on the upgrade-UX fix.

---

#### Task 9.9 — Concept matching threshold + recipe tightening → v0.3.11

**Problem (discovered during 2026-04-27 v0.3.7+0.3.8 smoke run)**:
The `biomedical-pathology` concept article ended up listing all three
top recommendations as sources during the auto-ingest chain — but those
top three were `OccDirector` (autonomous driving), `PokeVLA` (robot
manipulation), and `ChangeQuery` (remote sensing). None are biomedical.

Two layers of root cause:

1. **Recipe template too generic**: `skills/setup/SKILL.md:180-182`
   maps the "Biomedical & Pathology" theme to keywords that include
   `foundation model`. Any "foundation model" paper in cs.CV / cs.LG
   trips a match for the biomedical topic. The keyword list also
   includes the duplicate pair `WSI` / `whole-slide image` /
   `whole slide image`, which is fine, but the bare `foundation model`
   token is the offender. (`foundation model` is also listed under
   "Vision & Multimodal" — it's the generic-AI overlap that pollutes
   the biomedical bucket.)

2. **Filter does not gate by per-topic strength**: `CompositeScorer.
   _compute_relevance` (`src/paperwiki/plugins/scorers/composite.py:145-169`)
   returns a SINGLE aggregate `relevance` score across all topics plus
   a `matched_topics: list[str]` of every topic that hit at least one
   keyword or category. A paper that hits `foundation model` once gets
   added to `matched_topics` for the biomedical-pathology topic with no
   per-topic score attached. Downstream, `MarkdownWikiBackend.
   upsert_source` (`markdown_wiki.py:110`) writes those topic names
   into `related_concepts`, and the wiki-ingest auto-bootstrap chain
   stubs / updates concept articles based on `related_concepts` —
   ferrying the weakly-matched paper into the biomedical-pathology
   concept on the strength of one generic keyword.

The `Recommendation` model has `matched_topics: list[str]` and
`score: ScoreBreakdown` but no per-topic breakdown. We need to add a
per-topic strength signal and gate by it.

**Solution** (two layers, ship together):

- **Recipe-level**: tighten the setup SKILL's keyword template for
  "Biomedical & Pathology". Drop `foundation model` (too generic);
  collapse the WSI duplicates; bias toward biomedical-specific terms
  (`pathology`, `histopathology`, `WSI`, `clinical AI`,
  `digital pathology`, `medical imaging`, plus the existing
  `q-bio.QM` / `eess.IV` categories which carry the bio signal). Add
  a Common Rationalizations row in `setup/SKILL.md` calling out
  "generic AI keywords leak into specialized concept buckets" so
  future template edits stay sane. Note that we cannot rewrite users'
  existing personal recipes silently; document the reassessment
  prompt in setup's Branch 2 (Edit one piece → Topics) and surface a
  one-time warning when a personal recipe still contains the legacy
  generic-keyword list.

- **Filter-level**: extend `CompositeScorer._compute_relevance` to
  return a per-topic strength dict (e.g. `{"vision-multimodal": 0.85,
  "biomedical-pathology": 0.18}`) and stash it on
  `Recommendation.score_breakdown.notes` (existing field) using the
  key `topic_strengths`. Then update `MarkdownWikiBackend.
  upsert_source` to filter `matched_topics` → `related_concepts` by a
  configurable threshold (default 0.30) before writing the source's
  `related_concepts` frontmatter. Configurable via the `obsidian`
  reporter config: `wiki_topic_strength_threshold: 0.3` so power
  users can tune. Below threshold, the topic stays in
  `matched_topics` (still informational on the digest's per-paper
  callout) but is dropped from the source frontmatter that drives
  auto-ingest.

This puts the gate at the source→concept mapping (option 2 of the
three layers in the brief), which is the right boundary: scoring stays
in the scorer; auto-ingest behavior stays controllable per reporter.
Layer 1 (filter-side topic drop) would lose useful info for the
digest's per-paper "matched: [vision-language, biomedical-pathology]"
callout. Layer 3 (wiki-ingest SKILL recipient-side) would mean the
SKILL has to re-derive per-topic strength from text, which is a
re-implementation of the scorer in prose.

**Acceptance criteria**:

- **AC-9.9.1** `ScoreBreakdown.notes` populated with key
  `topic_strengths` mapping each topic name to a float in `[0, 1]`
  whenever the composite scorer ran. Per-topic strength uses the
  same saturating curve as the aggregate relevance, but evaluated on
  a single topic's hits (so a topic with 0 keyword hits + 0 category
  match has strength `0.0`).
- **AC-9.9.2** `MarkdownWikiBackend.upsert_source` accepts a
  `topic_strength_threshold: float = 0.3` keyword argument and
  filters `related_concepts` accordingly. When the recommendation
  has no `topic_strengths` populated (legacy data), behave as today
  (no gating).
- **AC-9.9.3** `ObsidianReporter` plumbs a `wiki_topic_strength_threshold`
  recipe-config field (default 0.3) into `upsert_source`.
- **AC-9.9.4** `skills/setup/SKILL.md` Q2 keyword table updated:
  "Biomedical & Pathology" keyword list drops `foundation model`,
  consolidates the WSI variants, adds biomedical-leaning terms.
  Common Rationalizations gains a row about generic-keyword leakage.
- **AC-9.9.5** Smoke tests:
  - `test_composite_scorer_emits_per_topic_strengths` — scorer returns
    a `topic_strengths` notes entry covering every configured topic.
  - `test_wiki_upsert_source_filters_by_topic_strength` — given a
    recommendation with `topic_strengths={"a": 0.9, "b": 0.15}` and
    threshold `0.3`, the source frontmatter's `related_concepts`
    contains `a` only.
  - `test_setup_skill_biomedical_keywords_exclude_generic_terms` —
    asserts the bundled-template biomedical-pathology keyword list
    does NOT contain `foundation model`.
- **AC-9.9.6** Existing tests continue to pass (the new threshold
  defaults are non-breaking when `topic_strengths` is absent).

**Verification**:

- `pytest -q tests/unit/plugins/scorers/test_composite.py
  tests/unit/plugins/backends/test_markdown_wiki.py
  tests/test_smoke.py -k "topic_strength or biomedical_keywords"`
  green.
- Manual: rebuild the user's personal recipe via `/paper-wiki:setup`
  Branch 2 → Topics → Biomedical & Pathology; verify the keyword
  list no longer contains `foundation model`. Run
  `/paper-wiki:digest daily`; confirm an `OccDirector`-style
  autonomous-driving paper does NOT land in the
  `biomedical-pathology` concept's `sources:` list.

**Complexity**: M (45-75 min). Scorer change + new
`ScoreBreakdown.notes` key + reporter plumbing + SKILL prose +
3 smoke tests.

**Dependencies**:
- Soft: Task 9.10 (the auto-bootstrap runner) ideally lands first so
  the new threshold gates the runner's stub creation; but if 9.10
  ships standalone, 9.9 still works against the SKILL's manual
  stub-write fallback.
- Independent of 9.11 / 9.12.

**Risk**: medium. Default threshold `0.3` is a guess; too high drops
legitimate matches, too low fails to stop pollution. Mitigation:
ship behind the configurable reporter field; add a Common
Rationalizations note that the right number is "tune by inspecting
2–3 days of digest output, then lock it". Document in CHANGELOG.

---

#### Task 9.10 — Implement `--auto-bootstrap` properly in the runner → v0.3.9

**Problem (discovered during 2026-04-27 v0.3.7+0.3.8 smoke run)**:
Task 9.7 added `--auto-bootstrap` mode to `skills/wiki-ingest/SKILL.md`
(documentation) and to `skills/digest/SKILL.md` (auto-chain step), and
two smoke tests assert the flag is mentioned in both SKILLs:

- `tests/test_smoke.py:608` —
  `test_wiki_ingest_skill_describes_auto_bootstrap_mode`
- `tests/test_smoke.py:635` —
  `test_digest_skill_passes_auto_bootstrap_to_wiki_ingest`

But `grep -rn '\-\-auto-bootstrap' src/` returns **zero** hits. The
underlying runner `paperwiki.runners.wiki_ingest_plan` does NOT accept
`--auto-bootstrap`. During the smoke run, the SKILL fell back to
inline-Python `asyncio.run` + direct `MarkdownWikiBackend.upsert_concept`
calls (the SKILL Process Step says "Walk `suggested_new_concepts`; for
each that has no existing concept article, write a stub …" — Claude
implements that with whatever ad-hoc tool it can reach). The smoke run
hit two `ImportError` dead-ends mid-attempt because the SKILL's
fallback path is fragile and bypasses the runner architecture per
SPEC §6.

This is a **partial-implementation bug** carried from v0.3.7, not a
new feature. Closing it lands in v0.3.9 alongside everything else.

**Solution**: extend the existing `wiki_ingest_plan` runner with a
`--auto-bootstrap` flag (option 1 of the brief — more contained than
adding a separate `bootstrap_concepts.py` runner, and the planner
already has the `MarkdownWikiBackend` instance + `suggested_concepts`
list).

When `--auto-bootstrap` is set:

1. After computing `IngestPlan`, if `source_exists` is `true`, walk
   `suggested_concepts` and create a stub for each one that does not
   yet exist on disk. Stub frontmatter:
   ```yaml
   ---
   name: <concept-name>
   tags: [auto-created]
   created: <YYYY-MM-DD>
   auto_created: true
   ---
   ```
   Stub body (the new sentinel from Task 9.12):
   ```
   _Auto-created during digest auto-ingest._

   _Run `/paper-wiki:wiki-ingest <source-id>` on a relevant paper to
   fold its content into this concept._
   ```
2. Move each stubbed concept name from `suggested_concepts` into
   `affected_concepts` so the SKILL's downstream update loop will
   fold the source citation in (no separate code path needed).
3. Add a `created_stubs: list[str]` field to the JSON output so the
   SKILL can surface "created N stubs, updated M concepts" in its
   summary line.

The runner stays LLM-free (file I/O only, per SPEC §6). The SKILL's
"auto-bootstrap" Process section becomes a thin pass-through:
"invoke the runner with `--auto-bootstrap`; surface its
`created_stubs` count to the user". The fragile inline-Python
fallback is removed.

**Acceptance criteria**:

- **AC-9.10.1** `paperwiki.runners.wiki_ingest_plan` accepts a
  `--auto-bootstrap` (boolean flag) Typer option.
- **AC-9.10.2** When the flag is set and `source_exists` is `true`,
  the runner creates stub files at
  `<vault>/Wiki/concepts/<filename>.md` for every entry in
  `suggested_concepts` that does not already exist. Stubs use the
  frontmatter and body shape specified above. Filename normalization
  goes through the same `MarkdownWikiBackend` helpers (no
  duplication).
- **AC-9.10.3** Stubbed concept names are moved from
  `suggested_concepts` into `affected_concepts` in the JSON output.
  The new `created_stubs: list[str]` field carries the same names
  for explicit reporting.
- **AC-9.10.4** When the flag is set and `source_exists` is `false`,
  the runner does NOT create stubs (still emits an empty
  `affected_concepts` and a clear error). Stubs are bound to a real
  source.
- **AC-9.10.5** When the flag is unset, behavior is unchanged
  (backwards-compatible with v0.3.7).
- **AC-9.10.6** `skills/wiki-ingest/SKILL.md` "Auto-bootstrap mode"
  Process simplifies to: "invoke
  `paperwiki.runners.wiki_ingest_plan <vault> <id> --auto-bootstrap`;
  read `created_stubs` from the JSON; the normal update loop now
  finds the new stubs and folds the source in." The
  `MarkdownWikiBackend.upsert_concept` direct-call language goes
  away. Common Rationalizations gains a row: "I can write the stub
  files directly via Python — saves a runner call." (Wrong: SPEC §6
  keeps file I/O in runners; SKILL stays Claude-side orchestration.)
- **AC-9.10.7** Tests:
  - `tests/unit/runners/test_wiki_ingest_plan.py` gains
    `test_auto_bootstrap_creates_stubs_for_suggested_concepts`,
    `test_auto_bootstrap_skips_existing_concepts` (idempotent),
    `test_auto_bootstrap_no_op_when_source_missing`,
    `test_auto_bootstrap_unset_preserves_legacy_behavior`.
  - The existing `test_wiki_ingest_skill_describes_auto_bootstrap_mode`
    smoke test (test_smoke.py:612) is updated: it now asserts the
    SKILL mentions invoking the **runner** with `--auto-bootstrap`,
    not direct `upsert_concept` calls.

**Verification**:

- `pytest -q tests/unit/runners/test_wiki_ingest_plan.py
  tests/test_smoke.py -k auto_bootstrap` green.
- Manual: `rm -rf <vault>/Wiki && /paper-wiki:digest daily` with
  `auto_ingest_top: 3`. Confirm the wiki-ingest auto-chain runs the
  runner with `--auto-bootstrap`, creates stubs, and the SKILL prints
  "created N stubs, updated M concepts" with no inline `asyncio.run`
  fallback.

**Complexity**: M (60-90 min). Runner: ~30 LoC + 4 unit tests.
SKILL prose: ~10 line trim. One smoke test update.

**Dependencies**:
- Hard: Task 9.7 (the SKILL contract that the flag exists). 9.7
  shipped in v0.3.7; 9.10 closes its runner-side gap.
- Soft: Task 9.12 (sentinel body update). If 9.12 ships in the same
  release, the runner uses the new sentinel from day one; if not,
  the runner uses today's sentinel and 9.12 updates it later.

**Risk**: low-medium. Risk is mostly schema drift — if the JSON
output gains `created_stubs` and a downstream SKILL doesn't read it,
nothing breaks (silent degrade). Rollback = revert the runner +
SKILL change; SKILL falls back to inline-Python again (today's
behavior).

---

#### Task 9.11 — Quiet `dedup.vault.missing` warnings on absent paths → v0.3.11

**Problem (discovered during 2026-04-27 v0.3.7+0.3.8 smoke run)**:
On a fresh-vault first run, the user sees three identical warnings:

```
WARNING  | paperwiki.plugins.filters.dedup:load:160 - dedup.vault.missing
WARNING  | paperwiki.plugins.filters.dedup:load:160 - dedup.vault.missing
WARNING  | paperwiki.plugins.filters.dedup:load:160 - dedup.vault.missing
```

These come from `MarkdownVaultKeyLoader.load`
(`src/paperwiki/plugins/filters/dedup.py:158-161`):

```python
async def load(self, ctx: RunContext) -> DedupKeys:
    if not self.root.exists() or not self.root.is_dir():
        logger.warning("dedup.vault.missing", path=str(self.root))
        return DedupKeys.empty()
```

The user's personal recipe configures three `vault_paths`
(`<vault>/Daily`, `<vault>/Sources`, `<vault>/Wiki/sources`,
`<vault>/Wiki/concepts`); on a first-ever run none exist yet. The
function-level behavior is correct (an empty vault has nothing to
dedup against), but `WARNING` is the wrong severity for the expected
first-run state. The user reasonably wonders whether something is
broken.

**Solution**: downgrade the absent-path branch to `INFO`. Keep
`WARNING` for actual `OSError`s (line 170 — those are real read
failures). Update the message slightly to make the empty-vault
intent obvious.

```python
# Before:
logger.warning("dedup.vault.missing", path=str(self.root))
# After:
logger.info(
    "dedup.vault.absent",
    path=str(self.root),
    note="vault path not yet created; dedup uses empty key set",
)
```

The event name change (`missing` → `absent`) is intentional: it
distinguishes "path doesn't exist yet" (info) from "path was
expected but disappeared" (which would be the warning case if we
ever add one).

**Acceptance criteria**:

- **AC-9.11.1** `dedup.py:160` uses `logger.info(...)` not
  `logger.warning(...)` when the vault root does not exist.
- **AC-9.11.2** The `OSError` branch at line 170
  (`dedup.vault.read_error`) stays at `logger.warning` — that's a
  real failure.
- **AC-9.11.3** Test
  `test_dedup_loader_logs_info_when_vault_path_absent` (new)
  asserts the level. Use loguru's testing utilities (or
  `caplog` if loguru is configured to propagate to the std logging
  handler in tests) to capture and inspect.
- **AC-9.11.4** Existing tests continue to pass — none assert on
  the warning level explicitly today (verified by grep), so this
  is a pure level downgrade with no contract break.

**Verification**:

- `pytest -q tests/unit/plugins/filters/test_dedup.py -k absent`
  green.
- Manual: on a fresh vault, `/paper-wiki:digest daily` no longer
  surfaces `WARNING` for missing vault paths. The structured log
  still records the event at INFO so observability isn't lost.

**Complexity**: S (15-20 min). 1 line change + 1 test.

**Dependencies**: none. Independent of every other Phase 9 task.

**Risk**: very low. Pure log-level change. Rollback = revert. No
behavioral change for filters or dedup keys.

---

#### Task 9.12 — Auto-stub UX (sentinel body + wiki-lint message) → v0.3.11

**Problem (discovered during 2026-04-27 v0.3.7+0.3.8 smoke run)**:
After Task 9.7 / 9.10 land, auto-bootstrap creates concept stubs
whose entire body is:

```
_Auto-created during digest auto-ingest. Lint with /paper-wiki:wiki-lint to flag for review._
```

When the user later runs `/paper-wiki:wiki-lint`, they see "Needs
review (auto-created stubs): N concepts" — but opening any concept
file shows nothing to review yet. The intended path is "user runs
`/paper-wiki:wiki-ingest <id>` manually to fold real content in",
but neither the sentinel nor the wiki-lint message makes this
obvious.

**Solution** (SKILL prose only, no Python):

1. Update the sentinel body in `skills/wiki-ingest/SKILL.md` (and in
   the new runner from Task 9.10) to explicitly tell the user the
   next step:
   ```
   _Auto-created during digest auto-ingest._

   _This stub has no synthesized content yet. To fold a relevant
   paper into this concept, run `/paper-wiki:wiki-ingest <source-id>`
   on a paper from the digest. To prune unwanted stubs in batch, see
   `/paper-wiki:wiki-lint`._
   ```
2. Update `skills/wiki-lint/SKILL.md` Process Step 2 (the
   "Surface auto-created stubs first" section) to clarify intent:
   ```
   "Auto-created stubs are intentionally empty until you run
   /paper-wiki:wiki-ingest on a relevant paper. Stubs that no
   longer match an interest area can be deleted with `rm
   <vault>/Wiki/concepts/<name>.md`."
   ```
3. The `auto_created: true` frontmatter contract stays unchanged.

**Acceptance criteria**:

- **AC-9.12.1** `skills/wiki-ingest/SKILL.md` Auto-bootstrap section
  documents the new two-paragraph sentinel body; the smoke test
  pinning the sentinel string is updated.
- **AC-9.12.2** `skills/wiki-lint/SKILL.md` Process Step 2 contains
  the new clarification prose ("intentionally empty until you run
  /paper-wiki:wiki-ingest").
- **AC-9.12.3** New smoke tests:
  - `test_wiki_ingest_sentinel_body_explains_next_step` — asserts
    the sentinel mentions both `/paper-wiki:wiki-ingest` and
    "stub" (or equivalent guidance).
  - `test_wiki_lint_explains_auto_stub_intent` — asserts the
    wiki-lint Process documents that stubs are intentionally
    empty.
- **AC-9.12.4** Task 9.10 runner uses the new sentinel body when
  creating stubs (or a constant shared between the runner and the
  SKILL test).

**Verification**:

- `pytest -q tests/test_smoke.py -k "sentinel or auto_stub_intent"`
  green.
- Manual: after a fresh-vault digest auto-ingest, open one of the
  generated stubs; the body explicitly tells you to run
  `/paper-wiki:wiki-ingest <id>`. Run `/paper-wiki:wiki-lint`; the
  "Needs review" message includes the intent clarification.

**Complexity**: S (20-30 min). Two SKILL prose edits + 2 smoke
tests. If 9.10 also ships in the same window, the runner sentinel
constant should live in one place (e.g. `paperwiki.runners._stub_constants`)
and be referenced by both the runner and the SKILL test.

**Dependencies**:
- Soft: Task 9.10. If 9.10 ships first with the OLD sentinel, 9.12
  updates it. If both ship together, single change.
- Independent of 9.9 / 9.11.

**Risk**: very low. Pure documentation / SKILL prose change.
Rollback = revert. No effect on already-created stubs in user vaults
(those keep the v0.3.7 sentinel; harmless).

---

### 10.3 Dependency graph + parallelization

```
9.1 (namespace fix) ────┬──> 9.6 (invariant test, same commit)        v0.3.6
                        │
                        ├──> 9.7 (auto-ingest bootstrap)              v0.3.7
                        │       │
                        │       └──> 9.10 (runner --auto-bootstrap)   v0.3.9
                        │               │
                        │               └──> 9.12 (sentinel + lint UX)  v0.3.11
                        │
9.2 (skeleton markers) ─┼──> 9.3 (overview synthesis)                 v0.3.7
                        │       │
                        │       └──> 9.4 (per-paper synthesis)        v0.3.10
                        │
                        ├──> 9.5 (auto image extraction)              v0.3.10
                        │
                        └──> 9.9 (concept matching threshold)         v0.3.11
                                │
                                └─> 9.11 (dedup log level, indep.)    v0.3.11
```

- **Sequenced strictly**: 9.1 → 9.2 → 9.3 → 9.4. Each builds on the
  previous.
- **Parallelizable in v0.3.7**: 9.3 and 9.7 ship together but touch
  different SKILL files (digest vs wiki-ingest); only conflict point is
  digest SKILL Process step 7 — write 9.7 first, then 9.3 layers
  in the overview-synthesis step alongside.
- **v0.3.9 is 9.10 alone** — the standalone "close the runner gap left
  by 9.7" release. No other tasks touch the same files, so it ships
  without blocking the bigger v0.3.10 batch.
- **Parallelizable in v0.3.10**: 9.5 can land in parallel with 9.4 —
  different files; only conflict point is digest SKILL Process, same
  pattern as above.
- **Parallelizable in v0.3.11**: 9.9 / 9.11 / 9.12 are mutually
  independent. 9.9 touches scorer + reporter + setup SKILL; 9.11 is a
  one-line dedup log change; 9.12 is two SKILL prose edits. Land in
  any order; bundle as one release for cohesion ("digest quality
  refinements").
- **9.6 lands in the same PR as 9.1** — the test would fail before the
  rewrite; bundling them keeps CI green at every commit.

### 10.4 Release sequencing

| Release | Tasks bundled | User-visible win |
|---------|---------------|------------------|
| v0.3.6  | 9.1 + 9.2 + 9.6 | Stale namespace gone; new digests have machine-targetable skeleton markers (no more "run SKILL after runner" prose); future regressions blocked by the invariant test. |
| v0.3.7  | 9.3 + 9.7 | Today's Overview callout actually has cross-paper synthesis; auto-ingest no longer dies on fresh vaults — concept stubs are bootstrapped automatically with a sentinel marker for later review. |
| v0.3.8  | 9.8 | Plugin upgrade UX fixed: `"skills"` declaration added to `plugin.json`; standard `/plugin uninstall` + `/plugin install` flow now works without manual cache cleanup. |
| v0.3.9  | 9.10 | Auto-bootstrap moved into the `wiki_ingest_plan` runner per SPEC §6 — the SKILL no longer falls back to fragile inline-Python `upsert_concept` calls. Closes the v0.3.7 partial-implementation gap. |
| v0.3.10 | 9.4 + 9.5 | Per-paper Detailed report has synthesized takeaways; auto-ingest-top papers get figures extracted automatically (visible on day 2). |
| v0.3.11 | 9.9 + 9.11 + 9.12 | Concept-matching threshold stops generic-keyword leakage (no more autonomous-driving papers in the biomedical bucket); fresh-vault `dedup.vault.missing` warnings drop to INFO; auto-stub bodies + wiki-lint message tell the user how to fold real content in. |

Six small releases, each independently shippable. Total estimated work:
11 tasks at 15-90 min each = **5.5-8.5 hours of focused work** for
Phase 9 in total. The 4 new tasks (9.9-9.12) add ~2.5-4.5 hours on top
of the original 7-task baseline.

### 10.5 Risks (Phase 9)

| Risk | Impact | Mitigation |
|------|--------|------------|
| Task 9.1 rewrite breaks a string the user relied on (e.g. `/paperwiki:digest` somewhere we didn't grep) | Slash command stops working in third-party docs | Stale namespace was already wrong (slash command name is `/paper-wiki:`); `claude plugin validate .` is the source of truth. CHANGELOG entry calls out the rename. |
| Task 9.3 synthesis hallucinates trends not present in the data | Misleading "Today's Overview" | SKILL Process requires `#N` citations for every claim; SKILL Common Rationalizations forbids inventing topic names; manual review on each digest run during v0.3.7 rollout. |
| Task 9.4 batching prompt blows context window when `top_k=20` | LLM call fails mid-digest | SKILL Process step says: batched prompt is default, fall back to per-paper if batched output truncates. Document max batch size empirically (likely ~10 abstracts). |
| Task 9.5 chains extract-images for 10+ papers per digest, hits arXiv rate-limits | First-run slowness | Runner already has 1/sec budget + caching; users with `auto_ingest_top > 5` see a one-time stall, then cached. SKILL Red Flags lists `auto_ingest_top > 10` as worth questioning. |
| HTML comment markers appear in Obsidian preview as visible glitches | Ugly digest UI | Obsidian hides HTML comments by default; verify on first v0.3.6 build. Fallback: switch to a YAML-fenced block as the marker. |
| Image extraction fails silently for one paper, the SKILL keeps going, user never finds out which | Half-imaged digest | SKILL Process step requires a one-line summary at the end ("3/3 succeeded, 0 failed"). |
| Task 9.7 auto-bootstrap pollutes vault with empty concept stubs the user later abandons | Vault clutter | `auto_created: true` frontmatter + sentinel body string; wiki-lint surfaces stubs in a dedicated "needs review" bucket the user can prune en masse. Manual `/paper-wiki:wiki-ingest` keeps the original confirmation prompt. |
| Task 9.9 default threshold (0.30) drops legitimate matches | Useful papers vanish from concept articles | Configurable via `wiki_topic_strength_threshold` recipe field; doc explicitly tells users to inspect 2-3 days of digest output and tune. Add Common Rationalizations note. |
| Task 9.9 per-topic strength is mis-saturated for tiny-keyword topics | A topic with only 1 keyword always reads "weak" | Use the same saturating curve `1 - 0.5**hits` whether scoring globally or per-topic; a single hit for a single-keyword topic still scores 0.5 (above default 0.3 threshold). |
| Task 9.10 runner schema change (`created_stubs`, moved fields) breaks third-party SKILLs reading the JSON | External SKILL silently degrades | Field is additive; old fields preserved. CHANGELOG entry surfaces the new field; smoke test asserts both old and new fields present. |
| Task 9.10 auto-bootstrap creates stubs for noisy `suggested_concepts` (compounds with 9.9 unless both ship) | Vault clutter on first run | Ship 9.10 in v0.3.9 alone (no threshold gating yet); 9.9 in v0.3.11 adds the gate. Document in v0.3.9 CHANGELOG that "concept-strength gating ships in v0.3.11". |
| Task 9.11 log-level downgrade hides a real misconfiguration (user typo'd vault path) | User wonders why dedup never fires | INFO line still includes the path verbatim; structured log key change (`dedup.vault.absent`) makes it filterable. Add a Red Flags entry to digest SKILL: "if a recipe's `vault_paths` are ALL absent across multiple runs, prompt user to re-run setup." |
| Task 9.12 sentinel body diverges between runner (Task 9.10) and SKILL (Task 9.7 docs) | Inconsistent bodies in user vaults | Define the sentinel as a constant in `paperwiki.runners._stub_constants`; runner imports it; smoke test asserts both SKILL.md and runner constant match. |

### 10.6 Rollback notes

- **9.1**: `git revert`. Risk = low because the rewrite is mechanical
  string substitution.
- **9.2**: `git revert`. Existing user vaults with old digests are
  unchanged.
- **9.3, 9.4, 9.5**: `git revert` on the SKILL.md. Slot markers stay
  in the file as orphan HTML comments — harmless.
- **9.6**: `pytest -k 'not test_no_stale_paperwiki_namespace'` to skip
  if the rewrite is being rolled back.
- **9.7**: `git revert` on the wiki-ingest + digest SKILL.md edits.
  Stubs already created in user vaults stay (sentinel string makes
  them findable: `grep -rl "Auto-created during digest auto-ingest"
  <vault>/Wiki/concepts/`); user can `rm -rf` them en masse or keep
  them as scaffolding.
- **9.9**: `git revert` on scorer + reporter + setup SKILL. Existing
  source files keep their pre-9.9 `related_concepts` lists (no
  rewrite). Users with custom `wiki_topic_strength_threshold` in
  their recipes get a YAML "unknown field" warning on next run —
  document a one-liner removal in CHANGELOG.
- **9.10**: `git revert` on runner + SKILL. Stubs already created by
  the runner stay in user vaults (same sentinel-grep cleanup as
  9.7). SKILL falls back to today's inline-Python path; v0.3.7
  fragility returns. Mitigation: rolling back 9.10 alone is rare —
  if it lands buggy, prefer a forward fix.
- **9.11**: `git revert`. The structured log key changes back to
  `dedup.vault.missing`; warning level returns. Pure observability
  change.
- **9.12**: `git revert`. Stubs created with the new sentinel keep
  it in user vaults (harmless prose); the SKILL Process reverts to
  the pre-9.12 prose.

### 10.7 Out of scope (Phase 9)

- Phase 8 PDF text extraction (still candidate; per-paper synthesis in
  9.4 leans on the abstract only — we'll know after v0.3.8 ships
  whether 9.4's quality justifies promoting Phase 8 to active).
- Migrating `extract-paper-images` SKILL to chain automatically inside
  the runner (would violate SPEC §6 — Python stays LLM-free; chaining
  belongs in the SKILL).
- Rewriting `_today_overview_block` to do client-side synthesis (would
  violate SPEC §6 — runner stays deterministic).
- Per-paper images in the inline teaser for `paperclip:` /
  `s2:` ids — those don't have arXiv source tarballs. Document the
  limitation; don't pretend.
- Adding a `confidence` field to the synthesized Today's Overview
  prose — the user's mental model is "this is my Claude assistant
  summarizing the day"; a confidence score on cross-paper synthesis
  is over-engineering for a 200-word block.

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
