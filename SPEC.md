# SPEC — paper-wiki

**Status**: Draft v0.3 (Claude Code plugin–first; aligned with `.claude-plugin` convention)
**Last updated**: 2026-04-25
**Owner**: kaneyxx

This SPEC is the operating contract for anyone (human or agent) working on
`paper-wiki`. The companion long-form rationale lives in
[`.omc/plans/00-foundation-plan.md`](.omc/plans/00-foundation-plan.md).
When the two disagree, **SPEC wins** and the plan is updated.

This SPEC follows the **Claude Code plugin marketplace convention** as
practiced by reference projects such as `addyosmani/agent-skills`:

- Manifest in `.claude-plugin/plugin.json`
- Self-published marketplace via `.claude-plugin/marketplace.json`
- User-facing slash commands in `.claude/commands/`
- Auto-discovered SKILLs in `skills/<name>/SKILL.md`
- Lifecycle automation in `hooks/hooks.json`
- Validation via the official `claude plugin validate` tool

---

## 1. Objective

`paper-wiki` is a **Claude Code plugin** that helps researchers build a
personal wiki of academic papers. SKILLs let the user — through Claude
Code — fetch papers from sources like arXiv and Semantic Scholar, filter
and score them against research interests, and persist durable notes
into a Markdown vault (Obsidian, plain folders, etc.).

### Distribution model

`paper-wiki` is shipped **only as a Claude Code plugin marketplace**.
It is **not** published to PyPI. Users install it via Claude Code's
plugin command:

```
/plugin marketplace add kaneyxx/paper-wiki
/plugin install paper-wiki@paper-wiki
```

The bundled Python implementation is invisible to end users — it
self-installs into a private virtualenv on first session via the
`SessionStart` hook.

### Target users

- Individual researchers using Claude Code who want a self-curated paper
  knowledge base
- Plugin contributors extending the pipeline with new sources, filters,
  scorers, or reporters

### Non-objectives

- ❌ Not a PyPI library
- ❌ Not a stand-alone command-line tool for end users
- ❌ Not a daily-feed app (daily mode is one of many recipes)
- ❌ Not a multi-user / SaaS service
- ❌ Not a Zotero replacement
- ❌ Not an LLM-integration framework — Claude Code is our only LLM
  surface; the plugin itself never calls LLM APIs

### Success looks like

A user opens Claude Code, types `/paper-wiki:digest`, and within ~60
seconds gets a curated Markdown digest written into their vault — with
no duplicates against earlier digests or existing notes — produced by
SKILLs that compose pipeline plugins under the hood, all in English by
default.

---

## 2. Commands

### User-facing slash commands

Defined as Markdown files in `.claude/commands/<name>.md`. Each command
is a thin wrapper that activates one or more SKILLs.

| Command | Purpose |
|---------|---------|
| `/paper-wiki:digest` | Build a research digest using a recipe |
| `/paper-wiki:analyze` | Deep-analyze a single paper into a wiki entry |
| `/paper-wiki:wiki-update` | Re-index the wiki, surface stale entries, suggest cross-links |
| `/paper-wiki:wiki-query` | Keyword query across the wiki |
| `/paper-wiki:setup` | First-run setup helper (env check, vault path, recipe selection) |

Slash commands are kebab-case under the `paperwiki:` namespace to avoid
collisions with other plugins.

### SKILLs (auto-activated by trigger conditions)

SKILLs live in `skills/<skill-name>/SKILL.md`. Claude Code activates
them based on the `description` frontmatter's `Use when…` patterns. Each
SKILL may also be invoked explicitly by a slash command.

| SKILL | Activates when |
|-------|----------------|
| `digest` | User says "build today's digest", or `/paper-wiki:digest` |
| `analyze` | User says "analyze this paper", or `/paper-wiki:analyze` |
| `wiki-update` | User says "refresh the wiki", or `/paper-wiki:wiki-update` |
| `wiki-query` | User says "search my wiki", or `/paper-wiki:wiki-query` |
| `setup` | First session detected, or `/paper-wiki:setup` |
| `paper-source-author` | User asks "how do I add a new source plugin?" |

