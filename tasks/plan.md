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

## 10. Phase 9 — Digest quality (active, v0.3.6 → v0.3.21)

**Status**: Active. v0.3.6–v0.3.12 shipped. v0.3.13–v0.3.21 outstanding.
v0.3.13–v0.3.18 cover citation-folding, e2e smoke, logging, per-paper
synthesis, concept-matching threshold, vault lock, and overview crash-
safety (the first round, planned 2026-04-27 morning). v0.3.19–v0.3.21
cover six new findings from the 2026-04-27 evening smoke run against
v0.3.18: inline figures inside Detailed reports, gating Detailed
reports by `auto_ingest_top`, interpretive Score reasoning, personal-
recipe migration, `s2.parse.skip` log-level downgrade, and
`extract-images` failure UX.

**Original framing (2026-04-27 morning)**: a chain of three small
releases to fix the placeholder-prose / stale-namespace / no-images
regressions a user observed on a fresh-vault digest run.

**Updated framing (2026-04-27 evening)**: after seven cumulative
releases (v0.3.6–v0.3.12), the user has run digest three times against
fresh vaults. Each run hit a different bug. The latest run (v0.3.12)
**hung for 4 minutes mid-flow** during the auto-chain step, with the
SKILL stuck in a Read-then-Edit loop on a pre-existing concept article.
The transcript was:

```
⏺ For paper #2 and #3, I need to fold the new source citations into
  the pre-existing stubs. I'll update each stub's sources list directly.
  Read 2 files (ctrl+o to expand)
⏺ Update(Documents/Paper-Wiki/Wiki/concepts/vision-multimodal.md)
  ⎿  File must be read first
✻ Cooked for 4m 0s
```

The architectural mismatch causing this hang is documented in §10.8
below. In short: the runner with `--auto-bootstrap` only handles
**stub creation** for missing concepts. The actual **citation-folding
into pre-existing concepts** is still SKILL-side LLM Edit work, which
is fragile and slow. The fix (Task 9.13, §10.8) moves this work into
the deterministic Python runner where it belongs per SPEC §6.

This revision adds six tasks (9.13–9.18, §10.7–§10.12) and reshapes
the release sequencing into v0.3.13–v0.3.18, each shippable in
~30–60 minutes of focused work, with a hard floor of an end-to-end
smoke test (Task 9.14) that runs in CI on every commit.

**2026-04-27 evening update**: a v0.3.18 fresh-vault smoke run
surfaced six more findings (s2.parse.skip log noise, extract-images
failure UX gap, stale personal-recipe keywords, no figures inside
synthesized Detailed reports, mechanical Score reasoning, and
all-paper synthesis ignoring `auto_ingest_top`). Tasks 9.19–9.24
(§10.14–§10.19) cover these and ship across three additional
releases: v0.3.19 (figures + top-N gating), v0.3.20 (interpretive
Score reasoning + recipe migration), v0.3.21 (cleanup: log levels +
extract-images summary).

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

**Shipped (v0.3.6 – v0.3.12):**

```
9.1 (namespace fix) ────┬──> 9.6 (invariant test, same commit)        v0.3.6
                        │
                        ├──> 9.7 (auto-ingest bootstrap docs)         v0.3.7
                        │       │
                        │       └──> 9.10 (runner --auto-bootstrap)   v0.3.9
                        │
9.2 (skeleton markers) ─┼──> 9.3 (overview synthesis)                 v0.3.7
                        │
                        └──> 9.8 (standard upgrade flow)              v0.3.8

[v0.3.10 — digest SKILL: imperative auto-chain]                       v0.3.10
[v0.3.11 — wiki-ingest SKILL: append flag, no inline-Python]          v0.3.11
[v0.3.12 — quiet runner DEBUG + dedup.vault.missing → DEBUG]          v0.3.12
```

**Outstanding (v0.3.13 – v0.3.18):**

```
9.13 (citation folding into runner) ────────────┬──> 9.16 (SKILLs use runners)   v0.3.13
                                                │
                                                └──> 9.14 (e2e smoke test)       v0.3.14
                                                          │
                                                          └──> 9.15 (centralized logger)   v0.3.15
                                                                    │
9.4 (per-paper synthesis) ──────────────────────┬─────────┬─> 9.5 (auto images)  v0.3.16
                                                │         │
9.9 (concept matching threshold) ───────────────┼─────────┴─> 9.12 (auto-stub UX)   v0.3.17
                                                │
                                                └──> 9.17 (vault lock)              v0.3.18
                                                          │
                                                          └──> 9.18 (overview crash-safe)   v0.3.18
```

**This revision (v0.3.19 – v0.3.21):**

```
9.4 (per-paper synthesis, shipped v0.3.16) ─┬─> 9.22 (figures in Detailed report)   v0.3.19
                                            │
                                            └─> 9.24 (Detailed reports gated by N)  v0.3.19
                                                  │
                                                  └─> 9.23 (insightful Score reasoning)  v0.3.20
                                                        │
9.9 (keyword tightening, shipped v0.3.17) ─────────────┴─> 9.21 (personal recipe migrate)  v0.3.20
                                                                │
9.5 (auto image extraction, shipped v0.3.16) ──────────────────┴─> 9.20 (extract-images failure UX)   v0.3.21
                                                                          │
9.12 (dedup.vault.missing → DEBUG, shipped v0.3.12) ─────────────────────└─> 9.19 (s2.parse.skip log level)   v0.3.21
```

- **9.22 + 9.24 ship together as v0.3.19** — both are SKILL prose only,
  highest user-visible impact (figures inside synthesized prose +
  honoring the depth-of-treatment envelope), strongly coupled (9.22's
  figure-embed contract only fires for top-N papers, which is exactly
  what 9.24 gates on).
- **9.23 + 9.21 ship together as v0.3.20** — 9.23 is SKILL prose
  (interpretive Score reasoning); 9.21 is a new runner + SKILL +
  setup integration (heaviest task in the v0.3.19–v0.3.21 cycle).
  Bundling balances the release weight: one SKILL-prose win + one
  runner-feature win.
- **9.19 + 9.20 ship together as v0.3.21** — both are cleanup/UX
  fixes (log-level downgrade + per-paper extract-images summary),
  smaller scope, ship as the "polish" release after the substance
  lands.

- **9.13 is the keystone.** Once citation folding moves into the
  runner, the digest auto-chain stops needing Claude to do Read+Edit
  per concept. This is the fix for the 4-minute hang.
- **9.16 follows 9.13 in the same release.** No point landing the
  runner if the SKILLs still orchestrate it the old way.
- **9.14 (e2e smoke) lands AFTER 9.13/9.16** because the test asserts
  the new auto-chain shape (subprocess-only, no LLM Edit/Read). It
  becomes the hard floor for every subsequent release.
- **9.15 (centralized logger) is independent** but lands after 9.14
  so the e2e smoke can pin "no DEBUG noise" as part of its asserts.
- **9.4 / 9.5** can land together (parallel SKILL prose; no file
  conflicts). 9.4 is the heaviest LLM cost; 9.5 is a 5-line SKILL
  prose addition.
- **9.9 / 9.12** can land together (different files). 9.9 is the
  scorer + reporter + setup SKILL change; 9.12 is the
  `_stub_constants.py` body update + wiki-lint SKILL message.
- **9.17 (vault lock)** is a defensive feature; ships standalone
  because it touches every mutating runner.
- **9.18 (overview crash-safe)** is SKILL prose only; ships
  alongside 9.17 for cohesion ("robustness release").

### 10.4 Release sequencing

**Shipped:**

| Release | Tasks | User-visible win |
|---------|-------|------------------|
| v0.3.6  | 9.1 + 9.2 + 9.6 | Stale namespace gone; machine-targetable skeleton markers; invariant test pins the contract. |
| v0.3.7  | 9.3 + 9.7 | Today's Overview synthesis; auto-ingest bootstrap docs. |
| v0.3.8  | 9.8 | Plugin upgrade UX: `"skills"` declaration; standard `/plugin uninstall` + `/plugin install` flow. |
| v0.3.9  | 9.10 | Auto-bootstrap runner-side; SKILL no longer falls back to inline-Python. |
| v0.3.10 | digest SKILL imperative auto-chain | No "shall I chain?" prompt; `auto_ingest_top: N` is the user's pre-approval. |
| v0.3.11 | wiki-ingest SKILL flag-append + no-inline-Python | Closes the v0.3.10 prose gap that allowed inline-Python regression. |
| v0.3.12 | runner DEBUG quieting + dedup.vault.missing → DEBUG | Fresh-vault digest no longer leaks DEBUG / WARNING noise to user transcript. |

**Outstanding (this revision):**

| Release | Tasks bundled | User-visible win | Time |
|---------|---------------|------------------|------|
| v0.3.13 | 9.13 + 9.16 | **Auto-chain stops hanging.** Citation folding moves into the runner; SKILLs no longer do Read+Edit dances on concept files. The 4-minute mid-flow hang is gone. | 60-90 min |
| v0.3.14 | 9.14 | **No more per-release regressions.** End-to-end smoke test pins the full digest → auto-chain pipeline as a hard CI floor. Every future release inherits this floor. | 45-60 min |
| v0.3.15 | 9.15 | **Clean logs by default.** Centralized `_internal/logging.py` module + `--verbose` flag + `PAPERWIKI_LOG_LEVEL` env var. No more spot-fixes per release for noisy `logger.debug` lines. | 30-45 min |
| v0.3.16 | 9.4 + 9.5 | **Per-paper Detailed report has prose**; **auto-ingest-top papers get figures** (visible day 2). | 60-90 min |
| v0.3.17 | 9.9 + 9.12 | Concept-matching threshold stops generic-keyword leakage; auto-stub bodies + wiki-lint message clarify next steps. | 45-75 min |
| v0.3.18 | 9.17 + 9.18 | Vault lock prevents corruption when two sessions race; Today's Overview is crash-safe (SIGINT mid-pass leaves the digest file recoverable). | 30-45 min |
| v0.3.19 | 9.22 + 9.24 | **Inline figures appear inside synthesized Detailed reports**; **Detailed reports honor `auto_ingest_top`** (top-N get deep, rest get teaser). | 60-80 min |
| v0.3.20 | 9.25 + 9.26 | **Image extraction quality leap** (PyMuPDF + 3-priority strategy per evil-read-arxiv reference; ~80% figure-recovery vs ~30%) **and** `paperwiki update` CLI that ends the manual JSON-cleanup ritual every release has required. | 120-165 min |
| v0.3.21 | 9.23 + 9.21 | **Score reasoning is interpretive, not transcriptive** (1–2 sentences explaining WHY, not paraphrasing sub-scores); **personal recipes can be migrated to v0.3.17 keyword updates** without re-running setup. | 90-120 min |
| v0.3.22 | 9.19 + 9.20 | **Cleanup release**: `s2.parse.skip` no longer leaks WARNINGs on every digest; `extract-images` failures surface a per-paper summary so users know which paper failed and why. | 35-55 min |

Ten outstanding releases (six previously planned + four from this
revision: 9.25 split off from v0.3.19 because PyMuPDF dep + caption-crop
algorithm pushes it to M-L size), each ~30–120 minutes of focused work.
**Total (v0.3.13 – v0.3.22): 9–13 hours.** Each release can be cut
and tagged independently so the user feels a steady drip of fixes.

### 10.4.1 Why v0.3.13 ships first (and alone)

Three reasons to land 9.13 + 9.16 together as v0.3.13 BEFORE everything
else, even though the e2e smoke test (9.14) is more obviously
"infrastructure":

1. **9.13 is the actual bug fix the user is blocked on.** Every fresh
   digest run hangs at the auto-chain step because of the SKILL-side
   Edit dance. Until the runner does the citation folding, the user
   can't get a full pipeline run end-to-end.
2. **9.14 needs 9.13 to pin the right contract.** Writing the e2e
   test before the runner change would lock in the broken
   architecture.
