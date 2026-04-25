# paper-wiki — Foundation Plan

**Date**: 2026-04-25
**Repo**: https://github.com/kaneyxx/paper-wiki
**Status**: Greenfield (only LICENSE GPL-3.0 + .git committed)

---

## Mission Statement

`paper-wiki` is **a personal research wiki builder** that turns the firehose of academic papers into a curated, queryable, knowledge-accumulating wiki. It is **not** a daily paper feed — it is a long-horizon knowledge base.

### Positioning vs other tools

| Tool | Primary use case | Output |
|------|------------------|--------|
| arxiv-sanity | Personalized daily feed | Web list |
| Zotero | Reference manager | Library |
| `evil-read-arxiv` (inspiration) | Daily Obsidian recommendations | Daily note |
| **`paper-wiki`** (this) | **Long-term research wiki accumulation** | **Living wiki + plugin pipeline** |

This positioning is intentional — it differentiates the project's SEO surface (search terms: "research wiki", "personal knowledge base", "paper wiki", "academic plugin"), avoiding direct competition with `evil-read-arxiv` (search terms: "daily paper recommendations", "obsidian arxiv").

## Goals

1. **Architecturally distinct** — Plugin-pipeline architecture (not procedural scripts). Different naming, different module layout, different abstractions. Clean-room (zero code copy).
2. **English-first** — All code, docstrings, logs, CLI help, default templates, README in English. Other languages via locale plugins.
3. **SKILL-first plugin packaging** — Ships as both:
   - PyPI package: `pip install paper-wiki`
   - Claude Code plugin bundle: `.plugin` manifest with embedded SKILLs
4. **Acknowledged inspiration** — Short README acknowledgment + CITATION.cff. Dignified, not buried.

## Non-Goals

- ❌ Not a fork of `evil-read-arxiv` (no git history relation, no code copy)
- ❌ Not a daily-feed tool by default (daily mode is one of many recipes)
- ❌ Not Obsidian-only (Obsidian is one reporter plugin)
- ❌ Not Chinese-first (Chinese available via i18n, but not the default)

## Acceptance Criteria

### Architecture distinctness (AC-A)
- **AC-A.1**: No code, function names, variable names, file names, or configuration keys identical to `evil-read-arxiv`. Zero copy-paste.
- **AC-A.2**: Top-level layout uses `src/paperwiki/{core,plugins,cli,config,skills}/`, **not** flat skill directories.
- **AC-A.3**: Core domain follows pipeline pattern: `Source → Filter → Scorer → Reporter`. Original repo is procedural — clearly different paradigm.
- **AC-A.4**: Configuration uses Pydantic schemas, not raw YAML dicts.
- **AC-A.5**: CLI uses `Typer` (or `Click`), not stdlib `argparse`.
- **AC-A.6**: HTTP via `httpx` with async, not `urllib.request` / `requests`.
- **AC-A.7**: Logging via `loguru`, not stdlib `logging`.
- **AC-A.8**: Independent reviewer reading both READMEs would describe them as "different projects with overlapping problem space" rather than "fork".

### English-first (AC-E)
- **AC-E.1**: 100% of code comments, docstrings, log messages, CLI `--help` text in English.
- **AC-E.2**: Default note/report templates in English. Chinese & other locales available via `paperwiki/locales/` resources.
- **AC-E.3**: README, CONTRIBUTING, CHANGELOG, ARCHITECTURE in English.
- **AC-E.4**: Issue / PR templates English.
- **AC-E.5**: PyPI keywords / GitHub topics English.

### Plugin system (AC-P)
- **AC-P.1**: Built-in plugins discoverable via Python entry points (`paperwiki.sources`, `paperwiki.filters`, `paperwiki.scorers`, `paperwiki.reporters`).
- **AC-P.2**: External packages can register plugins without forking core (`pip install paperwiki-plugin-foo` self-registers).
- **AC-P.3**: Each plugin implements a `typing.Protocol` interface; runtime checks via `runtime_checkable`.
- **AC-P.4**: Five reference plugins ship in core: `arxiv` source, `semantic_scholar` source, `relevance + dedup + recency` filters, `composite` scorer, `markdown + obsidian` reporters.
- **AC-P.5**: A "recipe" YAML can compose plugins into a pipeline without writing code.

