"""Unit tests for paperwiki.core.pipeline.

The pipeline orchestrates Source -> Filter -> Scorer -> Reporter (with an
optional WikiBackend) entirely in the async domain. Tests use minimal,
explicit stubs rather than mocking — this keeps the contract of each
protocol crisp and makes failures easy to localize.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.core.pipeline import Pipeline, PipelineResult

# ---------------------------------------------------------------------------
# Helpers and stubs
# ---------------------------------------------------------------------------


def _make_paper(canonical_id: str, title: str = "Stub") -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="A. Author")],
        abstract="Stub abstract.",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 1, 1, tzinfo=UTC), config_snapshot={})


class StaticSource:
    def __init__(self, name: str, papers: list[Paper]) -> None:
        self.name = name
        self._papers = papers

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        for paper in self._papers:
            yield paper


class IdentityFilter:
    name = "identity"

    async def apply(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Paper]:
        async for paper in papers:
            yield paper


class DropByPrefixFilter:
    """Drops papers whose canonical_id starts with the given prefix."""

    def __init__(self, prefix: str) -> None:
        self.name = f"drop-by-prefix:{prefix}"
        self._prefix = prefix

    async def apply(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Paper]:
        async for paper in papers:
            if paper.canonical_id.startswith(self._prefix):
                ctx.increment(f"filter.{self.name}.dropped")
                continue
            yield paper


class ConstantScorer:
    """Assigns a constant score to every paper."""

    name = "constant"

    def __init__(self, score: ScoreBreakdown) -> None:
        self._score = score

    async def score(
        self, papers: AsyncIterator[Paper], ctx: RunContext
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            yield Recommendation(paper=paper, score=self._score)


class IdentityScorer:
    """Composite score taken from the last digit of canonical_id (0-9 → 0.0-0.9)."""

    name = "identity-by-id"

    async def score(
        self, papers: AsyncIterator[Paper], ctx: RunContext
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            last = paper.canonical_id[-1]
            composite = (int(last) / 10.0) if last.isdigit() else 0.0
            yield Recommendation(paper=paper, score=ScoreBreakdown(composite=composite))


class CollectingReporter:
    name = "collecting"

    def __init__(self) -> None:
        self.collected: list[Recommendation] | None = None

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        self.collected = list(recs)


class CollectingWikiBackend:
    def __init__(self) -> None:
        self.upserted: list[Recommendation] = []

    async def upsert_paper(self, rec: Recommendation) -> None:
        self.upserted.append(rec)

    async def query(self, q: str) -> list[Recommendation]:
        return []


# ---------------------------------------------------------------------------
# Construction and validation
# ---------------------------------------------------------------------------


class TestPipelineConstruction:
    def test_pipeline_requires_at_least_one_source(self) -> None:
        with pytest.raises(ValueError, match="at least one source"):
            Pipeline(
                sources=[],
                filters=[],
                scorer=ConstantScorer(ScoreBreakdown()),
                reporters=[CollectingReporter()],
            )

    def test_pipeline_requires_at_least_one_reporter(self) -> None:
        with pytest.raises(ValueError, match="at least one reporter"):
            Pipeline(
                sources=[StaticSource("s", [])],
                filters=[],
                scorer=ConstantScorer(ScoreBreakdown()),
                reporters=[],
            )


# ---------------------------------------------------------------------------
# Run behavior
# ---------------------------------------------------------------------------


class TestPipelineRun:
    async def test_runs_end_to_end_with_single_source(self) -> None:
        paper = _make_paper("arxiv:0001.0001")
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("s1", [paper])],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown(composite=0.5)),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx())

        assert isinstance(result, PipelineResult)
        assert len(result.recommendations) == 1
        assert result.recommendations[0].paper == paper
        assert reporter.collected == result.recommendations

    async def test_fans_in_from_multiple_sources(self) -> None:
        p1 = _make_paper("arxiv:0001.0001")
        p2 = _make_paper("arxiv:0002.0002")
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[
                StaticSource("s1", [p1]),
                StaticSource("s2", [p2]),
            ],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown()),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx())

        ids = {r.paper.canonical_id for r in result.recommendations}
        assert ids == {"arxiv:0001.0001", "arxiv:0002.0002"}

    async def test_applies_filters_in_order(self) -> None:
        p1 = _make_paper("arxiv:0001.0001")
        p2 = _make_paper("biorxiv:0002.0002")
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("s", [p1, p2])],
            filters=[DropByPrefixFilter("biorxiv:")],
            scorer=ConstantScorer(ScoreBreakdown()),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx())

        assert {r.paper.canonical_id for r in result.recommendations} == {"arxiv:0001.0001"}
        assert result.counters.get("filter.drop-by-prefix:biorxiv:.dropped") == 1

    async def test_chains_multiple_filters(self) -> None:
        papers = [
            _make_paper("arxiv:0001.0001"),
            _make_paper("biorxiv:0002.0002"),
            _make_paper("medrxiv:0003.0003"),
        ]
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("s", papers)],
            filters=[DropByPrefixFilter("biorxiv:"), DropByPrefixFilter("medrxiv:")],
            scorer=ConstantScorer(ScoreBreakdown()),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx())

        assert {r.paper.canonical_id for r in result.recommendations} == {"arxiv:0001.0001"}

    async def test_top_k_selects_highest_composite(self) -> None:
        papers = [
            _make_paper("arxiv:0001.0001"),  # composite 0.1
            _make_paper("arxiv:0001.0009"),  # composite 0.9
            _make_paper("arxiv:0001.0005"),  # composite 0.5
        ]
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("s", papers)],
            filters=[],
            scorer=IdentityScorer(),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx(), top_k=2)

        ids = [r.paper.canonical_id for r in result.recommendations]
        assert ids == ["arxiv:0001.0009", "arxiv:0001.0005"]

    async def test_reporters_all_receive_full_top_k(self) -> None:
        paper = _make_paper("arxiv:0001.0001")
        r1 = CollectingReporter()
        r2 = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("s", [paper])],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown(composite=0.5)),
            reporters=[r1, r2],
        )

        await pipeline.run(_make_ctx())

        assert r1.collected == r2.collected
        assert r1.collected is not None
        assert len(r1.collected) == 1

    async def test_wiki_upsert_called_when_provided(self) -> None:
        paper = _make_paper("arxiv:0001.0001")
        reporter = CollectingReporter()
        wiki = CollectingWikiBackend()
        pipeline = Pipeline(
            sources=[StaticSource("s", [paper])],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown(composite=0.5)),
            reporters=[reporter],
            wiki=wiki,
        )

        await pipeline.run(_make_ctx())

        assert len(wiki.upserted) == 1
        assert wiki.upserted[0].paper == paper

    async def test_wiki_skipped_when_not_provided(self) -> None:
        # Run without wiki and confirm it does not raise; also confirm
        # ctx counters do not accidentally include wiki keys.
        paper = _make_paper("arxiv:0001.0001")
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("s", [paper])],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown(composite=0.5)),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx())

        assert all(not k.startswith("wiki.") for k in result.counters)

    async def test_counters_track_source_fetch(self) -> None:
        papers = [_make_paper(f"arxiv:0001.000{i}") for i in range(1, 4)]
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("arxiv", papers)],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown()),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx())

        assert result.counters.get("source.arxiv.fetched") == 3

    async def test_empty_source_produces_empty_result(self) -> None:
        reporter = CollectingReporter()
        pipeline = Pipeline(
            sources=[StaticSource("empty", [])],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown()),
            reporters=[reporter],
        )

        result = await pipeline.run(_make_ctx())

        assert result.recommendations == []
        assert reporter.collected == []

    async def test_failing_source_does_not_break_other_sources(self) -> None:
        """One source raising IntegrationError must not abort the whole digest.

        Real-world driver: ``semantic_scholar`` 429-rate-limits while
        ``arxiv`` is healthy. The user wants the arxiv-side digest, not
        a hard failure that loses the day's recommendations.
        """
        from paperwiki.core.errors import IntegrationError

        good_papers = [_make_paper("arxiv:1111.1111", title="Survives")]

        class FlakyS2Source:
            name = "semantic_scholar"

            async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
                msg = "S2 returned HTTP 429"
                raise IntegrationError(msg)
                yield  # pragma: no cover - unreachable, here for typing

        reporter = CollectingReporter()
        ctx = _make_ctx()
        pipeline = Pipeline(
            sources=[StaticSource("arxiv", good_papers), FlakyS2Source()],
            filters=[],
            scorer=ConstantScorer(ScoreBreakdown()),
            reporters=[reporter],
        )

        result = await pipeline.run(ctx)

        # The healthy source's papers still flow through to the reporter.
        assert len(result.recommendations) == 1
        assert result.recommendations[0].paper.title == "Survives"
        # The failure is surfaced as a counter for runners/SKILLs to read.
        assert ctx.counters["source.semantic_scholar.errors"] == 1
