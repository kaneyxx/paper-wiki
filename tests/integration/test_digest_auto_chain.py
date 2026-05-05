"""Integration tests for ``digest`` auto-chain (Task 9.218 / Phase G).

Closes the "from zero to query-ready" UX promise. Real-machine smoke
on 2026-05-04 (v0.4.4) and 2026-05-05 (v0.4.7) both confirmed the gap:
``/paper-wiki:digest`` correctly writes ``Wiki/papers/`` +
``Wiki/concepts/`` + dedup-ledger + per-paper figures, but leaves
``Wiki/.graph/edges.jsonl`` and ``Wiki/index.md`` un-built until the
user manually invokes ``paperwiki wiki-graph --rebuild`` and
``paperwiki wiki-compile``.

v0.4.8 chains both:

1. ``compile_graph(vault, force_rebuild=False)`` after a successful
   digest run, populating ``Wiki/.graph/edges.jsonl`` +
   ``citations.jsonl``.
2. ``compile_wiki(vault, allow_auto_migrate=False)`` after the graph
   refresh, rebuilding ``Wiki/index.md`` with current concept + paper
   counts.

Opt-out: ``--no-auto-chain`` flag + ``PAPERWIKI_NO_AUTO_CHAIN=1`` env.
Failures in either chain step are non-fatal — digest still exits 0
with a WARNING log + one-line stderr; the user already has paper
writes from the digest itself.

These tests stub the pipeline + chain primitives so the assertions
exercise the wiring contract without touching real graph state. Real
end-to-end correctness is covered by the post-merge maintainer smoke.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from paperwiki.core.errors import PaperWikiError
from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.core.pipeline import Pipeline
from paperwiki.runners import digest as digest_runner
from paperwiki.runners.wiki_compile import CompileResult
from paperwiki.runners.wiki_compile_graph import CompileGraphResult

# ---------------------------------------------------------------------------
# Recipe fixture — obsidian reporter so _resolve_vault_path returns a Path
# ---------------------------------------------------------------------------


_RECIPE_YAML = """\
name: smoke
sources:
  - name: arxiv
    config:
      categories: [cs.AI]
      lookback_days: 1
filters: []
scorer:
  name: composite
  config:
    topics:
      - name: vlm
        keywords: [foundation model]
reporters:
  - name: obsidian
    config:
      vault_path: {vault_path}
      wiki_backend: true
top_k: 5
"""


def _write_recipe(tmp_path: Path, vault_path: Path) -> Path:
    recipe_path = tmp_path / "r.yaml"
    recipe_path.write_text(
        _RECIPE_YAML.format(vault_path=vault_path),
        encoding="utf-8",
    )
    return recipe_path


# ---------------------------------------------------------------------------
# Stub plugins
# ---------------------------------------------------------------------------


class _StubSource:
    name = "stub"

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        yield Paper(
            canonical_id="arxiv:0001.0001",
            title="Foundation Model",
            authors=[Author(name="A")],
            abstract="abstract",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
        )


class _StubScorer:
    name = "stub-scorer"

    async def score(
        self,
        papers: AsyncIterator[Paper],
        ctx: RunContext,
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            yield Recommendation(paper=paper, score=ScoreBreakdown(composite=0.5))


class _StubReporter:
    """Minimal reporter that doesn't write anything — keeps test isolated."""

    name = "obsidian"

    def __init__(self) -> None:
        self.received: list[Recommendation] | None = None

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        self.received = list(recs)


def _stub_pipeline() -> Pipeline:
    return Pipeline(
        sources=[_StubSource()],
        filters=[],
        scorer=_StubScorer(),
        reporters=[_StubReporter()],
    )