### SKILL packaging (AC-S)
- **AC-S.1**: `.plugin` manifest (Claude Code plugin format) at `claude-plugin/plugin.json` or repo root.
- **AC-S.2**: SKILL files at `claude-plugin/skills/*/SKILL.md` follow Claude Code skill spec.
- **AC-S.3**: Three reference SKILLs ship: `paperwiki:digest`, `paperwiki:analyze`, `paperwiki:wiki-update`.
- **AC-S.4**: SKILLs invoke the underlying CLI (`paperwiki ...`), not raw Python — clean boundary.
- **AC-S.5**: A user can `omc skill add paper-wiki` (or equivalent) and use the SKILLs.

### Acknowledgment (AC-K)
- **AC-K.1**: README has a single-paragraph "Acknowledgments" section linking to `evil-read-arxiv`.
- **AC-K.2**: `CITATION.cff` includes `references:` block citing the inspiration.
- **AC-K.3**: Wording: short, dignified, not apologetic. Example: *"The seed idea — automating arXiv triage into a knowledge note — was inspired by `evil-read-arxiv` (juliye2025). paper-wiki is a clean-room rewrite with a different architecture and a wiki-first focus."*

### SEO differentiation (AC-SEO)
- **AC-SEO.1**: GitHub repo description avoids the words `arxiv-recommendations`, `daily-paper`, `论文推荐`.
- **AC-SEO.2**: GitHub topics: `research-wiki`, `personal-knowledge-base`, `academic-tools`, `paper-management`, `claude-code-plugin`, `obsidian`, `arxiv`. Not `paper-recommendation`, not `evil-*`.
- **AC-SEO.3**: README opening positions the project as "research wiki builder", not "paper recommender".
- **AC-SEO.4**: PyPI package name `paper-wiki`. PyPI keywords align with topics above.
- **AC-SEO.5**: No mention of `evil-read-arxiv` in repo metadata, only in the README Acknowledgments section.

## Architecture

### Top-level layout

```
paper-wiki/
├── pyproject.toml             # Hatch / PDM build, declares plugins via entry_points
├── LICENSE                    # GPL-3.0 (already exists)
├── README.md                  # English-first, positioning + acknowledgment
├── CITATION.cff               # Citation metadata
├── CHANGELOG.md               # Keep-a-changelog format
├── ARCHITECTURE.md            # Architecture deep dive
├── CONTRIBUTING.md
├── .github/
│   ├── workflows/{ci.yml,release.yml}
│   └── ISSUE_TEMPLATE/
├── docs/
│   ├── getting-started.md
│   ├── recipes.md
│   ├── plugin-authoring.md
│   └── skill-usage.md
├── src/
│   └── paperwiki/
│       ├── __init__.py
│       ├── core/
│       │   ├── models.py        # Paper, Recommendation, Score, RunContext
│       │   ├── protocols.py     # Source, Filter, Scorer, Reporter, Pipeline
│       │   ├── pipeline.py      # Orchestrator
│       │   ├── registry.py      # Plugin discovery via entry_points
│       │   └── errors.py
│       ├── plugins/
│       │   ├── sources/{arxiv.py,semantic_scholar.py,base.py}
│       │   ├── filters/{relevance.py,dedup.py,recency.py,base.py}
│       │   ├── scorers/{composite.py,base.py}
│       │   └── reporters/{markdown.py,obsidian.py,base.py}
│       ├── cli/
│       │   ├── __init__.py      # Typer app
│       │   ├── digest.py        # `paperwiki digest` (replaces "start-my-day")
│       │   ├── analyze.py       # `paperwiki analyze` (replaces "paper-analyze")
│       │   ├── wiki.py          # `paperwiki wiki` (knowledge base ops)
│       │   └── plugin.py        # plugin list/info commands
│       ├── config/
│       │   ├── schema.py        # Pydantic settings
│       │   └── loader.py
│       ├── locales/
│       │   ├── en/templates/    # English templates (default)
│       │   ├── zh/templates/    # Optional Chinese
│       │   └── README.md
│       └── _internal/
│           ├── http.py          # httpx client wrapper
│           ├── normalize.py     # arxiv_id / title key normalization
│           └── logging.py       # loguru config
├── claude-plugin/               # Claude Code plugin bundle
│   ├── plugin.json              # Plugin manifest
│   ├── skills/
│   │   ├── digest/SKILL.md
│   │   ├── analyze/SKILL.md
│   │   └── wiki-update/SKILL.md
│   └── README.md
├── recipes/                     # Pipeline composition examples (YAML)
│   ├── daily-arxiv.yaml
│   ├── weekly-deep-dive.yaml
│   └── obsidian-vault.yaml
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── examples/
    └── custom-plugin/           # External plugin example
```

