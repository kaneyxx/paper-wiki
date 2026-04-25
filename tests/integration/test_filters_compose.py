"""Integration: RecencyFilter + RelevanceFilter + DedupFilter through Pipeline.

Validates the Phase 3 deliverable that the three built-in filters
compose end-to-end inside a real :class:`Pipeline` and that the result
is the intersection of all three predicates.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.core.pipeline import Pipeline
from paperwiki.plugins.filters import (
    DedupFilter,
    MarkdownVaultKeyLoader,
    RecencyFilter,
    RelevanceFilter,
    Topic,
)


def _make_paper(
    canonical_id: str,
    *,
    title: str,
    days_old: int,
    abstract: str = "Generic abstract content.",
    categories: list[str] | None = None,
) -> Paper:
    target = datetime(2026, 4, 25, tzinfo=UTC)
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="A. Author")],
        abstract=abstract,
        published_at=target - timedelta(days=days_old),
        categories=categories or [],
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


class StaticSource:
    name = "static"

    def __init__(self, papers: list[Paper]) -> None:
        self._papers = papers

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        for paper in self._papers:
            yield paper


class IdentityScorer:
    """Trivial scorer: every paper gets composite=0.5 so order is preserved."""

    name = "identity"

    async def score(
        self, papers: AsyncIterator[Paper], ctx: RunContext
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            yield Recommendation(paper=paper, score=ScoreBreakdown(composite=0.5))


class CollectingReporter:
    name = "collect"

    def __init__(self) -> None:
        self.received: list[Recommendation] = []

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        self.received = list(recs)


async def test_three_filters_compose_through_pipeline(tmp_path: Path) -> None:
    """End-to-end: relevance keeps LLM papers, recency keeps last-7-days,
    dedup drops anything matching the vault."""
    # Seed the "vault" with one paper that should be dedup'd.
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "existing.md").write_text(
        '---\npaper_id: "arxiv:2506.13063"\ntitle: "Existing PRISM2 Paper"\n---\nbody.\n',
        encoding="utf-8",
    )

    # Curate the input stream so each filter has something to drop:
    keep = _make_paper(
        canonical_id="arxiv:0001.0001",
        title="Foundation Model for Vision Language",
        days_old=2,
    )
    drop_old = _make_paper(
        canonical_id="arxiv:0002.0002",
        title="Foundation Model Old Paper",
        days_old=200,
    )
    drop_irrelevant = _make_paper(
        canonical_id="arxiv:0003.0003",
        title="Combinatorics on Pure Math",
        abstract="Pure math content.",
        days_old=1,
    )
    drop_dup = _make_paper(
        canonical_id="arxiv:2506.13063",
        title="Foundation Model Already In Vault",
        days_old=2,
    )

    source_papers = [keep, drop_old, drop_irrelevant, drop_dup]

    pipeline = Pipeline(
        sources=[StaticSource(source_papers)],
        filters=[
            RecencyFilter(max_days=7),
            RelevanceFilter(topics=[Topic(name="llm", keywords=["foundation model"])]),
            DedupFilter(loaders=[MarkdownVaultKeyLoader(root=vault_root)]),
        ],
        scorer=IdentityScorer(),
        reporters=[CollectingReporter()],
    )

    ctx = _make_ctx()
    result = await pipeline.run(ctx)

    # Only the "keep" paper survives all three filters.
    assert {r.paper.canonical_id for r in result.recommendations} == {"arxiv:0001.0001"}

    # Each filter recorded its drop in counters.
    assert ctx.counters["filter.recency.dropped"] == 1
    assert ctx.counters["filter.relevance.dropped"] == 1
    assert ctx.counters["filter.dedup.dropped"] == 1


async def test_filter_order_matters_for_counters(tmp_path: Path) -> None:
    """Filters apply in declaration order; later filters never see what
    earlier filters dropped, so counters reflect the post-stream sizes."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "n.md").write_text(
        '---\npaper_id: "2506.13063"\ntitle: "Existing"\n---\n',
        encoding="utf-8",
    )

    # If RecencyFilter runs first, the irrelevant + dedup'd papers below
    # are still old enough to be dropped by recency, never reaching the
    # later filters.
    p_old_irrelevant = _make_paper(
        canonical_id="arxiv:0002.0002",
        title="Old Irrelevant",
        days_old=200,
    )
    p_old_dup = _make_paper(
        canonical_id="arxiv:2506.13063",
        title="Old Duplicate",
        days_old=200,
    )
    pipeline = Pipeline(
        sources=[StaticSource([p_old_irrelevant, p_old_dup])],
        filters=[
            RecencyFilter(max_days=7),
            RelevanceFilter(topics=[Topic(name="llm", keywords=["foundation model"])]),
            DedupFilter(loaders=[MarkdownVaultKeyLoader(root=vault_root)]),
        ],
        scorer=IdentityScorer(),
        reporters=[CollectingReporter()],
    )

    ctx = _make_ctx()
    await pipeline.run(ctx)

    # Both papers were old, so recency dropped both. Relevance and dedup
    # never saw them.
    assert ctx.counters["filter.recency.dropped"] == 2
    assert "filter.relevance.dropped" not in ctx.counters
    assert "filter.dedup.dropped" not in ctx.counters