# ---------------------------------------------------------------------------
# Chain-primitive fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chain_call_log(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path]]:
    """Capture ``compile_graph`` + ``compile_wiki`` calls in order.

    Returns a mutable list of ``(name, vault_path)`` tuples. Each chain
    helper is replaced with an async recorder that returns a fake
    success result so the tail of ``run_digest`` doesn't crash.
    """
    log: list[tuple[str, Path]] = []

    async def fake_compile_graph(
        vault_path: Path,
        *,
        wiki_subdir: str = "Wiki",
        force_rebuild: bool = False,
    ) -> CompileGraphResult:
        log.append(("compile_graph", vault_path))
        return CompileGraphResult(
            entity_count=1,
            edge_count=1,
            citation_count=0,
            edges_path=vault_path / wiki_subdir / ".graph" / "edges.jsonl",
            citations_path=vault_path / wiki_subdir / ".graph" / "citations.jsonl",
        )

    async def fake_compile_wiki(
        vault_path: Path,
        *,
        wiki_subdir: str = "Wiki",
        now: datetime | None = None,
        allow_auto_migrate: bool = True,
    ) -> CompileResult:
        log.append(("compile_wiki", vault_path))
        return CompileResult(
            index_path=vault_path / wiki_subdir / "index.md",
            concepts=2,
            sources=1,
        )

    monkeypatch.setattr(digest_runner, "compile_graph", fake_compile_graph)
    monkeypatch.setattr(digest_runner, "compile_wiki", fake_compile_wiki)
    return log


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear PAPERWIKI_NO_AUTO_CHAIN so each test sets it explicitly."""
    monkeypatch.delenv("PAPERWIKI_NO_AUTO_CHAIN", raising=False)


# ---------------------------------------------------------------------------
# Test 1 — happy path: both chain steps fire after successful digest
# ---------------------------------------------------------------------------


async def test_digest_chains_compile_graph_and_compile_wiki(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_call_log: list[tuple[str, Path]],
) -> None:
    """Successful digest with obsidian reporter → chain fires both steps."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _stub_pipeline())

    recipe_path = _write_recipe(tmp_path, vault_path)
    exit_code = await digest_runner.run_digest(recipe_path)

    assert exit_code == 0
    # Both chain steps invoked, each with the resolved vault path.
    assert chain_call_log == [
        ("compile_graph", vault_path),
        ("compile_wiki", vault_path),
    ]


# ---------------------------------------------------------------------------
# Test 2 — chain order: graph THEN wiki (graph stale would break index stats)
# ---------------------------------------------------------------------------


async def test_chain_runs_compile_graph_before_compile_wiki(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_call_log: list[tuple[str, Path]],
) -> None:
    """``compile_graph`` runs before ``compile_wiki`` so any future
    index-stat that consults the graph sees a fresh edges.jsonl."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _stub_pipeline())

    recipe_path = _write_recipe(tmp_path, vault_path)
    await digest_runner.run_digest(recipe_path)

    names = [step for step, _ in chain_call_log]
    assert names.index("compile_graph") < names.index("compile_wiki")


# ---------------------------------------------------------------------------
# Test 3 — compile_graph failure is non-fatal; compile_wiki still runs
# ---------------------------------------------------------------------------


async def test_compile_graph_failure_non_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``compile_graph`` raising must NOT fail digest; ``compile_wiki``
    still runs so the user keeps the index even if the graph is stale."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    log: list[str] = []

    async def boom_graph(vault_path: Path, **_kwargs: object) -> CompileGraphResult:
        log.append("compile_graph_attempted")
        msg = "graph permission denied"
        raise PaperWikiError(msg)

    async def fake_compile_wiki(vault_path: Path, **_kwargs: object) -> CompileResult:
        log.append("compile_wiki_ran")
        return CompileResult(index_path=vault_path / "Wiki" / "index.md", concepts=0, sources=0)

    monkeypatch.setattr(digest_runner, "compile_graph", boom_graph)
    monkeypatch.setattr(digest_runner, "compile_wiki", fake_compile_wiki)
    monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _stub_pipeline())

    recipe_path = _write_recipe(tmp_path, vault_path)
    exit_code = await digest_runner.run_digest(recipe_path)

    assert exit_code == 0  # digest still succeeded
    assert "compile_graph_attempted" in log
    assert "compile_wiki_ran" in log


# ---------------------------------------------------------------------------
# Test 4 — compile_wiki failure is non-fatal
# ---------------------------------------------------------------------------


async def test_compile_wiki_failure_non_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_call_log: list[tuple[str, Path]],
) -> None:
    """``compile_wiki`` raising must NOT fail digest."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()

    async def fake_compile_graph(vault_path: Path, **_kwargs: object) -> CompileGraphResult:
        return CompileGraphResult(
            entity_count=0,
            edge_count=0,
            citation_count=0,
            edges_path=vault_path / "Wiki" / ".graph" / "edges.jsonl",
            citations_path=vault_path / "Wiki" / ".graph" / "citations.jsonl",
        )

    async def boom_wiki(vault_path: Path, **_kwargs: object) -> CompileResult:
        msg = "wiki permission denied"
        raise PaperWikiError(msg)

    monkeypatch.setattr(digest_runner, "compile_graph", fake_compile_graph)
    monkeypatch.setattr(digest_runner, "compile_wiki", boom_wiki)
    monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _stub_pipeline())

    recipe_path = _write_recipe(tmp_path, vault_path)
    exit_code = await digest_runner.run_digest(recipe_path)

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Test 5 — opt-out via PAPERWIKI_NO_AUTO_CHAIN env var
# ---------------------------------------------------------------------------