### Domain model (`core/models.py`)

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Author(BaseModel):
    name: str
    affiliation: Optional[str] = None


class Paper(BaseModel):
    """Canonical paper representation across sources."""
    canonical_id: str          # e.g., "arxiv:2506.13063"
    title: str
    authors: list[Author]
    abstract: str
    published_at: datetime
    categories: list[str] = Field(default_factory=list)
    pdf_url: Optional[str] = None
    landing_url: Optional[str] = None
    citation_count: Optional[int] = None
    raw: dict = Field(default_factory=dict)  # source-specific extras


class ScoreBreakdown(BaseModel):
    relevance: float = 0.0
    novelty: float = 0.0
    momentum: float = 0.0       # popularity over time
    rigor: float = 0.0          # quality
    composite: float = 0.0
    notes: dict[str, str] = Field(default_factory=dict)


class Recommendation(BaseModel):
    paper: Paper
    score: ScoreBreakdown
    matched_topics: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None


class RunContext(BaseModel):
    """Carries state through the pipeline."""
    target_date: datetime
    config_snapshot: dict
    counters: dict[str, int] = Field(default_factory=dict)
```

### Plugin protocols (`core/protocols.py`)

```python
from typing import Protocol, runtime_checkable, AsyncIterator
from .models import Paper, Recommendation, RunContext


@runtime_checkable
class Source(Protocol):
    """Yields candidate papers from an external system."""
    name: str
    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]: ...


@runtime_checkable
class Filter(Protocol):
    """Drops or transforms papers based on a predicate."""
    name: str
    async def apply(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Paper]: ...


@runtime_checkable
class Scorer(Protocol):
    """Assigns ScoreBreakdown to each Paper, producing Recommendations."""
    name: str
    async def score(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Recommendation]: ...


@runtime_checkable
class Reporter(Protocol):
    """Persists Recommendations to a target (file, vault, API)."""
    name: str
    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None: ...


@runtime_checkable
class WikiBackend(Protocol):
    """Optional: knowledge-base read/write for cross-paper queries."""
    async def upsert_paper(self, rec: Recommendation) -> None: ...
    async def query(self, q: str) -> list[Recommendation]: ...
```

### Pipeline orchestration (`core/pipeline.py`)

```python
class Pipeline:
    def __init__(
        self,
        sources: list[Source],
        filters: list[Filter],
        scorer: Scorer,
        reporters: list[Reporter],
        wiki: Optional[WikiBackend] = None,
    ): ...

    async def run(self, ctx: RunContext) -> PipelineResult:
        # 1. Fan-in from all sources (async merge)
        # 2. Apply filters in order
        # 3. Score
        # 4. Top-K selection
        # 5. Emit to all reporters
        # 6. Optionally update wiki
        ...
```

This is **fundamentally different** from the original repo's procedural `main()` in `search_arxiv.py`. The pipeline is composable, async, and plugin-defined rather than hard-coded.

### Plugin discovery (`core/registry.py`)

Uses `importlib.metadata.entry_points`:

```toml
# pyproject.toml
[project.entry-points."paperwiki.sources"]
arxiv = "paperwiki.plugins.sources.arxiv:ArxivSource"
semantic_scholar = "paperwiki.plugins.sources.semantic_scholar:SemanticScholarSource"