### Internal Python entry points (called by SKILLs, not by users)

SKILLs call Python via:

```
${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.<name> [args]
```

| Module | Used by |
|--------|---------|
| `paperwiki.runners.digest` | `digest` SKILL |
| `paperwiki.runners.analyze` | `analyze` SKILL |
| `paperwiki.runners.wiki` | `wiki-update`, `wiki-query` SKILLs |
| `paperwiki.runners.diagnostics` | `setup` SKILL |

These are documented in `docs/internal-runners.md` for plugin
contributors. They are not a stable user contract.

### Developer commands (for repo maintainers and plugin contributors)

| Purpose | Command |
|---------|---------|
| Bootstrap dev env (recommended) | `uv venv && uv pip install -e ".[dev]"` |
| Bootstrap dev env (fallback) | `python -m venv .venv && .venv/bin/pip install -e ".[dev]"` |
| Lint | `ruff check src tests` |
| Format | `ruff format src tests` |
| Type-check | `mypy --strict src` |
| Unit tests | `pytest -q tests/unit` |
| Integration tests | `pytest -q tests/integration` |
| All tests | `pytest -q` |
| Coverage | `pytest --cov=paperwiki --cov-report=term-missing` |
| Validate plugin manifests | `claude plugin validate .` |
| Local install of plugin | `claude --plugin-dir $(pwd)` (run from repo root) |

### CI

`.github/workflows/ci.yml`:

- `ruff check`, `ruff format --check`, `mypy --strict`, `pytest -q`
- `npm install -g @anthropic-ai/claude-code`
- `claude plugin validate .`

`.github/workflows/test-plugin-install.yml` (mirrors the
`addyosmani/agent-skills` pattern):

- `claude plugin marketplace add ./`
- `claude plugin marketplace list`
- `claude plugin install paper-wiki@paper-wiki --scope user`

`.github/workflows/release.yml` triggers on tags `v*`, runs all of the
above, and creates a GitHub release with the manifest snapshot.

---

## 3. Project Structure