async def test_paperwiki_no_auto_chain_env_skips_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_call_log: list[tuple[str, Path]],
) -> None:
    """``PAPERWIKI_NO_AUTO_CHAIN=1`` skips the chain entirely."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    monkeypatch.setenv("PAPERWIKI_NO_AUTO_CHAIN", "1")
    monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _stub_pipeline())

    recipe_path = _write_recipe(tmp_path, vault_path)
    exit_code = await digest_runner.run_digest(recipe_path)

    assert exit_code == 0
    assert chain_call_log == []


# ---------------------------------------------------------------------------
# Test 6 — opt-out via --no-auto-chain CLI flag
# ---------------------------------------------------------------------------


def test_no_auto_chain_flag_skips_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_call_log: list[tuple[str, Path]],
) -> None:
    """``paperwiki digest --no-auto-chain`` skips the chain via CLI flag."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _stub_pipeline())

    recipe_path = _write_recipe(tmp_path, vault_path)
    cli = CliRunner()
    result = cli.invoke(digest_runner.app, [str(recipe_path), "--no-auto-chain"])

    assert result.exit_code == 0, result.output
    assert chain_call_log == []


# ---------------------------------------------------------------------------
# Test 7 — digest failure (RecipeSchemaError-shaped) does NOT invoke chain
# ---------------------------------------------------------------------------


async def test_digest_failure_does_not_invoke_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_call_log: list[tuple[str, Path]],
) -> None:
    """If the digest itself raises, the chain must NOT run — there's
    nothing new to graph or compile yet."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()

    def boom_pipeline(recipe: object) -> Any:
        msg = "pipeline init failed"
        raise PaperWikiError(msg)

    monkeypatch.setattr(digest_runner, "instantiate_pipeline", boom_pipeline)

    recipe_path = _write_recipe(tmp_path, vault_path)
    with pytest.raises(PaperWikiError):
        await digest_runner.run_digest(recipe_path)

    assert chain_call_log == []


# ---------------------------------------------------------------------------
# Test 8 — recipe without obsidian reporter (no vault) skips chain silently
# ---------------------------------------------------------------------------


_RECIPE_NO_VAULT = """\
name: smoke
sources:
  - name: arxiv
    config:
      categories: [cs.AI]
      lookback_days: 1
filters: []
scorer:
  name: composite
  config:
    topics:
      - name: vlm
        keywords: [foundation model]
reporters:
  - name: markdown
    config:
      output_dir: {output_dir}
top_k: 5
"""


async def test_recipe_without_obsidian_reporter_skips_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_call_log: list[tuple[str, Path]],
) -> None:
    """No obsidian reporter → no vault path → chain silently skipped.

    The dedup-ledger is already vault-bound by the same logic; the
    chain follows the same ``vault_path is None → no-op`` rule.
    """
    output_dir = tmp_path / "out"
    recipe_path = tmp_path / "r.yaml"
    recipe_path.write_text(
        _RECIPE_NO_VAULT.format(output_dir=output_dir),
        encoding="utf-8",
    )
    monkeypatch.setattr(digest_runner, "instantiate_pipeline", lambda recipe: _stub_pipeline())

    exit_code = await digest_runner.run_digest(recipe_path)

    assert exit_code == 0
    assert chain_call_log == []