[project.entry-points."paperwiki.filters"]
relevance = "paperwiki.plugins.filters.relevance:RelevanceFilter"
dedup = "paperwiki.plugins.filters.dedup:DedupFilter"
recency = "paperwiki.plugins.filters.recency:RecencyFilter"

[project.entry-points."paperwiki.scorers"]
composite = "paperwiki.plugins.scorers.composite:CompositeScorer"

[project.entry-points."paperwiki.reporters"]
markdown = "paperwiki.plugins.reporters.markdown:MarkdownReporter"
obsidian = "paperwiki.plugins.reporters.obsidian:ObsidianReporter"
```

External plugins:

```toml
# Some external package
[project.entry-points."paperwiki.sources"]
biorxiv = "my_package.biorxiv:BioRxivSource"
```

After `pip install`, `paperwiki plugin list` discovers automatically.

### Recipe composition (no-code pipeline)

```yaml
# recipes/daily-arxiv.yaml
name: daily-arxiv
sources:
  - name: arxiv
    config:
      categories: [cs.AI, cs.LG, cs.CL]
      window_days: 1
filters:
  - name: relevance
    config:
      topics_file: ~/.config/paperwiki/topics.yaml
  - name: dedup
    config:
      vault_path: ~/Documents/Obsidian-Vault
      strategy: identifier_first
  - name: recency
    config:
      max_days: 1
scorer:
  name: composite
  config:
    weights: { relevance: 0.5, novelty: 0.2, momentum: 0.2, rigor: 0.1 }
reporters:
  - name: markdown
    config: { output_dir: ./out }
  - name: obsidian
    config: { vault_path: ~/Documents/Obsidian-Vault, daily_dir: 10_Daily }
top_k: 10
```

CLI: `paperwiki run recipes/daily-arxiv.yaml`

## Tooling Choices (deliberately different from original)

| Concern | `evil-read-arxiv` | `paper-wiki` (this) |
|---------|------------------|---------------------|
| HTTP | `urllib.request` + optional `requests` | `httpx` (async-first) |
| CLI parsing | `argparse` | `Typer` |
| Logging | stdlib `logging` | `loguru` |
| Config | YAML + dict | Pydantic settings + YAML/TOML |
| Build | implicit Python files | `pyproject.toml` + Hatch |
| Async | None (sync) | `asyncio` end-to-end |
| Plugin | None (skill-folder convention) | Python entry points + Protocol |
| Tests | None visible | `pytest` + `pytest-asyncio` + VCR for HTTP |
| Type checking | None | `mypy --strict` (or `pyright`) |
| Lint | None | `ruff` |
| Format | None | `ruff format` |

## SKILL packaging (Claude Code plugin)

### Manifest (`claude-plugin/plugin.json`)

```json
{
  "name": "paper-wiki",
  "displayName": "Paper Wiki",
  "version": "0.1.0",
  "description": "Personal research wiki builder powered by arXiv and Semantic Scholar",
  "author": "kaneyxx",
  "license": "GPL-3.0",
  "homepage": "https://github.com/kaneyxx/paper-wiki",
  "skills": [
    "skills/digest",
    "skills/analyze",
    "skills/wiki-update"
  ],
  "requirements": {
    "python": ">=3.11",
    "pip": ["paper-wiki>=0.1.0"]
  }
}
```

### Reference SKILLs

1. **`paperwiki:digest`** — Build today's research digest using a recipe. Replaces the `start-my-day` workflow concept, but invocation goes through `paperwiki digest --recipe daily-arxiv` (no script duplication).
2. **`paperwiki:analyze`** — Deep-analyze a single paper into a wiki entry. Equivalent purpose to `paper-analyze` but a different prompt structure and template.
3. **`paperwiki:wiki-update`** — Re-index the wiki, surface stale entries, suggest cross-links.

Each `SKILL.md` is **English-first**, references CLI commands rather than embedding Python scripts, and has its own structure (no `工作流程` headers — uses `## Workflow / ## Tools / ## Examples`).

## Acknowledgment (final wording draft)