3. **9.16 (SKILL trim) can't ship without 9.13** — the SKILL change
   is "delete the Read+Edit prose because the runner does it now".

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
| Task 9.13 runner mutates concept frontmatter; if a user has hand-edited a concept's `sources:` list, the runner appends without merging | User edit lost mid-list | Runner reads existing `sources:`, appends only if `canonical_id` not already present; round-trips other frontmatter verbatim (yaml.safe_dump preserves order via `sort_keys=False`); never deletes existing entries. Smoke test pins a hand-edited concept survives the fold. |
| Task 9.13 changes the JSON schema (new `folded_citations` field) — third-party SKILLs reading the JSON might break | Silent schema drift | Field is additive; `affected_concepts` and `created_stubs` preserved. CHANGELOG calls out the new field; e2e smoke (9.14) asserts the schema. |
| Task 9.14 e2e smoke test relies on a stub `Source` plugin — if the real `ArxivSource` schema drifts, the test passes but production still breaks | False sense of security | Stub plugin uses the same `Paper` model as production; recipe loader / pipeline / scorer / reporter / wiki-backend are real. Only the network adapter is mocked. CI also keeps the existing `test_bundled_recipes.py` to catch source-plugin schema drift. |
| Task 9.15 logger config breaks tests that capture log output via `caplog` | Test suite goes red | New `configure_runner_logging` is opt-in (called from runners' `main()`); pytest fixtures don't trigger it. Existing tests that import `from loguru import logger` keep working. New `tests/unit/_internal/test_logging.py` pins the configure-then-log shape. |
| Task 9.17 lock file gets stranded after a crash — user can't run anything until they `rm` it | UX foot-gun | `acquire_vault_lock` reclaims locks older than `stale_after_s` (default 5 min); the held-lock error message tells the user the exact `rm` path. Lock content is human-readable JSON `{pid, host, started_at, runner}`. |
| Task 9.17 lock file in user vault confuses Obsidian sync (Dropbox / iCloud) | Sync conflicts | `.paperwiki.lock` filename starts with a dot (Obsidian doesn't index dotfiles); recommend `.paperwiki.lock` be added to `.gitignore` (already implied by `Wiki/.cache/`-style ignores). Document in CHANGELOG. |
| Task 9.18 SIGINT handler races with file write — partial digest on disk | Half-written digest | The digest runner already writes the file in one `aiofiles.open(...).write(rendered)` call; SIGINT interrupting the write is a kernel-level concern not addressable in user-space. SKILL prose only documents that the SLOT MARKERS make the file re-fillable, not that the file is atomically written. |
| Task 9.19 log-level downgrade hides a real S2 schema break (e.g. S2 changes their JSON shape) | Silent data loss | The `model validation` branch (line 219) STAYS at WARNING — that's the only branch that catches schema-shape failures. Sparse-record branches stay at DEBUG; summary INFO line surfaces aggregate count so observability isn't lost. |
| Task 9.20 extract-images summary block becomes noise when nothing failed (e.g. all 3 succeeded with 0 figures) | Boilerplate output | Format is intentionally compact (3 lines for top-3 papers); even all-success is useful confirmation. SKILL Common Rationalizations forbids "skip if all succeeded". |
| Task 9.21 migrate-recipe applies an unwanted update to a power-user's hand-tuned keywords | User loses customization | `recipe_migrations` map is conservative — only removes keywords explicitly listed in `remove`; never strips a user's custom additions. Backup file at `<recipe-path>.bak.<timestamp>` is always created so the user can restore manually. SKILL Process invokes `--dry-run` first; user confirms via AskUserQuestion before apply. |
| Task 9.21 setup SKILL adds a migration prompt that fires every time, becoming nag fatigue | User stops invoking setup | Heuristic check ONLY fires when the user already chose "Keep current config" in Branch 1; never volunteers itself in the wizard flow. Once migrated, the recipe matches the target version and the heuristic returns clean — no future prompts. |
| Task 9.22 SKILL embeds a 50 MB PDF figure inline, blowing up Obsidian render time | Slow note open | Figure-selection heuristic prefers `fig1.*` / `figure_1.*` / `teaser.*` over generic names; cap is 1–2 figures per Detailed report; embed size is `\|600` (Obsidian downsamples). The `extract_paper_images` runner already filters out tiny icon-fragments (per the v0.3.18 commit `c7d5df4`). |
| Task 9.22 figure paths drift if `extract_paper_images` changes its output directory naming | Broken inline embeds | SKILL prose references the same `<source_filename>/images/` namespace the reporter uses for the card teaser (`_canonical_id_to_filename`); a single source of truth. Smoke test pins the path shape. |
| Task 9.23 LLM synthesizes Score reasoning prose that contradicts the actual sub-scores (e.g. claims "high momentum" when momentum=0.50) | Misleading interpretation | SKILL Process requires the synthesized line to be GROUNDED in the sub-score numbers (cite at least one); SKILL Common Rationalizations bans "interpret optimistically". Manual review on each digest run during v0.3.20 rollout. |
| Task 9.24 users who liked all-paper Detailed reports see them disappear for #4–#10 | Perceived feature regression | Teaser line names `/paper-wiki:analyze <id>` so manual deep dives are one command away; CHANGELOG entry calls out the contract shift; recipe doc note says `auto_ingest_top` is now a depth-of-treatment knob. Power users can set `auto_ingest_top: 10` to recover all-paper synthesis. |
| Task 9.24 reporter still emits per-paper slot markers for ALL papers but SKILL only fills top-N | Orphan markers in older re-runs | Option 1 (chosen) keeps reporter simple: SKILL replaces sub-top-N markers with the teaser line during Step 8. If the SKILL crashes mid-step 8, sub-top-N markers stay; user re-runs SKILL and they get filled (idempotent — neither path produces orphans long-term). |

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
- **9.13**: `git revert` on the new runner. Concepts already folded
  via the runner keep the appended `canonical_id` in their `sources:`
  frontmatter (harmless — that's where it should be). The wiki-ingest
  SKILL falls back to the old Read+Edit dance via the v0.3.12 SKILL
  prose; users see the 4-minute hang return on next digest.
  Mitigation: forward fixes preferred over rollback for 9.13.
- **9.14**: `pytest -k 'not test_full_digest_auto_chain'` to skip if
  the test is too brittle. Better: fix the brittleness inline.
- **9.15**: `git revert`. Loguru defaults return; user sees DEBUG
  noise again. Pure observability change.
- **9.16**: `git revert` on SKILL.md. SKILLs go back to the old
  Read+Edit prose; runner gains stay (no harm). Net: similar to 9.13
  rollback but the runner side is preserved.
- **9.17**: `git revert`. Lock file logic gone; concurrent writes
  resume the racey-but-rare-in-practice behavior. Users with a
  stranded `.paperwiki.lock` in their vault can `rm` it.
- **9.18**: `git revert` on SKILL.md. Pre-revert digest files keep
  their slot markers (harmless); SKILL Process reverts to the
  pre-9.18 ordering.
- **9.19**: `git revert`. Loguru level returns to WARNING for the
  four sparse-record branches; structured-log key reverts to
  `s2.parse.skip` from `s2.parse.skipped_summary`. Pure observability
  change.
- **9.20**: `git revert` on the digest SKILL.md. Existing digest
  files unaffected; SKILL terminal output stops emitting the
  per-paper extract-images summary; failures revert to silent
  absorption (today's behavior). Pure SKILL prose change.
- **9.21**: `git revert` removes the `migrate_recipe` runner +
  SKILL + setup integration. Personal recipes already migrated by
  users keep their post-migration shape (harmless — the new keyword
  lists are strictly better). Backup files at
  `<recipe-path>.bak.<timestamp>` survive on disk; users can restore
  manually if any custom keyword was lost. The setup SKILL Branch 1
  prose reverts to pre-9.21.
- **9.22**: `git revert` on SKILL.md. Existing digest files keep
  their inline figure embeds (markdown is plain text); subsequent
  digests synthesize Detailed reports without figures (today's
  v0.3.18 behavior). Card teaser is unaffected (still rendered by
  the reporter).
- **9.23**: `git revert` on SKILL.md. Existing digest files keep
  their interpretive Score reasoning (markdown is plain text);
  subsequent digests revert to transcriptive sub-score paraphrase.
  Pure SKILL prose change.
- **9.24**: `git revert` on SKILL.md. Future digests regress to
  all-paper synthesis (no top-N gate); existing digest files in user
  vaults are unchanged (markdown is plain text). Per-paper slot
  markers stop being replaced by the teaser line; SKILL fills all
  slots again. Low-cost rollback.

---

### 10.7 Task 9.13 — Move citation folding from SKILL to runner → v0.3.13

**Problem (discovered during 2026-04-27 v0.3.12 fresh-vault smoke run)**:

Per the SKILL transcript, after the digest auto-chain invoked
`/paper-wiki:wiki-ingest <id> --auto-bootstrap` for paper #1, control
moved to paper #2 and #3, where the SKILL had to fold the new source's
`canonical_id` into the `sources:` lists of TWO PRE-EXISTING concepts
(`vision-multimodal`, `agents-reasoning`) the user had created
manually. The SKILL transcript shows:

```
⏺ For paper #2 and #3, I need to fold the new source citations into
  the pre-existing stubs. I'll update each stub's sources list directly.
  Read 2 files (ctrl+o to expand)
⏺ Update(Documents/Paper-Wiki/Wiki/concepts/vision-multimodal.md)
  ⎿  File must be read first
✻ Cooked for 4m 0s
```

The Edit tool requires the file to be Read first; Claude Read it,
tried to Edit, hit a "File must be read first" error (probably a
race or a SKILL-side bug), retried, looped, and stalled for four
minutes before the user gave up.

**Architectural diagnosis**:

`paperwiki.runners.wiki_ingest_plan` accepts `--auto-bootstrap`
(shipped v0.3.9) which auto-creates STUBS for missing concepts in
`suggested_concepts`. But for concepts that ALREADY EXIST (and the
source's frontmatter `related_concepts` lists them), the runner
returns them in `affected_concepts` and the SKILL is expected to
"fold the source citation in" via LLM-driven Edits. The wiki-ingest
SKILL Process Step 4:

> 4. **Update affected concepts.** For each name in
>    `affected_concepts`: read the existing concept body, fetch the new
>    source's content, and synthesize an updated body that
>    incorporates the new evidence without dropping prior synthesis.

This step assumes the SKILL will do BOTH:

- (a) **fold the source citation** into the concept's `sources:`
  frontmatter list, AND
- (b) **synthesize updated body prose** that reflects the new
  evidence.

(a) is a deterministic YAML mutation. (b) is genuine LLM synthesis.
Today, both are bundled into the same SKILL step — and the bundled
step does Read + Edit per concept, which is fragile and slow.

**The fix is to split (a) from (b):**

- (a) **citation folding** moves into the runner. Pure file I/O.
  Always runs. Idempotent.
- (b) **body synthesis** stays in the SKILL but becomes EXPLICITLY
  manual-only (`/paper-wiki:wiki-ingest <id>` without
  `--auto-bootstrap` triggers it; the digest auto-chain skips it).

This puts the architecture on the right side of SPEC §6: Python is
LLM-free deterministic file I/O; SKILLs do genuine synthesis only when
the user asks for it.

**Solution**:

Rename `paperwiki.runners.wiki_ingest_plan` to
`paperwiki.runners.wiki_ingest` (one runner, two modes via flags).
Old module stays as a deprecation shim importing from the new one,
emitting a one-line `DeprecationWarning`. Or land a new module side-
by-side and migrate the SKILL — the user can choose; the cleaner
architecture is the rename.

**New CLI**:

```
python -m paperwiki.runners.wiki_ingest <vault> <canonical-id>
    [--auto-bootstrap]   # creates stubs for missing concepts (existing v0.3.9 behavior)
    [--fold-citations]   # appends canonical_id to each affected concept's sources list (NEW)
```

The two flags are independent. Auto-chain digest passes both; manual
invocations of `/paper-wiki:wiki-ingest <id>` pass neither (interactive
mode).

**Citation-folding implementation** (new in this task):

For each name in `affected_concepts`:

1. Read `<vault>/Wiki/concepts/<name>.md` via the existing
   `_read_frontmatter` helper.
2. If `canonical_id` is already in `frontmatter["sources"]`, skip
   (idempotent — covers the "re-run same digest" case).
3. Append `canonical_id` to `frontmatter["sources"]`. Bump
   `frontmatter["last_synthesized"]` to today (UTC). Other fields
   (title, status, confidence, related_concepts) preserved verbatim.
4. Re-render the file: frontmatter (yaml.safe_dump, sort_keys=False)
   + `---\n\n` + existing body verbatim. Body is read from disk and
   passed through unchanged.
5. Append the concept name to `folded_citations: list[str]` in the
   JSON output.

**SKILL change** (`skills/wiki-ingest/SKILL.md` Process Step 4):

> 4. **Update affected concepts.** For each name in
>    `affected_concepts`:
>
>    - **If `--fold-citations` was passed (the digest auto-chain
>      path)**: SKIP this step. The runner has already appended the
>      source citation to each concept's `sources:` frontmatter. Do
>      NOT Read or Edit any concept file. Surface
>      `folded_citations` count from the runner JSON in your summary.
>    - **Otherwise (interactive `/paper-wiki:wiki-ingest <id>` invocation)**:
>      proceed with body-synthesis update as documented today.

**Acceptance criteria**:

- **AC-9.13.1** `paperwiki.runners.wiki_ingest` (or
  `paperwiki.runners.wiki_ingest_plan` extended) accepts both
  `--auto-bootstrap` and `--fold-citations` Typer flags.
- **AC-9.13.2** `--fold-citations` appends `canonical_id` to each
  affected concept's `sources:` frontmatter list. Idempotent (no
  duplicate appends if the canonical_id is already present).
- **AC-9.13.3** Concept body is preserved byte-for-byte across the
  fold. Frontmatter ordering is preserved (yaml.safe_dump
  `sort_keys=False`).
- **AC-9.13.4** Last_synthesized in folded concepts bumps to today.
- **AC-9.13.5** JSON output gains `folded_citations: list[str]`
  field. Empty list when `--fold-citations` is not passed (legacy
  schema preserved).
- **AC-9.13.6** Wiki-ingest SKILL Process Step 4 is updated:
  `--fold-citations` path skips the Read+Edit dance entirely; SKILL
  surfaces the count from runner JSON.
- **AC-9.13.7** New unit tests:
  - `test_fold_citations_appends_canonical_id_to_existing_concept`
  - `test_fold_citations_idempotent_when_canonical_id_already_present`
  - `test_fold_citations_preserves_concept_body_verbatim`
  - `test_fold_citations_preserves_other_frontmatter_fields`
  - `test_fold_citations_bumps_last_synthesized_to_today`
  - `test_fold_citations_no_op_when_affected_concepts_empty`
  - `test_runner_with_both_flags_creates_stubs_and_folds_existing`

**Verification**:

- `pytest -q tests/unit/runners/test_wiki_ingest.py -k fold_citations`
  green.
- Manual: with two pre-existing concepts in `<vault>/Wiki/concepts/`,
  invoke
  `python -m paperwiki.runners.wiki_ingest <vault> arxiv:X --fold-citations`;
  observe both concepts gain `arxiv:X` in their `sources:` list,
  bodies unchanged, no LLM tools invoked.

**Complexity**: L (60–90 min). New runner subcommand or rename;
seven unit tests; SKILL Process Step 4 rewrite; smoke test update.

**Dependencies**:
- Hard: nothing (the runner already exists; this is a new mode).
- Soft: 9.16 (SKILL trim) ships in same release.

**Risk**: low-medium. Risk = a hand-edited concept's frontmatter has
non-standard fields the runner doesn't preserve. Mitigation =
yaml.safe_dump round-trip preserves arbitrary keys; smoke test pins
this with a concept that has a custom `notes:` field.

---

### 10.8 Task 9.14 — End-to-end smoke test → v0.3.14

**Problem**: the user has run `/paper-wiki:digest` against a fresh
vault three times across v0.3.5, v0.3.10, and v0.3.12. Each run hit
a different bug:

- v0.3.5: stale `/paperwiki:` namespace (fixed in v0.3.6).
- v0.3.10: SKILL asked "shall I auto-chain?" (fixed in v0.3.10).
- v0.3.12: SKILL hung 4 minutes mid-flow on Edit dance (fix landing
  in v0.3.13).

Three releases, three fresh-vault regressions. The pattern is clear:
**there is no end-to-end test exercising the full digest + auto-chain
pipeline.** Existing tests cover individual modules, individual
runners, individual SKILLs — but nothing pins the whole digest →
auto-chain → wiki-state-on-disk flow as a hard contract.

**Solution**: add `tests/integration/test_full_digest_auto_chain.py`.
This is the floor that every future release must hold.

**Test structure**:

```python
async def test_full_digest_auto_chain_lands_top_papers_into_wiki(
    tmp_path: Path,
) -> None:
    """Fresh vault → digest → auto-chain → wiki state on disk."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Stub source emits 3 deterministic papers (no network).
    recipe = build_test_recipe(
        vault=vault,
        sources=[StubSource(papers=[paper1, paper2, paper3])],
        auto_ingest_top=3,
        topics=[topic_vision, topic_agents],
    )

    # Run the real digest pipeline.
    await run_digest(recipe_path=recipe, target_date=fixed_date)

    # Assert digest file on disk.
    digest_files = list((vault / "Daily").glob("*.md"))
    assert len(digest_files) == 1

    # Simulate the digest SKILL's auto-chain step: invoke
    # the wiki_ingest runner subprocess-style for each top paper.
    for paper in [paper1, paper2, paper3]:
        result = subprocess.run([
            sys.executable, "-m", "paperwiki.runners.wiki_ingest",
            str(vault), paper.canonical_id,
            "--auto-bootstrap", "--fold-citations",
        ], capture_output=True, check=True)
        plan = json.loads(result.stdout)
        # Each paper should have stubbed >= 1 concept OR folded into >= 1.
        assert plan["created_stubs"] or plan["folded_citations"]

    # Assert wiki state on disk.
    concepts = list((vault / "Wiki" / "concepts").glob("*.md"))
    assert len(concepts) >= 3, "expected >= 3 concept stubs"

    for concept_path in concepts:
        text = concept_path.read_text()
        # Each concept references at least one source.
        assert "sources:" in text
        # Auto-created stubs use the sentinel body.
        if "auto_created: true" in text:
            assert AUTO_CREATED_SENTINEL_BODY in text
```

Pinned contracts (every assertion is a contract):

1. **Pipeline produces a digest file** (count + filename pattern).
2. **Auto-chain runner is invoked subprocess-style** with
   `--auto-bootstrap --fold-citations`. NO Claude Edit/Read tool
   calls happen for citation folding. (This is what the v0.3.12
   transcript got wrong.)
3. **Concept stubs are created** for missing concepts.
4. **Pre-existing concepts get the new source's `canonical_id`** in
   their `sources:` list (Task 9.13's contract).
5. **No DEBUG noise** — capture stderr, assert no `DEBUG` lines
   (the v0.3.15 contract).
6. **Total runtime < 10 seconds** — pin no SKILL hang.

**Acceptance criteria**:

- **AC-9.14.1** `tests/integration/test_full_digest_auto_chain.py`
  exists.
- **AC-9.14.2** Test passes on a clean checkout.
- **AC-9.14.3** Test fails when `--fold-citations` is broken in the
  runner (smoke-test the test by manually breaking the runner
  during development — verify the test points at the right
  assertion).
- **AC-9.14.4** Test fails when DEBUG-noise is reintroduced (after
  9.15).
- **AC-9.14.5** Test runtime < 10s (no live network; no LLM).
- **AC-9.14.6** Test asserts subprocess-style runner invocation,
  NOT in-process — this is the contract that the auto-chain is
  Python-only.

**Verification**:

- `pytest -q tests/integration/test_full_digest_auto_chain.py`
  green.
- Manual: deliberately break the `--fold-citations` flag in the
  runner; the test fails with a precise message about a missing
  source citation.

**Complexity**: M (45–60 min). Single test file with ~80 LoC; one
StubSource fixture (~30 LoC); reuses existing recipe / pipeline /
backend.

**Dependencies**:
- Hard: 9.13 (the test asserts the new flag's contract).
- Soft: 9.15 (the no-DEBUG-noise assert depends on the centralized
  logger).

**Risk**: low. Risk = test brittleness across CI runners (timing,
filesystem). Mitigation = `tmp_path`, fixed `target_date`,
no-network stub source, async-await for I/O.

---

### 10.9 Task 9.15 — Centralized logger config + `--verbose` → v0.3.15

**Problem**: loguru defaults to DEBUG. Every release has had at least
one "user sees DEBUG noise" report. v0.3.12 patched two specific
lines; v0.3.13 will introduce a new runner with new DEBUG-eligible
log calls; the pattern repeats.

There is currently NO `paperwiki._internal/logging.py` (verified —
the file does not exist). Each runner imports `from loguru import
logger` directly and gets loguru's defaults.

**Solution**: add `src/paperwiki/_internal/logging.py`:

```python
"""Centralized logger configuration for paperwiki runners."""

from __future__ import annotations

import os
import sys

from loguru import logger


def configure_runner_logging(
    *,
    verbose: bool = False,
    default_level: str = "INFO",
) -> None:
    """Reset loguru's sinks and re-configure for runner output.

    Removes the default DEBUG sink. Adds a stderr sink at
    ``default_level`` (INFO) or DEBUG when ``verbose`` is True.
    Honors PAPERWIKI_LOG_LEVEL env var as the highest-priority
    override (so CI / hooks can silence runners with one env var).
    """
    logger.remove()  # Drop loguru's default DEBUG sink.

    env_override = os.environ.get("PAPERWIKI_LOG_LEVEL")
    if env_override:
        level = env_override.upper()
    elif verbose:
        level = "DEBUG"
    else:
        level = default_level

    logger.add(
        sys.stderr,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function} - {message}",
    )

    # Pin chatty modules to WARNING by default (overridable via
    # PAPERWIKI_LOG_LEVEL=DEBUG which still wins).
    if not verbose and not env_override:
        logger.disable("paperwiki.plugins.filters.dedup")
        logger.disable("paperwiki._internal.arxiv_source")
```

Every runner's `main()` calls
`configure_runner_logging(verbose=verbose_flag)` as the first line.
Each runner gains a `--verbose / -v` Typer option (default False).

**Acceptance criteria**:

- **AC-9.15.1** `src/paperwiki/_internal/logging.py` exists with
  `configure_runner_logging`.
- **AC-9.15.2** Every runner (`digest`, `wiki_ingest`,
  `wiki_compile`, `wiki_query`, `wiki_lint`, `extract_paper_images`,
  `migrate_sources`, `diagnostics`) imports + calls
  `configure_runner_logging` in `main()`.
- **AC-9.15.3** Every runner exposes `--verbose / -v` Typer option.
- **AC-9.15.4** Default behavior: no DEBUG lines on stderr.
- **AC-9.15.5** `--verbose` enables DEBUG.
- **AC-9.15.6** `PAPERWIKI_LOG_LEVEL=WARNING` silences INFO.
- **AC-9.15.7** Unit test `test_configure_runner_logging_default_level_is_info`
  pins INFO is default.
- **AC-9.15.8** Unit test
  `test_configure_runner_logging_verbose_emits_debug` pins
  `--verbose` re-enables DEBUG.
- **AC-9.15.9** e2e smoke (Task 9.14) asserts no DEBUG lines on
  stderr.

**Verification**:

- `pytest -q tests/unit/_internal/test_logging.py` green.
- Manual: fresh vault `/paper-wiki:digest daily` produces zero
  DEBUG lines on stderr; `python -m paperwiki.runners.digest
  recipes/daily-arxiv.yaml --verbose` re-enables DEBUG.

**Complexity**: S (30–45 min). One new module (~30 LoC); 8 runner
edits (1 line each); 2 unit tests.

**Dependencies**: none (independent).

**Risk**: very low. Risk = users who set `LOGURU_LEVEL` env var
expect the old behavior. Mitigation = `PAPERWIKI_LOG_LEVEL` is a
distinct namespaced env var; loguru's `LOGURU_LEVEL` is documented
as ignored by paperwiki runners.

---

### 10.10 Task 9.16 — Update SKILLs to USE runners, not orchestrate them → v0.3.13

**Problem**: even after Task 9.13 lands the `--fold-citations` flag,
the wiki-ingest SKILL.md still has Process Step 4 + Step 5 + the
"Auto-bootstrap mode" section that describe the LLM-side dance.
Without trimming the SKILL prose, the LLM may still try to do the
old behavior even when the new flag is available — partial-fix
regression.

**Solution**: rewrite `skills/wiki-ingest/SKILL.md` Process to be a
runner pass-through for the auto-chain path. Manual interactive
mode keeps body-synthesis. The "Auto-bootstrap mode" section
collapses to a 4-line runner invocation summary.

**SKILL Process (revised)**:

```markdown
## Process

1. **Resolve the source id.** Accept arxiv:1234.5678, s2:<paperId>,
   or a fuzzy title; normalize via paperwiki._internal.normalize.

2. **Run the runner.** Invoke
   `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_ingest
   <vault> <canonical-id>`.

   - **Auto-chain path (digest auto-ingest):** append both
     `--auto-bootstrap` and `--fold-citations`. The runner stubs
     missing concepts AND folds the source citation into each
     affected concept's `sources:` list. NO LLM work in this path.
   - **Interactive path (manual `/paper-wiki:wiki-ingest <id>`)**:
     omit both flags. The runner returns `affected_concepts` and
     `suggested_concepts`; you'll handle the body-synthesis update
     loop in Step 4.

3. **Honor `source_exists`.** If false, stop and ask the user to
   run `/paper-wiki:analyze <id>` first.

4. **Body synthesis (interactive only).** For each name in
   `affected_concepts`: read the existing concept body, fetch the
   new source's content, synthesize an updated body that
   incorporates the new evidence. Write back via
   `MarkdownWikiBackend.upsert_concept(...)`. **Skip this entire
   step on the auto-chain path** — the runner has already folded
   citations; body prose is intentionally NOT regenerated to keep
   auto-chain fast and deterministic.

5. **Append to _log.md.** One line per ingest call.

6. **Summarize.** Print "created N stubs, folded M citations,
   updated K concept bodies" so the digest auto-chain can surface
   per-paper progress.
```

**Acceptance criteria**:

- **AC-9.16.1** `skills/wiki-ingest/SKILL.md` Process is rewritten
  per the structure above.
- **AC-9.16.2** Auto-chain path documents NO Read or Edit tool
  calls.
- **AC-9.16.3** Interactive path keeps body-synthesis.
- **AC-9.16.4** Common Rationalizations gains a row: "I'll Edit the
  concept file directly to fold the citation, faster than calling
  the runner" — wrong, the runner is now the single source of
  truth for citation folding.
- **AC-9.16.5** Smoke test
  `test_wiki_ingest_skill_auto_chain_path_uses_only_runner` pins
  the SKILL.md auto-chain path mentions
  `--auto-bootstrap --fold-citations` and contains no `Edit` or
  `Read` tool references.
- **AC-9.16.6** `skills/digest/SKILL.md` Process Step 8 also
  updates: the auto-chain invocation passes both flags.

**Verification**:

- `pytest -q tests/test_smoke.py -k wiki_ingest_skill_auto_chain`
  green.
- Manual: read SKILL.md auto-chain path; verify no Read/Edit
  language remains.

**Complexity**: M (30–45 min). SKILL prose rewrite (~80 LoC delta);
1 new smoke test; digest SKILL Process Step 8 update.

**Dependencies**:
- Hard: 9.13 (the runner flag must exist for the SKILL to invoke
  it).

**Risk**: low. Risk = users with custom workflows expecting the old
SKILL behavior. Mitigation = interactive path preserved; only
auto-chain changes; CHANGELOG entry calls out the new flag's role.

---

### 10.11 Task 9.17 — Defensive concurrency lock → v0.3.18

**Problem (parent-agent diagnosis from 2026-04-27 v0.3.12 smoke
incident)**:

The user's vault `Wiki/concepts/` directory disappeared between
14:09 and 14:15 during the SKILL flow. The most likely root cause
was the parent agent (the assistant managing the test session)
running `rm -rf ~/Documents/Paper-Wiki/Wiki ...` for fresh-test
cleanup, while the user's session was still mid-flow on a previous
digest run.

This is primarily a parent-agent UX issue ("don't nuke vault while
user is running"), but it also reveals an architectural gap: there
is NO defensive locking. Two parallel digest runs against the same
vault, or a digest mid-flow plus a `rm -rf`, both produce silent
corruption rather than a clear "vault is locked" error.

**Solution**: add `src/paperwiki/_internal/locking.py` with an
`acquire_vault_lock` async context manager that writes a
`.paperwiki.lock` file containing `{pid, host, started_at,
runner_name}` JSON. Releases on exit. Reclaims locks older than
`stale_after_s` (default 300s) so a crashed runner doesn't strand
the vault.

**Locked runners**:

- `wiki_ingest` (acquires for the duration of stub creation +
  citation folding + body synthesis)
- `wiki_compile` (acquires for the index.md regeneration)
- `migrate_sources` (acquires for source-stub format upgrades)
- `obsidian` reporter when `wiki_backend=true` (the digest's source-
  file write path)

**Read-only runners do NOT lock**:

- `wiki_query` (read-only)
- `wiki_lint` (read-only — only reports findings)
- `diagnostics` (read-only — env probes)

**Lock content** (human-readable JSON):

```json
{
  "pid": 12345,
  "host": "MacBook-Pro.local",
  "started_at": "2026-04-27T14:09:00+00:00",
  "runner": "wiki_ingest",
  "vault": "/Users/.../Documents/Paper-Wiki"
}
```

**Held-lock error message**:

```
UserError: vault is locked by pid=12345 (runner=wiki_ingest,
started 2 minutes ago at 14:09:00).

If the previous run is still active, wait for it to finish.
If the previous run crashed, the lock will be reclaimed
automatically after 5 minutes — or remove it manually:

    rm /Users/.../Documents/Paper-Wiki/.paperwiki.lock

Lock content was written to help debug stuck runs.
```

**Acceptance criteria**:

- **AC-9.17.1** `src/paperwiki/_internal/locking.py` exists with
  `acquire_vault_lock(vault_path: Path, *, runner_name: str,
  timeout_s: float = 5.0, stale_after_s: float = 300.0)` async
  context manager.
- **AC-9.17.2** Lock file is `<vault>/.paperwiki.lock` containing
  JSON.
- **AC-9.17.3** Two parallel writers race: one acquires; the
  second raises `UserError` with the held-lock message.
- **AC-9.17.4** Stale lock (> `stale_after_s` old) is reclaimed
  automatically with a `logger.info("vault.lock.reclaimed", ...)`
  line.
- **AC-9.17.5** Lock is released on context exit (including
  exception path).
- **AC-9.17.6** Mutating runners (`wiki_ingest`, `wiki_compile`,
  `migrate_sources`) acquire the lock; read-only runners
  (`wiki_query`, `wiki_lint`, `diagnostics`) do NOT.
- **AC-9.17.7** Obsidian reporter with `wiki_backend=true`
  acquires the lock before per-source writes; releases after the
  loop completes.
- **AC-9.17.8** Unit tests:
  - `test_lock_blocks_concurrent_writers`
  - `test_lock_is_released_on_exception`
  - `test_stale_lock_is_reclaimed`
  - `test_read_only_runner_does_not_lock`

**Verification**:

- `pytest -q tests/unit/_internal/test_locking.py` green.
- Manual: open two terminals, run
  `python -m paperwiki.runners.wiki_ingest <vault> arxiv:X` in
  each simultaneously; second invocation exits 1 with the
  held-lock message. After first completes, second can be re-run
  successfully.

**Complexity**: S-M (30–45 min). One module (~60 LoC); 4 unit
tests; runner integration (4 imports + 4 `async with`).

**Dependencies**: none (independent).

**Risk**: low-medium. Risk = lock contention in user vaults synced
via Dropbox/iCloud (the lock file is created on local disk before
sync sees it). Mitigation = lock file uses `.paperwiki.lock` (dot
prefix; Obsidian doesn't index, most sync tools deprioritize); the
JSON content is small (< 500 bytes); README documents adding
`.paperwiki.lock` to vault-level ignore lists if the user uses git.

---

### 10.12 Task 9.18 — Make Today's Overview synthesis crash-safe → v0.3.18

**Problem**: today's digest SKILL Process orders the steps as
"runner runs → SKILL summarizes top-3 → SKILL synthesizes overview
→ SKILL auto-chains wiki-ingest". If the SKILL crashes (SIGINT,
context-window exhaustion, model timeout) during overview
synthesis, the digest file on disk has the per-paper sections + the
slot marker `<!-- paper-wiki:overview-slot -->` — but the user's
auto-chain never runs and the user has to re-trigger the entire
pipeline.

After Task 9.13 lands and citation folding is in the runner, the
auto-chain becomes deterministic and fast (Python only, no LLM
hangs). So the right ordering is:

1. Runner produces digest file with all slot markers in place.
2. SKILL invokes auto-chain runner (subprocess; deterministic; no
   LLM).
3. SKILL synthesizes per-paper Detailed reports (LLM; may crash).
4. SKILL synthesizes Today's Overview (LLM; may crash).

If 3 or 4 crash, the digest file is on disk, auto-chain has run,
and re-running the SKILL only re-fills the synthesis steps for slot
markers still on disk (idempotent).

**Solution**: document the new ordering in `skills/digest/SKILL.md`
Process. Add a Common Rationalizations row about "I'll synthesize
overview before flushing per-paper sections — saves a roundtrip"
calling out the order matters for crash safety.

**Revised SKILL Process** (key sections):

```markdown
6. **Summarize the outcome.** Read the reporter output paths from
   the recipe and report: how many recommendations were emitted,
   where they were written, and the titles + composite scores of
   the top 3. (No file modifications yet; pure reporting.)

7. **Auto-chain wiki-ingest** (deterministic; runs first to
   finish even if synthesis crashes later). Read the recipe's
   `auto_ingest_top` field. If > 0, immediately invoke
   `paperwiki.runners.wiki_ingest <vault> <canonical-id>
   --auto-bootstrap --fold-citations` for each top paper. NO LLM
   work. Surface `created_stubs` and `folded_citations` counts
   per paper.

8. **Per-paper Detailed report synthesis** (LLM; idempotent).
   For each `<!-- paper-wiki:per-paper-slot:{canonical_id} -->`
   marker still in the digest file, synthesize the Detailed
   report block and replace the marker. If a marker is already
   gone (re-run case), skip it.

9. **Today's Overview synthesis** (LLM; idempotent). Find the
   `<!-- paper-wiki:overview-slot -->` marker. If present,
   synthesize 60-200 words of cross-paper prose and replace the
   marker. If gone (re-run case), skip.
```

The order shift moves auto-chain BEFORE synthesis. If SKILL
crashes during step 8 or 9, the user re-runs the SKILL and only
the un-synthesized slot markers get filled — auto-chain doesn't
re-run because it's already done its job.

**Acceptance criteria**:

- **AC-9.18.1** `skills/digest/SKILL.md` Process Steps 6–9
  documented in the new order: summarize → auto-chain → per-paper
  synthesis → overview synthesis.
- **AC-9.18.2** Common Rationalizations gains a row about
  ordering.
- **AC-9.18.3** Smoke test
  `test_digest_skill_synthesizes_overview_after_pipeline_complete`
  asserts the overview-synthesis step appears AFTER the
  auto-chain step in the SKILL Process.
- **AC-9.18.4** SKILL Verification section adds: "if the SKILL
  is interrupted mid-synthesis, re-running the SKILL re-fills only
  the still-present slot markers; the auto-chain does NOT re-run".

**Verification**:

- `pytest -q tests/test_smoke.py -k overview_after_pipeline` green.
- Manual: run digest, SIGINT during overview synthesis (~step 9);
  re-run SKILL; observe only the overview slot is re-filled,
  per-paper sections preserved verbatim, auto-chain not re-run.

**Complexity**: S (20-30 min). SKILL prose rewrite (~30 LoC delta);
1 smoke test.

**Dependencies**:
- Hard: 9.13 + 9.14 + 9.16 (auto-chain must be deterministic before
  reordering makes sense).

**Risk**: very low. Pure SKILL prose change; no Python edits.

---

### 10.14 Task 9.19 — Quiet `s2.parse.skip` warnings on sparse S2 records → v0.3.21

**Problem (discovered during 2026-04-27 v0.3.18 fresh-vault smoke run)**:

The user's transcript shows three `s2.parse.skip` `WARNING` lines at the
start of every digest:

```
WARNING  | paperwiki.plugins.sources.semantic_scholar:_parse_entry:175 - s2.parse.skip
WARNING  | paperwiki.plugins.sources.semantic_scholar:_parse_entry:180 - s2.parse.skip
WARNING  | paperwiki.plugins.sources.semantic_scholar:_parse_entry:193 - s2.parse.skip
```

These come from
`src/paperwiki/plugins/sources/semantic_scholar.py::_parse_entry`
(lines 175, 180, 193, 198, 219), which warns whenever an S2 record is
missing title, abstract, publication date, authors, canonical id, or
fails model validation. Each branch logs at WARNING.

The dominant case in production is "S2 returned a sparse record" — the
search endpoint indexes lots of papers with no abstract or no
publication date, especially for older / non-arXiv records. This is
the API speaking to us in its native language, not a misconfiguration.

Per the v0.3.12 precedent (`dedup.vault.missing` was downgraded from
WARNING to DEBUG when the dominant case was "fresh vault, expected
empty"), `s2.parse.skip` should follow the same pattern: DEBUG by
default, with one INFO summary line at the end of the fetch loop.

**Solution**:

1. Downgrade every `logger.warning("s2.parse.skip", ...)` call in
   `_parse_entry` to `logger.debug(...)`. Keep the structured key
   (`s2.parse.skip`) and `reason=` field — both useful for `--verbose`
   diagnostics.
2. Track skip count + reason histogram during `_parse_response`. Emit
   one `logger.info("s2.parse.skipped_summary", count=N,
   by_reason={"missing title/abstract": 2, "no authors": 1, ...})`
   line at the end of the fetch loop when `count > 0`. Skip the line
   when `count == 0`.
3. The model-validation branch at line 219 (`reason="model
   validation"`) is rare and indicates a bug in our `Paper` model or
   in S2's schema; KEEP it at WARNING.

**Acceptance criteria**:

- **AC-9.19.1** `_parse_entry` uses `logger.debug` (not `warning`) for
  the four "sparse record" branches: missing title/abstract, bad
  publication date, no authors, no usable id.
- **AC-9.19.2** The `model validation` branch (line 219) stays at
  `logger.warning` — that's a real schema mismatch.
- **AC-9.19.3** `_parse_response` (or the source's `fetch` method)
  emits one `logger.info("s2.parse.skipped_summary", count=N,
  by_reason={...})` line per fetch when at least one entry was
  skipped. The structured payload includes the per-reason histogram
  so power users can debug via `--verbose`.
- **AC-9.19.4** New unit test
  `test_semantic_scholar_skip_branches_log_at_debug_level` (in
  `tests/unit/plugins/sources/test_semantic_scholar.py`) asserts the
  level. Use loguru's testing utilities or `caplog` if loguru is
  configured to propagate to the std logging handler in tests.
- **AC-9.19.5** New unit test
  `test_semantic_scholar_emits_skip_summary_at_info_level` asserts
  the summary line appears once per fetch with `count > 0` and is
  absent when all entries parse cleanly.
- **AC-9.19.6** Existing tests continue to pass — none assert on the
  WARNING level today (verified by `grep -n "s2.parse" tests/`).

**Verification**:

- `pytest -q tests/unit/plugins/sources/test_semantic_scholar.py -k
  "skip_branches_log or skip_summary"` green.
- Manual: on a fresh vault, `/paper-wiki:digest daily` shows zero
  `WARNING | s2.parse.skip` lines on stdout/stderr at the default INFO
  level. With `--verbose`, the per-entry DEBUG lines reappear plus a
  summary INFO line. The structured log key is still
  `s2.parse.skipped_summary` so observability isn't lost.

**Complexity**: S (15–25 min). 4 single-line level changes + 1 summary
emit + 2 unit tests.

**Dependencies**:
- Soft: Task 9.15 (centralized logger) — when 9.15 ships, the
  `--verbose` flag toggles DEBUG visibility cleanly. If 9.15 is in
  flight, 9.19 still works under loguru's default sinks (just less
  ergonomic to debug).
- Independent of every other Phase 9 task.

**Risk**: very low. Pure log-level change. Rollback = revert. No
behavioral change for parsed papers.

---

### 10.15 Task 9.20 — Surface `extract-images` failure details to the user → v0.3.21

**Problem (discovered during 2026-04-27 v0.3.18 fresh-vault smoke run)**:

The auto-chain ran `/paper-wiki:extract-images` for all top-3 papers.
Paper #1 returned 0 images (no figures in source tarball — fine), paper
#2 succeeded with 2 PDF figures (fine), and paper #3 hit a 404 when
fetching the arXiv source tarball:

```
extract_paper_images.failed | error=arXiv 404 for arxiv:2504.12345
```

The runner exited non-zero, the SKILL caught it, and the digest
completed. But the user never sees a clear summary of WHICH paper
failed, WHY, and whether they need to do anything about it. Per the
digest SKILL Process Step 7a today:

> Continue on failure (a 404 or non-arXiv id is not a digest failure);
> surface a one-liner skip reason for `paperclip:` / `s2:` ids.

The SKILL says "surface a one-liner" but in practice, the failure is
silently absorbed. The user has to read the runner stderr to discover
what happened.

**Solution**: extend the digest SKILL Process Step 7a (extract-images
auto-chain) to ALWAYS emit a per-paper summary line in the digest
SKILL's terminal output, regardless of success / failure. Format:

```
Image extraction:
  #1 arxiv:2504.11111 — succeeded (0 figures, source has no figures)
  #2 arxiv:2504.22222 — succeeded (2 figures cached, displayed in Detailed report below)
  #3 arxiv:2504.33333 — skipped (arXiv 404 — paper may be too new or pulled)
```

The summary line lives in the SKILL's terminal output, NOT in the
on-disk digest file (the digest file already shows whether figures
landed via inline teasers). Rationale: the digest file is for the
human reader; the SKILL terminal output is the operator log for that
morning's run.

The implementation is SKILL prose only — extend `skills/digest/SKILL.md`
Process Step 7a to:

1. Capture each `extract_paper_images` runner's exit code + JSON output
   (or stderr on non-zero).
2. Classify: success-with-figures / success-no-figures / network-fail
   / non-arxiv-skip.
3. Emit the summary block before moving to Step 7b (wiki-ingest chain).

**Acceptance criteria**:

- **AC-9.20.1** `skills/digest/SKILL.md` Process Step 7a documents the
  per-paper summary block with the four classifications above
  (success-with-figures / success-no-figures / network-fail /
  non-arxiv-skip).
- **AC-9.20.2** SKILL Verification section adds: "after extract-images
  auto-chain, a per-paper summary block was emitted to the user; no
  failure was silently absorbed".
- **AC-9.20.3** SKILL Common Rationalizations gains a row: "I'll skip
  the summary if all extractions succeeded — it's noise" → "Wrong.
  The user wants a confidence signal that extraction ran. Always emit
  the block; even all-success is useful confirmation."
- **AC-9.20.4** New smoke test
  `test_digest_skill_emits_extract_images_summary` asserts the SKILL
  Process mentions the four classifications and the per-paper format.
- **AC-9.20.5** Manual: run digest with `auto_ingest_top: 3` where one
  arxiv id is known to 404; observe the SKILL terminal emits a
  summary block naming the failed paper + reason; observe the digest
  file is otherwise unaffected.

**Verification**:

- `pytest -q tests/test_smoke.py -k extract_images_summary` green.
- Manual smoke: as above.

**Complexity**: S (20–30 min). SKILL prose only (~20 line addition); 1
smoke test.

**Dependencies**:
- Soft: Task 9.5 (auto image extraction) is the prerequisite — 9.5
  shipped in v0.3.16. 9.20 closes a UX gap left over from 9.5.
- Independent of 9.19 / 9.21 / 9.22 / 9.23 / 9.24.

**Risk**: very low. Pure SKILL prose change; no Python edits.
Rollback = revert.

---

### 10.16 Task 9.21 — Personal recipe migration after v0.3.17 keyword updates → v0.3.20

**Problem (discovered during 2026-04-27 v0.3.18 fresh-vault smoke run)**:

The user's personal recipe at `~/.config/paper-wiki/recipes/daily.yaml`
was generated by `/paper-wiki:setup` back in v0.3.4. v0.3.17 (Task 9.9)
tightened the **bundled** recipe template's `biomedical-pathology`
keyword list — dropped `foundation model`, consolidated WSI variants —
but the **personal copy stays stale**. On today's smoke run, TSMNet
(remote-sensing semantic segmentation, paper #3) was matched into
`biomedical-pathology` because the stale `foundation model` keyword
was still in the user's recipe.

Three plan candidates exist:

- **3a — Setup detection**: setup SKILL detects stale personal recipes
  via heuristic (`foundation model` keyword in `biomedical-pathology`
  bucket) on every invocation → prompts via AskUserQuestion: "Your
  recipe predates v0.3.17 keyword updates. Reconfigure?" Y/N.
  - **Pros**: only fires when the user invokes setup; doesn't pollute
    every digest run; respects user's "I know what my recipe says"
    autonomy.
  - **Cons**: invisible until the user invokes setup again, which most
    users never do after first run; the stale recipe keeps poisoning
    digests for months.

- **3b — Digest warning**: digest SKILL emits a one-line WARNING every
  run if the recipe matches the stale heuristic.
  - **Pros**: visible immediately; user can't miss it.
  - **Cons**: nag fatigue — the user sees the same line every morning
    until they fix it; no remediation path beyond "go re-run setup".

- **3c — Dedicated `migrate-recipe` runner + SKILL**: analogous to
  `migrate-sources`. Runner reads the personal recipe, computes the
  diff against the bundled template's keyword lists, applies surgical
  updates (drop `foundation model` from `biomedical-pathology`,
  consolidate WSI variants), and writes back. Wrap in a
  `/paper-wiki:migrate-recipe` SKILL that surfaces the diff before
  applying. Setup SKILL Branch 1 gains a "Migrate recipe to latest
  template" option.
  - **Pros**: no nag; surgical (preserves user's vault path, S2 key,
    auto_ingest_top, custom 5th topics); gives the user agency to
    review the diff; reusable for future template updates.
  - **Cons**: most complexity (one new runner + one new SKILL +
    setup integration); need to maintain a "what's the latest
    expected keyword list" canonical source.

**Recommendation: 3c (least disruptive long-term)**. The
`migrate-sources` precedent already exists; users understand
"migrate" semantics. The runner stays LLM-free per SPEC §6 (it diffs
two YAML structures and applies surgical edits). Setup invokes
migrate-recipe as part of Branch 1 ("Keep current config" gains a
sub-prompt: "Your recipe predates v0.3.17 — migrate now?").

**Solution** (combining 3a's UX gating + 3c's deterministic runner):

1. **New runner** `paperwiki.runners.migrate_recipe`:
   ```
   python -m paperwiki.runners.migrate_recipe <recipe-path>
        [--dry-run] [--target-version 0.3.17]
   ```
   - Reads the recipe YAML, computes the per-topic keyword diff against
     a canonical "expected keywords" map (lives in
     `paperwiki.config.recipe_migrations` as a versioned dict).
   - In `--dry-run` mode, emits a JSON diff (added / removed keywords
     per topic) without touching the file.
   - In default mode, applies the diff in-place AFTER backing up the
     original to `<recipe-path>.bak.<timestamp>`.
   - Preserves user-edited fields: `vault_path`, `api_key_env`,
     `auto_ingest_top`, custom 5th topic, `top_k`.
   - Emits JSON `{recipe_path, target_version, applied_changes:
     [{topic, removed_keywords, added_keywords}], backup_path}`.
   - Idempotent — re-running on an already-migrated recipe is a no-op
     (`applied_changes: []`).

2. **New SKILL** `skills/migrate-recipe/SKILL.md` (six-section anatomy):
   - Process: invoke runner with `--dry-run` first; show user the
     proposed diff; ask via AskUserQuestion to confirm; invoke runner
     in apply mode; report.
   - Slash command `.claude/commands/migrate-recipe.md`.

3. **Setup SKILL Branch 1 integration**: when the user picks "Keep
   current config", run the migration heuristic check (read the
   recipe, look for `foundation model` in `biomedical-pathology`
   bucket — or any pattern from `recipe_migrations`'s "stale
   markers" list). If stale, ask: "Your recipe predates v0.3.17. Run
   migrate-recipe now?" with three options: "Yes, migrate" / "No,
   keep stale" / "Show me the diff first". Yes hands off to the
   migrate-recipe runner.

**Acceptance criteria**:

- **AC-9.21.1** `paperwiki.runners.migrate_recipe` exists with the
  CLI + JSON contract above. Backups land at
  `<recipe-path>.bak.<YYYYMMDDHHMMSS>` (atomic move; user can
  inspect / restore).
- **AC-9.21.2** `paperwiki.config.recipe_migrations` defines the
  canonical "expected keyword list per template version" map.
  Today's entry is `0.3.17` covering the v0.3.17 bundled-recipe
  keywords. Format: `{"0.3.17": {"biomedical-pathology": {"remove":
  ["foundation model"], "add": ["clinical AI", "digital pathology",
  "histopathology"]}, "vision-multimodal": {...}, ...}}`.
- **AC-9.21.3** Idempotent: re-running migrate-recipe on a fresh
  recipe (already at target version) emits `applied_changes: []` and
  exits 0.
- **AC-9.21.4** Backup files survive across invocations; never
  overwrite (timestamp suffix prevents collision).
- **AC-9.21.5** New SKILL `migrate-recipe` passes the parametrized
  smoke test (`tests/test_smoke.py`).
- **AC-9.21.6** Setup SKILL Branch 1 mentions the migration check;
  smoke test `test_setup_skill_offers_migration_when_recipe_is_stale`
  asserts the prose.
- **AC-9.21.7** Tests:
  - `tests/unit/runners/test_migrate_recipe.py` covers happy path,
    dry-run, idempotent re-run, custom 5th topic preservation,
    backup creation.
  - `tests/test_smoke.py::test_migrate_recipe_skill_anatomy`.
  - `tests/unit/config/test_recipe_migrations.py::test_0_3_17_target_drops_foundation_model_from_biomedical`.

**Verification**:

- `pytest -q tests/unit/runners/test_migrate_recipe.py
  tests/test_smoke.py -k migrate_recipe tests/unit/config/test_recipe_migrations.py`
  green.
- `claude plugin validate .` green.
- Manual: take the user's existing
  `~/.config/paper-wiki/recipes/daily.yaml` (still containing
  `foundation model` under `biomedical-pathology`); run
  `/paper-wiki:migrate-recipe`; observe the diff is shown, the user
  confirms, the file is updated in place, the backup is at
  `daily.yaml.bak.<timestamp>`, and the next digest no longer routes
  TSMNet-style remote-sensing papers into `biomedical-pathology`.

**Complexity**: M (60–90 min). One new runner (~80 LoC), one new
canonical-map module, one new SKILL (six-section), one setup SKILL
prose addition, ~5 unit tests + 2 smoke tests.

**Dependencies**:
- Soft: Task 9.9 (v0.3.17) shipped the keyword tightening that this
  task migrates users toward. Without 9.9 there's nothing to migrate
  toward.
- Independent of 9.19 / 9.20 / 9.22 / 9.23 / 9.24.

**Risk**: medium. The migration diff could lose user-customized
keywords if the diff logic is too aggressive. Mitigation:
`recipe_migrations` map is explicit (only removes keywords listed in
`remove`; only adds keywords listed in `add`); never drops a keyword
the user added beyond the stale-template baseline; backup file is
always created so the user can restore. Document the conservative
diff strategy in CHANGELOG.

Rollback: `git revert` removes the new runner + SKILL. Personal
recipes already migrated by users keep their post-migration shape
(harmless — the new keyword lists are strictly better). Backup files
on disk can be restored manually if any user lost a custom keyword
they want back.

---

### 10.17 Task 9.22 — Inline figures in synthesized Detailed reports → v0.3.19

**Problem (discovered during 2026-04-27 v0.3.18 fresh-vault smoke run)**:

The user's transcript: extract-images succeeded for paper #2, saving 2
PDF figures to `Wiki/sources/<id>/images/`. The reporter's
`_try_inline_teaser` (`obsidian.py:185-203`) embedded ONE of those
figures at the per-paper card level (between the metadata callout and
the Abstract heading). But the **Detailed report block** that the SKILL
synthesizes (`### Detailed report` — Why this matters / Key takeaways /
Score reasoning) does NOT include any figures. Result: figures are
"extracted but invisible inside the synthesized prose".

The user's words: "even when extract-paper-images succeeds, those
figures are NOT inlined into the Detailed report block in the daily
digest".

Two architectural notes:

1. The reporter already does ONE figure embed per recommendation via
   `_try_inline_teaser` — first alphabetically-sorted file matching
   `_FIGURE_EXTS`, embedded as `![[<id>/images/<name>|700]]` between
   the metadata callout and the Abstract. **This is the "card
   teaser" — distinct from the SKILL-synthesized Detailed report.**
2. The Detailed report is filled by the digest SKILL Process Step 8
   (the per-paper synthesis pass that fills
   `<!-- paper-wiki:per-paper-slot:{canonical_id} -->`). Today, the
   contract is plain prose only — no embeds.

**Solution**: extend the digest SKILL Process Step 8 contract so that
when synthesizing the Detailed report for a paper whose
`Wiki/sources/<id>/images/` directory has at least one extracted image,
the synthesized prose ALSO embeds 1–2 figure references using Obsidian's
`![[<path>|600]]` syntax.

The SKILL prose must specify:

- After "Key takeaways" and BEFORE "Score reasoning", insert a
  `**Figures.**` line (or similar minimal heading inside the
  synthesized block) followed by 1–2 `![[<path>|600]]` embeds.
- Figure selection heuristic: pick the top 1 file by alphabetical sort
  IF the directory has 1–2 figures total; pick the top 2 by
  alphabetical sort IF the directory has 3+ figures (so we never
  embed all 7 architecture diagrams, just a teaser + a follow-up). If
  the alphabetical sort surfaces a file named like `fig1.*`,
  `figure_1.*`, `teaser.*`, prefer it over generic names.
- Distinct from card teaser: the card teaser embeds `|700` (full
  width); the Detailed-report figures embed `|600` (smaller, clearly
  in-section). Sizes are explicit so users can visually distinguish.
- If the directory is empty / missing (extract-images failed or
  non-arxiv id), skip figures silently.
- The path uses the source's filename namespace — `<source_filename>`
  comes from `_canonical_id_to_filename`, e.g. `arxiv_2506.13063` —
  matching what the reporter already uses for the card teaser.

The reporter's `_try_inline_teaser` is left UNCHANGED — it still does
the card teaser. Both the card teaser and the Detailed-report
embeds appear in the same digest, deliberately. (Card teaser exists
even on re-runs without re-synthesis; Detailed-report figures only
appear after synthesis.)

**Smoke test contract**: assert the SKILL Process step 8 documents
this behavior; assert that the SKILL Common Rationalizations forbids
"I'll skip the figures because they're already in the card teaser".

**Acceptance criteria**:

- **AC-9.22.1** `skills/digest/SKILL.md` Process Step 8 documents the
  Figures embed contract: Figures section appears between Key
  takeaways and Score reasoning when the source's images directory
  has at least one figure; embed 1–2 figures via `![[<path>|600]]`;
  apply the alphabetical-sort + `fig1`/`teaser` preference heuristic.
- **AC-9.22.2** SKILL Common Rationalizations gains a row: "Card
  teaser already shows a figure — Detailed report doesn't need one"
  → "Wrong. Card teaser is decorative; Detailed-report figures
  ground the synthesized claims (Why-this-matters / Key-takeaways).
  Different functions; both belong."
- **AC-9.22.3** SKILL Common Rationalizations gains another row: "I'll
  embed all 7 architecture diagrams to be thorough" → "Wrong. 1–2
  figures max per Detailed report. Use the heuristic. Excessive
  figures clutter the digest."
- **AC-9.22.4** SKILL Verification adds: "Each Detailed report
  section that has a corresponding `Wiki/sources/<id>/images/`
  directory with files contains at least one
  `![[<source_filename>/images/...|600]]` embed."
- **AC-9.22.5** New smoke test
  `test_digest_skill_embeds_figures_in_detailed_report` asserts the
  SKILL Process documents the embed contract + the alphabetical-sort
  heuristic + the `|600` size convention.
- **AC-9.22.6** Manual: run digest with `auto_ingest_top: 3` against a
  fresh vault. After auto-chain + per-paper synthesis, open one of
  the top-3 papers' Detailed report sections in Obsidian; confirm
  it has 1–2 inline `![[...]]` embeds rendering the actual extracted
  figures.

**Verification**:

- `pytest -q tests/test_smoke.py -k embeds_figures_in_detailed`
  green.
- Manual smoke: as above.

**Complexity**: S–M (30–45 min). SKILL prose only — ~30 line addition
to Process Step 8 + 2 Common Rationalizations rows + 1 smoke test.
No Python edits.

**Dependencies**:
- Hard: Task 9.4 (per-paper synthesis pass shipped in v0.3.16). The
  Detailed report wouldn't exist to embed into otherwise.
- Hard: Task 9.5 (auto image extraction shipped in v0.3.16). The
  images wouldn't be on disk to embed.
- Soft: Task 9.20 (extract-images failure UX). If 9.20 ships first,
  the user has clear signal when no images are available; if 9.20
  ships later, the synthesis silently skips figures (the AC-9.22.1
  contract already covers this).

**Risk**: low. SKILL prose change. Rollback = revert SKILL.md;
existing Detailed reports keep their figures (markdown is plain
text); subsequent digests synthesize without figures.

**Note**: this is the highest-leverage finding per user impact (per
the input brief). The user explicitly called out this gap in the v0.3.18
transcript review.

**Surprised-by-codebase note**: `_try_inline_teaser` already does
"first alphabetical figure embedded at the card level" — the closest
existing prior art to this task. The heuristic is the same; only the
location (card vs synthesized Detailed report) and size (`|700` vs
`|600`) differ. Consider extracting the file-selection helper into a
shared `_pick_teaser_image(images_dir, *, count: int = 1)` function
in `paperwiki._internal.figures` so both the reporter and (if we ever
move this from SKILL prose into runner output) future code share the
heuristic — but this is OPTIONAL polish, not part of the v0.3.19
slice. SKILL prose can describe the heuristic without code reuse.

---

### 10.18 Task 9.23 — Insightful Score reasoning (synthesized, not transcribed) → v0.3.20

**Problem (discovered during 2026-04-27 v0.3.18 fresh-vault smoke run)**:

The user's transcript shows the synthesized Score reasoning today:

> **Score reasoning.** 0.79 — relevance 0.99 (vision-language +
> foundation-model + agent reasoning), novelty 0.98 (parallel-exploration
> RL for LLM agents is largely unexplored), momentum 0.50 (just
> published), rigor 0.50.

The user's verbatim feedback: "this is not great". And they're right —
this is just a paraphrase of the four sub-scores that are already
visible in the metadata callout one section above. The user could
compute that themselves. The synthesis adds zero insight.

Better shape would be 1–2 sentences of *interpretation*:

> **Score reasoning.** Punches above its weight: novelty is genuinely
> high (parallel-exploration RL on LLM agents is largely unexplored
> ground), and the dataset/code release adds rigor signal that momentum
> can't yet — expect this to age into a citation magnet within 6–12
> months.

Or:

> **Score reasoning.** Hits the relevance ceiling but rigor is held
> back by being a brand-new arXiv release with no peer review or
> replications yet — treat the headline numbers cautiously until
> follow-up work appears.

Or even shorter:

> **Score reasoning.** High novelty + high relevance, but momentum and
> rigor lag because it's brand-new — score will settle as citations
> accrue.

The contract change is from "transcribe the four sub-scores" to
"synthesize an interpretation of why this paper scores the way it
does, what it means, and what to expect".

**Solution**: rewrite the digest SKILL Process Step 8 contract for
the "Score reasoning" line. New shape requirements:

1. **1–2 sentences** (not bullet-styled list of sub-scores).
2. **Actively interpret WHY the score is what it is**, not just
   transcribe. Use the four sub-scores as evidence backing the
   interpretation, not as the content itself.
3. **Acknowledge limits** (e.g. "rigor 0.50 because brand-new, no
   replications" — make the rigor=0.50 line MEAN something, don't just
   restate it).
4. **Cite specific topic matches when relevance is high** (e.g.
   "matches all 4 of your topics" rather than listing them
   individually — the user can read the metadata callout above).
5. **Forbid pure number-restating** ("0.79 — relevance 0.99, novelty
   0.98, momentum 0.50, rigor 0.50") via Common Rationalizations row.

**Acceptance criteria**:

- **AC-9.23.1** `skills/digest/SKILL.md` Process Step 8 contract for
  "Score reasoning" updated: 1–2 sentences, interpretive (not
  transcriptive), acknowledges limits, cites specific evidence.
- **AC-9.23.2** SKILL Common Rationalizations gains a row: "I'll
  just list the sub-scores — it's accurate." → "Accurate but
  useless. The user can read the metadata callout. Synthesize an
  interpretation: WHY this score? WHAT does it mean? WHAT to expect
  next?"
- **AC-9.23.3** SKILL Common Rationalizations gains a second row: "If
  the score is moderate (e.g. 0.65), there's nothing interesting to
  say." → "Wrong. Moderate scores are the most interesting — explain
  the trade-off (e.g. 'Strong topic match but momentum lags because
  this is a re-implementation of older work; useful for replication
  studies, less so for cutting-edge tracking')."
- **AC-9.23.4** SKILL Verification section adds: "Each Score
  reasoning sentence interprets WHY (not just WHAT); does not consist
  solely of the four sub-score numbers; references at least one
  specific signal beyond the sub-score themselves (e.g. topic match,
  recency, dataset release)."
- **AC-9.23.5** SKILL Red Flags gains: "Score reasoning starts with
  the composite number and just restates the four sub-scores in
  parentheses → STOP. The user has the metadata callout. Synthesize
  an interpretation."
- **AC-9.23.6** New smoke test
  `test_digest_skill_score_reasoning_is_interpretive_not_transcriptive`
  asserts the SKILL Process contract mentions "interpret", "1–2
  sentences", and the forbidden number-restating pattern.
- **AC-9.23.7** Manual: run digest, inspect 3 Score reasoning lines
  across different score brackets (high / medium / low). Each should
  read as opinion-bearing interpretation, not number-paraphrase.

**Verification**:

- `pytest -q tests/test_smoke.py -k score_reasoning_interpretive`
  green.
- Manual: as above. (LLM output is human-judged; the smoke test only
  pins the SKILL contract, not the synthesized prose itself.)

**Complexity**: S (20–30 min). SKILL prose only — rewrite ~10 lines
of Process Step 8; add 2 Common Rationalizations rows + 1 Red Flag +
1 smoke test.

**Dependencies**:
- Hard: Task 9.4 (per-paper synthesis pass shipped in v0.3.16). Score
  reasoning is one of three blocks inside the Detailed report.
- Independent of 9.19 / 9.20 / 9.21 / 9.22 / 9.24.

**Risk**: low. Pure SKILL prose change; LLM output quality is variable
(this is the same risk as 9.3 / 9.4). Mitigation: AC-9.23.4 +
AC-9.23.5 give the SKILL clear failure signals. Rollback = revert.

---

### 10.19 Task 9.24 — Detailed reports gated by `auto_ingest_top` → v0.3.19

**Problem (discovered during 2026-04-27 v0.3.18 fresh-vault smoke run)**:

The user's recipe says `auto_ingest_top: 3` — meaning only the top 3
papers should get the heavyweight treatment (auto-ingest into wiki,
image extraction, deep synthesis). But v0.3.18's Process Step 8
synthesizes Detailed reports for **ALL papers** in the digest (10 in
this case). The user's reading: "Why are #4 through #10 also getting
deep treatment when I only asked for top-3 ingest?"

Two interpretations of the contract exist:

- **Interpretation A**: `auto_ingest_top` ONLY controls the wiki-ingest
  auto-chain. Detailed reports are independent — every paper gets one
  because that's the digest's "rich" mode.
- **Interpretation B**: `auto_ingest_top` is a "depth-of-treatment"
  knob. Top-N papers get deep (ingest + images + Detailed report);
  rest get light (abstract + metadata only, slot stays empty or shows
  brief 1-line teaser).

Per the input brief: **the user's expectation aligns with
Interpretation B**. Adopting B is also more consistent with the
overall mental model: the recipe declares "ingest 3 papers deeply"
and the SKILL respects that envelope across all expensive operations
(LLM synthesis, image extraction, wiki-ingest).

**Solution**: re-shape the contract to Interpretation B.

Two implementation options for the per-paper slot below top-N:

- **Option 1 (simpler)**: reporter still emits the
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->` marker for ALL
  papers; SKILL only fills slots for top-N and replaces the rest with
  a one-line teaser:
  ```
  _Run `/paper-wiki:analyze <canonical-id>` for a deep dive on this paper._
  ```
- **Option 2 (cleaner)**: plumb `auto_ingest_top` through to the
  reporter so the marker is only emitted for top-N papers; sub-top-N
  papers get the teaser line written by the reporter directly. This
  requires the reporter to know `auto_ingest_top`, which is currently
  recipe-level config not reporter param.

**Recommendation: Option 1**. No reporter plumbing required; the SKILL
already reads the recipe; the SKILL's slot-fill loop just adds a
bracket on `index <= auto_ingest_top`. Rollback is also simpler.

(If Option 2 ends up cleaner during implementation — e.g. for a future
"reporters drive everything, SKILLs only handle re-fills" refactor —
it can be revisited; not in scope for v0.3.19.)

**Acceptance criteria**:

- **AC-9.24.1** `skills/digest/SKILL.md` Process Step 8 documents the
  top-N gating: per-paper Detailed report synthesis only for the top
  `min(auto_ingest_top, top_k)` papers; remaining slots get the
  one-line teaser referenced above.
- **AC-9.24.2** When `auto_ingest_top == 0` (no auto-chain), Step 8
  fills ALL slots with the teaser only (no synthesis at all). The
  digest is "light mode" — abstract + metadata + teaser link only.
- **AC-9.24.3** SKILL Common Rationalizations gains a row: "I
  synthesized Detailed reports for all 10 papers — more value for
  the user." → "Wrong. `auto_ingest_top` controls treatment depth.
  Only top-N get deep. The rest get a teaser pointing at
  `/paper-wiki:analyze`. Respect the user's depth budget."
- **AC-9.24.4** SKILL Red Flags gains: "I synthesized Detailed
  reports for all N papers when `auto_ingest_top` is 3 → STOP.
  `auto_ingest_top` is the depth-of-treatment envelope. Top-3 deep,
  rest teaser."
- **AC-9.24.5** SKILL Verification section adds: "After Step 8,
  exactly `min(auto_ingest_top, top_k)` per-paper slots have synthesized
  Detailed reports; the remaining slots have the teaser line."
- **AC-9.24.6** New smoke test
  `test_digest_skill_gates_detailed_reports_by_auto_ingest_top`
  asserts the SKILL Process documents the gating behavior +
  references `auto_ingest_top` explicitly + names the teaser line.
- **AC-9.24.7** Manual: run digest with `auto_ingest_top: 3` and
  `top_k: 10`. Inspect the digest file: top-3 papers have full
  synthesized Detailed reports; papers #4–#10 have the one-line
  teaser; no marker comments remain.
- **AC-9.24.8** Manual edge case: run digest with `auto_ingest_top: 0`
  and `top_k: 10`. All 10 slots get the teaser; no synthesis ran.

**Verification**:

- `pytest -q tests/test_smoke.py -k gates_detailed_reports_by_auto_ingest_top`
  green.
- Manual: as above.

**Complexity**: S (25–35 min). SKILL prose only (~25 line addition to
Process Step 8); 1 smoke test; 0 Python edits.

**Dependencies**:
- Hard: Task 9.4 (per-paper synthesis pass shipped in v0.3.16).
- Soft: Task 9.22 (Detailed-report figures). The figure-embed contract
  in 9.22 ALSO only fires for top-N papers (since only top-N get
  synthesized Detailed reports). 9.22 + 9.24 should ship together
  for coherent semantics.
- Independent of 9.19 / 9.20 / 9.21 / 9.23.

**Risk**: medium. Users who liked all-paper Detailed reports as a
"free quality bump" will see them disappear for #4–#10. Mitigation:
the teaser line names `/paper-wiki:analyze <id>` so manual deep dives
are one command away; CHANGELOG entry calls out the contract shift
explicitly; recipe doc note that `auto_ingest_top` is now a
depth-of-treatment knob, not just an ingest gate.

Rollback: `git revert` on SKILL.md. Future digests regress to
all-paper synthesis; existing digest files in user vaults are
unchanged (markdown is plain text). Low-cost rollback.

**Note**: this is the second-highest-leverage finding per user
impact (after 9.22). The depth-of-treatment mismatch is a clear
contract bug — the recipe says "3" but the SKILL spent compute on
all 10.

---

### 10.20 Task 9.25 — Improve `extract-paper-images` per evil-read-arxiv reference → v0.3.20

**Problem (concrete, from v0.3.18 smoke + user follow-up)**:
The user pointed at <https://github.com/juliye2025/evil-read-arxiv> as a
reference. They have `~/Projects/evil-read-arxiv/extract-paper-images/`
locally — its `SKILL.md` + `scripts/extract_images.py` document a
3-priority extraction strategy that recovers MANY more figures than our
current runner.

Failure modes our runner exhibits today (per real smoke):

- **#1 in v0.3.18 smoke**: source bundle existed but had ZERO figures
  in the `pics/figures/fig/images/img` directories — got 0 images even
  though the paper has figures (likely as inline TikZ or as standalone
  PDFs at the source root).
- Our `_internal/arxiv_source.py` only walks the 6 figure-dir names.
  When authors don't use those (they put figures next to `.tex` at root,
  or use TikZ), we miss everything.
- We accept `.pdf` figure files but don't convert them to PNG, so
  Obsidian renders only the first page of multi-page PDFs and never as
  scaled-up rasters.

**Solution — adopt evil-read-arxiv's 3-priority chain**:

1. **Priority 1 (existing — keep)**: walk `pics/figures/fig/images/img`
   dirs in the arXiv source bundle for figure files (`.png`, `.jpg`,
   `.jpeg`, `.gif`, `.webp`, `.pdf`). Apply existing min-size filter
   (>200px on at least one axis, preserves v0.3.16 commit `c7d5df4`).

2. **Priority 2 (NEW)**: scan the source bundle ROOT (not just figure
   dirs) for standalone `.pdf` figure files (filename pattern: doesn't
   look like `<paper>.pdf` or `main.pdf` — heuristic: anything that
   isn't the paper's own compiled PDF). Convert each to PNG via PyMuPDF
   (`fitz.open(pdf).get_pixmap(matrix=fitz.Matrix(3, 3))`). One PNG per
   page; multi-page figures become `<figname>_page1.png`, `_page2.png`.

3. **Priority 3 (NEW)**: if priorities 1+2 yield <2 figures, detect TikZ
   by grepping `.tex` files for `\begin{tikzpicture}` or
   `\usepackage{pgfplots}`. When TikZ is the rendering source, the
   compiled paper PDF is the only place those figures exist. Fall back
   to **caption-aware crop** of the paper PDF:

   ```python
   import fitz
   doc = fitz.open(paper_pdf)
   for page in doc:
       blocks = page.get_text("blocks")
       for b in blocks:
           text = b[4]
           if re.match(r"^\s*Figure\s+\d+\s*[:.]", text):
               caption_bottom = b[3]
               # Find figure top: walk up until we hit a non-image block
               # or use a simple heuristic — top of page or N% above caption
               clip = fitz.Rect(margin, fig_top, page_w - margin, caption_bottom + 5)
               pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip)
               pix.save(out / f"{paper_id}_fig{n}.png")
   ```

   This is the "TikZ-cropped" source class. Cap at top-K cropped figures
   to avoid over-extraction on long papers.

4. **Generate `images/index.md`** alongside extracted files with a
   per-figure manifest: source class (`arxiv-source` / `pdf-figure` /
   `pdf-extraction` / `tikz-cropped`), filename, path, size, format.
   The `extract_paper_images` runner already emits a JSON list; expand
   it to also write the index file. The wiki-ingest SKILL can use this
   manifest when 9.22 inlines figures into Detailed reports (pick the
   first non-`tikz-cropped` figure as the "teaser" since cropped figures
   tend to look choppy at small sizes).

5. **Min-size filter applies after extraction**: drop any output PNG
   <200px on both axes (Priority 2 PDFs at 3× rendering should always
   pass; Priority 3 crops sometimes produce slivers when the heuristic
   misjudges the figure top).

**Files to touch**:

- `src/paperwiki/_internal/arxiv_source.py` — add Priority 2 + Priority 3
  detection logic; reuse existing `_FIGURE_DIRS` for Priority 1.
- `src/paperwiki/runners/extract_paper_images.py` — emit `index.md`
  alongside JSON; surface source-class breakdown in JSON output
  (`{"sources": {"arxiv-source": 2, "pdf-figure": 1, "tikz-cropped": 0}}`).
- `pyproject.toml` — add `pymupdf>=1.24` to dependencies. (PyMuPDF is
  AGPL but offers a commercial license; for a GPL-3.0 plugin it's
  compatible — note in CHANGELOG.)
- `tests/unit/_internal/test_arxiv_source.py` — fixtures for each
  priority path. Use minimal-bytes synthetic source bundles (no real
  arXiv calls); for Priority 3 use a tiny PDF with one fake "Figure 1:"
  caption block.

**Acceptance criteria**:

- **AC-9.25.1**: `pyproject.toml` declares `pymupdf>=1.24`; `pytest -q`
  runs successfully without network calls.
- **AC-9.25.2**: Priority 2 — when source bundle has a standalone
  `pipeline.pdf` at root (not in `pics/`), the runner converts it to
  `pipeline_page1.png` (and additional pages if multi-page); the JSON
  output `sources` map increments `pdf-figure` count.
- **AC-9.25.3**: Priority 3 — when source bundle has only `.tex` files
  with `\begin{tikzpicture}` and a paper PDF, the runner crops the
  paper PDF at "Figure N:" caption boundaries and saves
  `<paper-id>_fig1.png`, `_fig2.png`, …; JSON `sources["tikz-cropped"]`
  reflects the count.
- **AC-9.25.4**: `images/index.md` exists alongside the extracted files
  with per-figure source class.
- **AC-9.25.5**: Min-size filter drops sub-200px outputs from any
  priority path (regression test: synthesize a 50px-wide PDF page →
  not extracted).
- **AC-9.25.6**: Smoke test asserts the runner picks the first
  non-`tikz-cropped` figure as the "teaser" (consistency contract for
  9.22's inline-figure pick).

**Verification**:

- `pytest -q tests/unit/_internal/test_arxiv_source.py` covering each
  priority + min-size edge.
- `pytest -q tests/unit/runners/test_extract_paper_images.py` covering
  the index.md emission + JSON shape.
- Manual smoke (after v0.3.20 ships): on the v0.3.18 transcript's #1
  paper that gave 0 images — re-run extract-paper-images directly and
  confirm Priority 2 or 3 yields ≥1 figure.

**Complexity**: **M-L** — PyMuPDF dependency adds ~15 MB to the venv;
caption-aware cropping is the trickiest algorithm in the runner so far
(needs careful figure-top heuristics so we don't crop prose). Budget
90–120 min including TikZ fixture construction.

**Dependencies**:

- Hard: none. The runner is independently improvable.
- Soft: 9.22 (figures inline in Detailed reports) — this task makes
  9.22 actually have figures to inline for many more papers. Worth
  shipping 9.22 first (v0.3.19), then 9.25 (v0.3.20), so users see the
  layered improvement on consecutive digest runs.

**Risk**: medium. PyMuPDF's PDF parsing can fail on malformed PDFs,
producing zero output silently. Mitigation: surface per-paper errors
via stderr log (`extract_paper_images.failed` already exists in the
runner) AND accumulate a count in the JSON output. Caption-cropping
heuristic can mis-cut on dense LaTeX layouts; cap output at K=8 figures
per paper so a misbehaving paper can't fill the disk. Document the
known limits in the SKILL.

**Reference (READ FIRST)**:

- `/Users/fangyi/Projects/evil-read-arxiv/extract-paper-images/SKILL.md`
  — full 3-priority strategy + caption-crop code snippet (lines 80–120).
- `/Users/fangyi/Projects/evil-read-arxiv/extract-paper-images/scripts/extract_images.py`
  — production implementation: `find_figures_from_source` (Priority 1+2),
  `extract_pdf_figures` (Priority 3 entry point), `extract_from_pdf_figures`
  (the per-figure PDF→PNG conversion). Use as the architectural blueprint;
  port the algorithm into `paperwiki._internal/arxiv_source.py` rather
  than inline a CLI script (we keep our runner protocol per SPEC §6).

---

### 10.21 Task 9.26 — `paperwiki` CLI for in-place plugin upgrade → v0.3.20

**Problem (concrete, from every release smoke session)**:
Every release the user has tried to upgrade through `/plugin install
paper-wiki@paper-wiki` and consistently hits "Plugin already installed
globally". Claude Code 2.1.119's plugin manager has four broken upgrade
paths:

- `/plugin install paper-wiki@paper-wiki` — short-circuits when an
  `installed_plugins.json` entry exists. Does NOT compare versions.
- `/plugin update paper-wiki` — returns empty output (broken in 2.1.119).
- `/plugin marketplace update paper-wiki` — refreshes the marketplace
  clone but never re-emits cache files, so active install stays old.
- `/plugin uninstall paper-wiki@paper-wiki` — does NOT delete cache;
  only writes a `false` override to `settings.local.json`.

So the only currently-working upgrade flow requires the user to run a
5-line shell incantation: nuke cache, prune `installed_plugins.json`,
prune both `settings.json` `enabledPlugins`, then `/plugin install`
from a fresh session. **This does not scale to other users** — paper-wiki
cannot be told "here's how to upgrade" without a manual JSON-editing
ritual.

OMC sidesteps this entirely by shipping its own `omc update` CLI that
runs OUTSIDE Claude Code (architectural reference at
`~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.2/src/cli/index.ts`
and `scripts/`). paper-wiki should follow the same pattern.

**Solution**: ship a top-level `paperwiki` console-script entry-point
that bundles the upgrade dance into a single command:

```bash
paperwiki update
```

What it does:

1. Resolve marketplace clone path: `~/.claude/plugins/marketplaces/paper-wiki/`
   by default, or via `--marketplace-dir <path>`.
2. `git -C <clone> fetch --tags && git -C <clone> pull --ff-only` —
   refresh the marketplace clone.
3. Read `<clone>/.claude-plugin/plugin.json` → newest version available.
4. Read `~/.claude/plugins/installed_plugins.json` → currently-cached
   version.
5. If equal: print `paper-wiki is already at <version>` and exit 0.
6. If marketplace > cache:
   - Rename `~/.claude/plugins/cache/paper-wiki/paper-wiki/<old>/` →
     `<old>.bak.<UTC-timestamp>` (preserve, don't delete — user can
     restore if upgrade breaks).
   - Drop `paper-wiki@paper-wiki` entry from `installed_plugins.json`.
   - Drop `paper-wiki@paper-wiki` from `settings.json` `enabledPlugins`
     and `settings.local.json` `enabledPlugins`.
   - Print: "paper-wiki upgraded marketplace 0.3.18 → 0.3.19 (cache backed
     up to 0.3.18.bak.<ts>). Next: /exit any running session, then
     `claude` → `/plugin install paper-wiki@paper-wiki` for the fresh
     install."
7. Exit codes: 0 success/no-op, 1 git/filesystem error, 2 marketplace
   clone missing (print "run `/plugin marketplace add kaneyxx/paper-wiki`
   first").

Additional subcommands (low cost, ship together):

- `paperwiki status` — prints cache version, marketplace version,
  settings enabledPlugins state. For debugging "is it installed?".
- `paperwiki uninstall` — opposite direction: removes cache + JSON
  entries cleanly. The thing `/plugin uninstall` was supposed to do.

**Files to touch**:

- `pyproject.toml` — add `[project.scripts] paperwiki = "paperwiki.cli:main"`.
- `src/paperwiki/cli.py` (new) — Typer app with `update`, `status`,
  `uninstall` subcommands. Reuses `paperwiki._internal.logging`
  (configure_runner_logging from 9.15) for `--verbose`.
- `README.md` — replace "manual JSON cleanup" upgrade doc with
  `paperwiki update` as the primary upgrade path. Move manual flow
  into a "fallback if uv/pip not on PATH" footnote.
- `tests/unit/test_cli.py` (new) — Typer-runner tests with tmp_path
  fixtures simulating cache/JSON state.

**Acceptance criteria**:

- **AC-9.26.1** `paperwiki --help` prints subcommand list including
  `update`, `status`, `uninstall`.
- **AC-9.26.2** `paperwiki update` against a stale cache renames cache
  dir to `.bak.<UTC-timestamp>`, removes JSON entries, prints success +
  next-steps, exits 0. Idempotent — re-running on the same state is a
  no-op.
- **AC-9.26.3** `paperwiki update` against an up-to-date cache prints
  `paper-wiki is already at <version>` and exits 0 without mutating
  any files.
- **AC-9.26.4** `paperwiki update` against missing marketplace clone
  exits 2 with actionable message naming
  `/plugin marketplace add kaneyxx/paper-wiki`.
- **AC-9.26.5** `paperwiki status` prints a 3-line state report
  (cache version / marketplace version / enabledPlugins yes-or-no).
- **AC-9.26.6** `paperwiki uninstall` removes cache + JSON entries;
  smoke verifies subsequent `/plugin install` does fresh install path
  (the very thing `/plugin uninstall` should have done).
- **AC-9.26.7** README's "Upgrading" section names `paperwiki update`
  as the primary path; the manual JSON-editing flow stays as a
  fallback footnote only.

**Verification**:

- `pytest -q tests/unit/test_cli.py` — mocked filesystem (tmp_path)
  with synthetic `~/.claude/plugins/{cache,marketplaces}/paper-wiki`
  + JSON state. Use `typer.testing.CliRunner`. Cover all four paths:
  stale cache (success), up-to-date (no-op), missing clone (exit 2),
  malformed JSON (exit 1).
- Smoke test pins `paperwiki update --help` shape in `test_smoke.py`.
- Manual smoke (post-ship): on the user's actual machine, run
  `paperwiki update` → fresh `claude` → `/plugin install paper-wiki@paper-wiki`
  succeeds without "already installed" short-circuit.

**Complexity**: **S-M** (~30-45 min). Pure Python CLI + filesystem
mutation; no LLM, no async, no network beyond `git pull` subprocess.

**Dependencies**:

- Hard: none. Independent of 9.25 (image extraction quality).
- Soft: ships in same release (v0.3.20) as 9.25 because both touch the
  user-facing release flow; CHANGELOG can document them together. If
  9.25 takes longer than budget, 9.26 ships alone — fixing the upgrade
  path is more urgent than image quality.

**Risk**: **low**. The CLI mutates files paper-wiki already mutates
manually each release; preserving the old cache as `.bak.<timestamp>`
makes the operation reversible. Risk row: malformed
`installed_plugins.json` (user-edited) → CLI must `cp <path>
<path>.bak` before mutating and exit 1 with a diff if write fails.

**Rollback**: `git revert` on the cli + pyproject + README changes.
The existing manual upgrade flow continues to work for any user who
has the v0.3.x docs cached.

**Reference**:

- OMC's update flow at
  `~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.2/src/cli/index.ts`
  + `scripts/setup-progress.sh`. Architecturally same shape: refresh
  clone → sync cache → prompt restart. Port the algorithm; do not port
  the TypeScript. Stay Python-native to fit our `pyproject.toml`
  install path.

---

### 10.13 Out of scope (Phase 9)

- Phase 8 PDF text extraction (still candidate; per-paper synthesis in
  9.4 leans on the abstract only — we'll know after v0.3.16 ships
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