```
paper-wiki/
├── .claude-plugin/
│   ├── plugin.json             # Plugin manifest (Claude Code spec)
│   └── marketplace.json        # Self-published marketplace listing
├── .claude/
│   └── commands/               # User-facing slash commands
│       ├── digest.md
│       ├── analyze.md
│       ├── wiki-update.md
│       ├── wiki-query.md
│       └── setup.md
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── test-plugin-install.yml
│   │   └── release.yml
│   └── ISSUE_TEMPLATE/
├── LICENSE                     # GPL-3.0
├── README.md                   # English-first; install instructions
├── CLAUDE.md                   # In-repo dev guidance for Claude Code
├── AGENTS.md                   # Cross-agent dev guidance
├── CHANGELOG.md                # Keep-a-changelog
├── ARCHITECTURE.md             # Architecture deep dive
├── CONTRIBUTING.md
├── CITATION.cff
├── SPEC.md                     # This file
├── pyproject.toml              # Local dev install only; never published to PyPI
├── skills/                     # Auto-discovered SKILLs (Claude Code reads SKILL.md)
│   ├── digest/
│   │   ├── SKILL.md            # Main entry
│   │   └── recipes-reference.md  # Optional supporting file (only if SKILL.md > ~100 lines)
│   ├── analyze/
│   │   └── SKILL.md
│   ├── wiki-update/
│   │   └── SKILL.md
│   ├── wiki-query/
│   │   └── SKILL.md
│   ├── setup/
│   │   └── SKILL.md
│   └── paper-source-author/
│       └── SKILL.md
├── agents/                     # Specialist personas (optional, used by SKILLs)
│   ├── README.md
│   └── pipeline-architect.md   # e.g., reviews plugin protocol changes
├── references/                 # Cross-SKILL shared content
│   ├── recipe-schema.md
│   ├── plugin-authoring.md
│   ├── dedup-strategy.md
│   └── obsidian-conventions.md
├── hooks/
│   ├── hooks.json              # Lifecycle hook registry
│   ├── ensure-env.sh           # SessionStart: build .venv if missing
│   └── README.md
├── docs/
│   ├── getting-started.md
│   ├── recipes.md
│   ├── plugin-authoring.md
│   ├── skill-anatomy.md
│   └── internal-runners.md
├── recipes/                    # YAML recipe library
│   ├── daily-arxiv.yaml
│   ├── weekly-deep-dive.yaml
│   └── obsidian-vault.yaml
├── src/paperwiki/              # Backing Python implementation (private)
│   ├── __init__.py             # __version__ only
│   ├── core/
│   │   ├── models.py           # Pydantic: Paper, Recommendation, ScoreBreakdown, RunContext
│   │   ├── protocols.py        # Source, Filter, Scorer, Reporter, WikiBackend
│   │   ├── pipeline.py         # Pipeline orchestrator
│   │   ├── registry.py         # Plugin discovery via importlib.metadata
│   │   └── errors.py
│   ├── plugins/
│   │   ├── sources/{base.py, arxiv.py, semantic_scholar.py}
│   │   ├── filters/{base.py, relevance.py, dedup.py, recency.py}
│   │   ├── scorers/{base.py, composite.py}
│   │   └── reporters/{base.py, markdown.py, obsidian.py}
│   ├── runners/                # Invoked by SKILLs
│   │   ├── digest.py
│   │   ├── analyze.py
│   │   ├── wiki.py
│   │   └── diagnostics.py
│   ├── config/
│   │   ├── schema.py           # Pydantic settings
│   │   └── loader.py
│   ├── locales/
│   │   ├── en/templates/
│   │   └── zh/templates/
│   └── _internal/
│       ├── http.py
│       ├── normalize.py
│       └── logging.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/               # VCR cassettes, sample papers
│   ├── unit/{core, plugins, runners, _internal}/
│   └── integration/
└── examples/
    └── custom-source-plugin/   # Example external plugin authorship
```

### Layout rules

- The Claude Code plugin "surface" lives in `.claude-plugin/`,
  `.claude/`, `skills/`, `agents/`, `references/`, `hooks/`. Anything
  the Claude Code runtime sees is in those directories.
- All Python source lives under `src/paperwiki/` (src layout). End
  users never see this directly.
- All SKILLs live at `skills/<skill-name>/SKILL.md`. Skill directory
  names are lowercase, hyphenated, and match the SKILL frontmatter
  `name`. Supporting files live next to `SKILL.md` only when content
  exceeds ~100 lines.
- Tests mirror `src/paperwiki/` layout under `tests/`.
- Modules with leading `_` are internal — not part of the plugin
  contract for plugin authors.
- Plugin classes named after their role:
  `*Source`, `*Filter`, `*Scorer`, `*Reporter`, `*Backend`.

### Vault subdirectory defaults

The plugin writes user-facing artifacts under three default subdirs of
the user's vault. They are exposed as constants in
`paperwiki.config.layout`:

| Constant | Default value | Purpose |
|----------|--------------|---------|
| `DAILY_SUBDIR` | `Daily` | Per-day digests written by `ObsidianReporter`. |
| `SOURCES_SUBDIR` | `Sources` | Per-paper notes written by the `analyze` SKILL (Phase 6). |
| `WIKI_SUBDIR` | `Wiki` | Synthesized concept articles + index (Phase 6). |

The defaults are deliberately friendly (no numeric prefixes) so the
plugin does not impose Johnny.Decimal / PARA conventions on users who
do not follow them. Users who do can override every subdir per-recipe.

---

## 4. Manifest contracts

### `.claude-plugin/plugin.json`

```json
{
  "name": "paper-wiki",
  "description": "Personal research wiki builder for Claude Code — pipeline-driven paper ingestion with plugin architecture.",
  "version": "0.1.0",
  "author": { "name": "kaneyxx" },
  "homepage": "https://github.com/kaneyxx/paper-wiki",
  "repository": "https://github.com/kaneyxx/paper-wiki",
  "license": "GPL-3.0",
  "commands": "./.claude/commands"
}
```