```markdown
## Acknowledgments

The seed idea — automating arXiv paper triage into Obsidian-friendly notes —
was inspired by [evil-read-arxiv](https://github.com/juliye2025/evil-read-arxiv)
by juliye2025 and contributors. **paper-wiki is a clean-room rewrite** with a
different architecture (plugin pipeline vs. procedural scripts), a different
focus (long-term wiki accumulation vs. daily feed), and a different default
language (English vs. Chinese). No code from the original project was copied;
overlap is at the level of the problem domain.
```

`CITATION.cff` will include a `references:` entry pointing at the inspiration.

## SEO Differentiation Strategy

| Surface | Action |
|---------|--------|
| Repo name | Already `paper-wiki` — distinct from `evil-read-arxiv` ✅ |
| Repo description | "Personal research wiki builder. Pipeline-driven paper ingestion with plugin architecture." (No "daily", no "arxiv recommendation") |
| GitHub topics | `research-wiki`, `personal-knowledge-base`, `academic-tools`, `paper-management`, `claude-code-plugin`, `obsidian`, `arxiv`, `python` |
| README first sentence | "**paper-wiki** turns the firehose of academic publishing into a curated, queryable, knowledge-accumulating wiki." |
| README keywords | "research wiki", "knowledge base", "plugin", "pipeline" — not "daily recommendation", not "fork" |
| PyPI package | `paper-wiki` |
| PyPI classifiers | `Topic :: Scientific/Engineering`, `Topic :: Documentation`, `Intended Audience :: Science/Research`, `Framework :: AsyncIO` |
| CLI command | `paperwiki` (not `start-my-day`, not `arxiv-*`) |
| Default config dir | `~/.config/paperwiki/` |
| GitHub social card | Custom — different visual identity |

## Implementation Phases

### Phase 0 — Repo scaffolding (small, ship first)
1. `pyproject.toml` with Hatch backend, Typer/loguru/pydantic/httpx pinned
2. README skeleton with positioning + acknowledgment
3. CITATION.cff
4. `src/paperwiki/__init__.py` exposing `__version__`
5. CI workflow: lint + type-check + test
6. **Deliverable**: `pip install -e .` works; `paperwiki --version` prints.

### Phase 1 — Core models & protocols (no networking)
1. `core/models.py` — Pydantic models
2. `core/protocols.py` — Plugin protocols
3. `core/pipeline.py` — Pipeline runner with mock plugins
4. `tests/unit/` — full coverage of models + pipeline orchestration with stub plugins
5. **Deliverable**: Pipeline runs end-to-end with stubs.

### Phase 2 — Source plugins
1. `arxiv.py` — async httpx client, paged fetch, response parsing (clean rewrite, no copy)
2. `semantic_scholar.py` — async client, rate-limit handling
3. VCR-recorded integration tests
4. **Deliverable**: `paperwiki run recipes/sources-only.yaml` fetches and prints papers.

### Phase 3 — Filter plugins
1. `relevance.py` — topic matching from user config
2. `dedup.py` — full vault + daily history dedup with topup (port the design from start-my-day's plan, but as a clean filter)
3. `recency.py` — sliding window
4. **Deliverable**: Filters compose, pipeline produces final candidates.

### Phase 4 — Scorer & reporters
1. `composite.py` — weighted multi-criteria scoring
2. `markdown.py` — clean Markdown digest
3. `obsidian.py` — Obsidian-flavored Markdown with wikilinks (English-first templates)
4. **Deliverable**: End-to-end recipe produces a daily digest file.

### Phase 5 — Claude Code plugin packaging
1. `claude-plugin/plugin.json`
2. Three SKILLs (digest, analyze, wiki-update)
3. Test plugin install via `omc skill add paper-wiki`
4. **Deliverable**: Claude Code installable plugin.

### Phase 6 — Wiki backend (the namesake feature)
1. `WikiBackend` protocol + `MarkdownWikiBackend` reference impl (file-based)
2. `wiki query` CLI for keyword search
3. Cross-link suggestions
4. **Deliverable**: Knowledge accumulates across runs; queryable.

### Phase 7 — Polish & launch
1. Examples in `recipes/`, `examples/`
2. Documentation pass
3. v0.1.0 PyPI release
4. README "What's next" section
5. **Deliverable**: Publishable.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Code-similarity perception** despite clean-room | Reputational | Track every implementation decision in ARCHITECTURE.md showing rationale; tooling list above shows divergence; commit history will not contain any cherry-pick from `evil-read-arxiv` |
| **Idea overlap legal claim** (no LICENSE on original) | Low (ideas not copyrightable) but uncomfortable | Acknowledge inspiration explicitly; do not copy code; document independent design decisions |
| **GPL-3.0 viral reach** (you chose copyleft) | Future contributors / users may want permissive | Document license rationale in CONTRIBUTING; consider dual-license offer for plugins (`MIT or GPL` for plugin SDK) — decide before v1.0 |
| **SKILL spec drift** (Claude Code plugin format evolves) | Plugin breaks | Pin to a tested spec version in `plugin.json`; have CI smoke test against latest |
| **Plugin API instability** before v1.0 | Plugin authors burned | Mark protocols `@experimental` until v1.0; document SemVer policy |
| **Async complexity learning curve** | Maintenance load | Pipeline is the only mandatory async surface; sync helpers wrap async for simple plugins |
| **"Just use Zotero" comparison** | Adoption friction | README explicitly compares to alternatives |
| **English-first alienating original audience** | Smaller initial users | Provide Chinese locale from day 1 (translated, not primary); welcome translation PRs |

## Verification Checklist (before announcing v0.1.0)

- [ ] `git log --all --oneline` contains zero commits authored by anyone other than you (or future contributors). No `evil-read-arxiv` author appears.
- [ ] `git log -p` and `diff` against `evil-read-arxiv` shows zero shared content.
- [ ] All 23 ACs above (A.1–A.8, E.1–E.5, P.1–P.5, S.1–S.5, K.1–K.3, SEO.1–SEO.5) have evidence.
- [ ] `pip install paper-wiki` works on a clean machine.
- [ ] `paperwiki run recipes/daily-arxiv.yaml` produces a valid digest.
- [ ] Claude Code plugin installs and three SKILLs execute.
- [ ] README's first 200 words mention positioning, plugin architecture, and acknowledgment — in that order.
- [ ] `pytest -q` green.
- [ ] `mypy --strict src/` clean.
- [ ] `ruff check` clean.

## Out of Scope (this plan)

- ❌ Migrating any user data from `evil-read-arxiv` setups (separate project later)
- ❌ Web UI / dashboard (CLI-first)
- ❌ Multi-user / SaaS
- ❌ Built-in LLM calls inside the pipeline (LLM is a SKILL concern, not core)
- ❌ Vector embeddings / semantic search (post-v0.1)
- ❌ PDF parsing / image extraction (separate plugin in a later phase)

## Decision Log

- **GPL-3.0**: Already chosen by user; document rationale in CONTRIBUTING (copyleft to ensure plugins benefit community).
- **Pipeline pattern**: Composable, testable, future-proof for new sources. Original repo's procedural style does not scale to plugin ecosystem.
- **Async**: arXiv + S2 are I/O-bound; concurrent fetch is a meaningful win.
- **Pydantic**: Schema validation, free JSON schema export for plugins, IDE autocomplete.
- **Typer**: Modern UX, automatic completion, type-driven help text.
- **English-first**: Reaches international research community; aligns with PyPI ecosystem norms; avoids language-mixing in source.
- **Acknowledge inspiration once, prominently**: Single dignified mention is more credible than buried disclaimer; avoids both plagiarism perception and undue association.
- **GitHub topics chosen for SEO disjointness**: `research-wiki` + `personal-knowledge-base` carve a search niche away from `evil-read-arxiv`'s topics.

## Next Action

Phase 0 scaffolding is the smallest meaningful first commit. Roughly:
- `pyproject.toml`, `README.md`, `CITATION.cff`, `src/paperwiki/__init__.py`, `.github/workflows/ci.yml`, `tests/test_smoke.py`.

Want me to execute Phase 0 next, or do you want to review/edit this plan first?