Manifest constraints (verified by `claude plugin validate`):

- `name`: lowercase, hyphenated; matches the directory name people clone
- `version`: SemVer
- `commands`: relative path to slash-commands directory

### `.claude-plugin/marketplace.json`

```json
{
  "name": "paper-wiki",
  "owner": { "name": "kaneyxx" },
  "metadata": {
    "description": "Personal research wiki builder for Claude Code."
  },
  "plugins": [
    {
      "name": "paper-wiki",
      "source": { "source": "github", "repo": "kaneyxx/paper-wiki" },
      "description": "Pipeline-driven paper ingestion with plugin architecture."
    }
  ]
}
```

### `hooks/hooks.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/ensure-env.sh"
          }
        ]
      }
    ]
  }
}
```

### `hooks/ensure-env.sh` (sketch)

```bash
#!/usr/bin/env bash
set -euo pipefail
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}"
VENV="${PLUGIN_ROOT}/.venv"
STAMP="${VENV}/.installed"

if [ ! -f "${STAMP}" ]; then
  cd "${PLUGIN_ROOT}"
  if command -v uv >/dev/null 2>&1; then
    uv venv "${VENV}"
    uv pip install --python "${VENV}/bin/python" -e .
  else
    python3 -m venv "${VENV}"
    "${VENV}/bin/pip" install -e .
  fi
  touch "${STAMP}"
fi
```

End users never see this — it runs silently on first session and
no-ops thereafter.

### SKILL frontmatter

Every `SKILL.md` starts with:

```markdown
---
name: <kebab-case-name>
description: <One-sentence what it does (third person)>. Use when <trigger conditions>.
---
```

`name` matches the directory; `description` follows the convention: the
first sentence describes capability, the rest describes triggers.

### SKILL anatomy (six standard sections)

```markdown
# <Skill Name>

## Overview
What this skill does and why it matters.

## When to Use
Triggering conditions, with positive and negative examples.

## Process
Step-by-step workflow with verification gates between steps.

## Common Rationalizations
Excuses agents/users use to skip steps, with rebuttals.

## Red Flags
Warning signs that the skill is being applied incorrectly.

## Verification
How to confirm the skill was applied correctly. Evidence requirements.
```

This anatomy is the convention used by `addyosmani/agent-skills` and
similar production-grade plugins. New SKILLs MUST follow it.

### Slash command files

Each `.claude/commands/<name>.md` looks like:

```markdown
---
description: Build a research digest using a recipe
---

Invoke the paper-wiki:digest skill.

If the user has not provided a recipe, ask which recipe to use, or default to `daily-arxiv`.
After the digest is produced, summarize the top 3 papers in chat.
```

---

## 5. Code Style

### Language & runtime

- Python ≥ 3.11
- Type hints mandatory on all internal APIs, especially plugin protocols
- `from __future__ import annotations` at the top of every module

### Formatting & linting

- `ruff format` — single source of truth for formatting
- `ruff check` — rule set: `E`, `F`, `I`, `B`, `UP`, `N`, `S`, `RUF`,
  `PT`, `SIM`, `TCH`, `PERF`
- `mypy --strict` must pass for `src/`. Tests may relax
  `disallow_untyped_defs`

### Naming

- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Module-level constants: `UPPER_SNAKE`
- Private helpers: leading underscore
- Plugin classes named after their role suffix:
  `*Source`, `*Filter`, `*Scorer`, `*Reporter`, `*Backend`

### Async & I/O

- All I/O (network, filesystem) goes through async functions
- Use `httpx.AsyncClient` for HTTP; do not import `requests` or `urllib`
- Use `aiofiles` for file I/O when in an async context;
  sync `pathlib` is fine for runner startup
- Plugin protocols are async-first; provide a sync wrapper helper
  (`paperwiki.utils.run_sync`) for plugin authors who prefer sync

### Logging

- Use `loguru` exclusively; do not import stdlib `logging`
- Every log line carries an action verb and identifiers
  (`logger.info("source.fetch.complete", count=len(papers), source=name)`)
- No print statements outside of runner-stdout paths consumed by SKILLs

### Errors

- Custom exceptions in `core/errors.py`; inherit from `PaperWikiError`
- User errors (bad config, bad input) → `UserError` (runner exits 1)
- System errors (network down, API change) → `SystemError` (runner exits 2)
- Never swallow exceptions silently; either re-raise or log + recover

### Comments & docstrings

- All public modules, classes, and functions have docstrings
- Docstrings follow Google style
- All comments and docstrings in **English** (Chinese only inside
  `locales/zh/`)
- Comments explain *why*, not *what*; let code show *what*

### Imports

- Sort with `ruff` (isort-compatible)
- No star imports
- No relative imports across packages; only within a package

### LLM boundary

- The plugin code **never** calls LLM APIs. Reasoning, summarization,
  and natural-language generation are the responsibility of Claude Code
  driving the SKILL. Python runners produce structured data; SKILLs
  let Claude turn that into prose.
- This means: no `anthropic`, `openai`, `langchain`, `litellm`, or
  similar imports anywhere in `src/paperwiki/`.

### SKILL writing style

- Follow the six-section anatomy in §4
- Description starts with capability (third person), then triggers
- Use bullet steps, not paragraphs, in Process
- Every Process step has a measurable exit criterion
- `Common Rationalizations` and `Red Flags` are mandatory, not optional

---

## 6. Testing Strategy

### Coverage target

- Unit-test coverage **≥ 85%** for `src/paperwiki/core/`
- Unit-test coverage **≥ 75%** overall
- Critical paths (pipeline, dedup, scoring) at 100%
- Coverage measured by `pytest-cov`; CI fails below thresholds

### Test pyramid

| Layer | Tooling | Scope |
|-------|---------|-------|
| Unit | `pytest`, `pytest-asyncio`, `hypothesis` | One module / one behavior; no I/O |
| Integration | `pytest-asyncio`, `vcrpy` for HTTP | One plugin against recorded fixture |
| End-to-end | `pytest-asyncio` | Full pipeline with stub network + temp filesystem |
| Plugin-install smoke | `claude plugin validate` + `claude plugin install` in CI | Manifest validity + install success |

### Fixtures & determinism

- All HTTP traffic in tests is replayed from VCR cassettes;
  **no live network** in CI
- All filesystem writes go to `tmp_path`
- All time-dependent logic accepts an injected `now` for deterministic
  testing
- Snapshot tests (Markdown digest output) use `syrupy`

### TDD expectation

- New features land with tests in the same PR
- Bug fixes land with a regression test that fails before the fix
- Tests describe behavior, not implementation; use Given/When/Then
  structure where it improves clarity

### What we do not test

- Third-party library internals
- Generated code
- Throwaway scripts in `examples/`

---

## 7. Boundaries

### Always do

- Default to English in all user-facing surfaces (README, SKILL.md,
  log messages, runner output, default templates)
- Validate plugin manifests with `claude plugin validate .` before
  every commit that touches `.claude-plugin/`, `.claude/commands/`,
  `skills/`, `agents/`, or `hooks/`
- Run `ruff check`, `ruff format --check`, `mypy --strict`,
  `pytest -q`, locally before any commit
- Write commit messages in **Conventional Commits** format
  (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`).
  Format is enforced by a `commit-msg` hook installed at dev-env
  bootstrap.
- Update `CHANGELOG.md` for every user-visible change
- Pin direct Python dependencies with version ranges; avoid floating
  versions
- Use `httpx` for HTTP; `loguru` for logs; `Pydantic` for config;
  `Typer` for any internal command-line entry points
- Use `pathlib` for paths; never raw `os.path.join`
- Treat the plugin protocol as `@experimental` until v1.0; document
  every change in `docs/plugin-authoring.md`
- Use `${CLAUDE_PLUGIN_ROOT}` in all hook and SKILL bash invocations;
  never hardcode paths
- Follow the six-section SKILL anatomy in §4 for every new SKILL

### Ask first

- Before adding a new top-level Python dependency
- Before changing a Pydantic model in `core/models.py` (breaks plugins)
- Before changing a `Protocol` in `core/protocols.py` (breaks plugins)
- Before introducing a new SKILL or removing one
- Before introducing a new slash command or removing one
- Before introducing a new runner or removing one
- Before touching `.claude-plugin/plugin.json`'s public surface
- Before touching `.claude-plugin/marketplace.json`'s public surface
- Before bumping the major version
- Before adding any non-English content to the default surface

### Never do

- Never publish to PyPI; this project is a Claude Code plugin only
- Never call LLM APIs from Python code; reasoning belongs in SKILLs
  driven by Claude Code
- Never add `requests` or `urllib.request` imports (use `httpx`)
- Never add stdlib `logging` imports (use `loguru`)
- Never use `argparse` (use `Typer` for any internal CLI)
- Never check secrets into the repo
- Never make live network calls in tests
- Never break the plugin protocol without a major version bump
- Never use mixed-language comments (Chinese + English in the same
  module); pick English for source, Chinese only inside `locales/zh/`
- Never auto-merge PRs that touch `core/protocols.py` or
  `.claude-plugin/`
- Never expose internal runners as a public CLI for end users
- Never write to `${CLAUDE_PLUGIN_ROOT}` outside the `.venv` directory;
  plugin must not pollute its install location

---

## Decision log

- **Manifest at `.claude-plugin/plugin.json`**: matches the official
  Claude Code plugin spec and the convention used by reference plugins
  such as `addyosmani/agent-skills`.
- **Self-published marketplace via `.claude-plugin/marketplace.json`**:
  lets users install with `/plugin marketplace add kaneyxx/paper-wiki`
  followed by `/plugin install paper-wiki`. No third-party marketplace
  dependency.
- **Slash commands in `.claude/commands/`**: mirrors reference plugin
  layout; one Markdown file per command; commands delegate to SKILLs.
- **SessionStart hook for venv bootstrap**: makes Python deps invisible
  to end users; idempotent via `.installed` stamp file; uses `uv` when
  available, falls back to stdlib `venv`.
- **Distribution: Claude Code plugin only**: single channel keeps
  packaging simple, install story uniform, avoids dual-maintenance of
  CLI vs. plugin UX.
- **No LLM API integration in code**: Claude Code already provides the
  LLM. Embedding LLM calls in the plugin would duplicate that surface
  and create vendor lock-in.
- **Python ≥ 3.11**: modern type syntax, `tomllib` stdlib, `Self`,
  asyncio improvements. Python 3.10 dropped to keep the codebase modern.
- **GPL-3.0**: chosen by repo owner; ensures plugin contributions stay
  open. Plugin SDK relicensing decision deferred to v1.0.
- **`uv` recommended, not mandatory**: faster and reproducible; falling
  back to `pip` is acceptable.
- **English-first, single mixed-language boundary**: avoids
  multi-language code smell while still serving zh users via
  `locales/zh/`.
- **Async-first plugin protocol**: I/O is the dominant cost; sync
  wrappers exist for plugin authors.
- **Coverage thresholds (core 85% / overall 75%)**: industry mid-tight
  setpoint; high enough to catch regressions in critical paths
  (pipeline, dedup, scoring) without bogging down feature work.
- **Conventional Commits enforced via commit-msg hook**: keeps history
  scannable and enables CHANGELOG automation.
- **Plugin protocol marked `@experimental` until v1.0**: signals
  instability to plugin authors so they can pin versions; SemVer
  guarantees begin at v1.0.0.
- **Six-section SKILL anatomy**: matches industry-leading plugins
  (`addyosmani/agent-skills`); enforces a consistent quality bar.
- **`claude plugin validate` as canonical manifest validator**: single
  source of truth maintained by Anthropic; no custom validator drift.
