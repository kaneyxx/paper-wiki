"""Unit tests for paperwiki.plugins.scorers.composite.CompositeScorer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
)
from paperwiki.plugins.filters.relevance import Topic
from paperwiki.plugins.scorers.composite import CompositeScorer


def _make_paper(
    *,
    canonical_id: str = "arxiv:0001.0001",
    title: str = "Generic Paper",
    abstract: str = "Generic abstract content.",
    categories: list[str] | None = None,
    citation_count: int | None = None,
    days_old: int = 5,
) -> Paper:
    target = datetime(2026, 4, 25, tzinfo=UTC)
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="A. Author")],
        abstract=abstract,
        published_at=target - timedelta(days=days_old),
        categories=categories or [],
        citation_count=citation_count,
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


async def _stream(papers: list[Paper]) -> AsyncIterator[Paper]:
    for paper in papers:
        yield paper


async def _score_one(scorer: CompositeScorer, paper: Paper, ctx: RunContext) -> Recommendation:
    """Run the scorer over a single paper and return the resulting recommendation."""
    return await anext(scorer.score(_stream([paper]), ctx))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestCompositeScorerConstruction:
    def test_empty_topics_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one topic"):
            CompositeScorer(topics=[])

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="sum to 1"):
            CompositeScorer(
                topics=[Topic(name="x", keywords=["x"])],
                weights={
                    "relevance": 0.6,
                    "novelty": 0.6,
                    "momentum": 0.0,
                    "rigor": 0.0,
                },
            )

    def test_default_weights_used_when_unspecified(self) -> None:
        from paperwiki.core.models import DEFAULT_SCORE_WEIGHTS

        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["x"])])
        assert scorer.weights == DEFAULT_SCORE_WEIGHTS


# ---------------------------------------------------------------------------
# Score axes
# ---------------------------------------------------------------------------


class TestRelevance:
    async def test_high_relevance_when_topic_matches_title_and_abstract(self) -> None:
        scorer = CompositeScorer(
            topics=[
                Topic(name="vlm", keywords=["foundation model", "vision"]),
            ],
        )
        paper = _make_paper(
            title="A Foundation Model for Vision",
            abstract="We introduce a new foundation model and study vision tasks.",
        )
        ctx = _make_ctx()
        recs = [r async for r in scorer.score(_stream([paper]), ctx)]

        assert recs[0].score.relevance > 0.5
        assert "vlm" in recs[0].matched_topics

    async def test_zero_relevance_when_no_topic_matches(self) -> None:
        scorer = CompositeScorer(topics=[Topic(name="vlm", keywords=["foundation model"])])
        paper = _make_paper(title="Combinatorics", abstract="Pure math.")
        ctx = _make_ctx()
        recs = [r async for r in scorer.score(_stream([paper]), ctx)]

        assert recs[0].score.relevance == 0.0
        assert recs[0].matched_topics == []

    async def test_relevance_clamped_to_one(self) -> None:
        # Many keyword hits; relevance must still be in [0, 1].
        scorer = CompositeScorer(
            topics=[Topic(name="vlm", keywords=["model", "vision", "language", "image"])],
        )
        paper = _make_paper(
            title="Model Model Model Model",
            abstract="vision language image model vision language image model",
        )
        ctx = _make_ctx()
        recs = [r async for r in scorer.score(_stream([paper]), ctx)]

        assert 0.0 <= recs[0].score.relevance <= 1.0


class TestNovelty:
    async def test_novelty_boosts_on_innovation_keywords(self) -> None:
        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["x"])])
        innovative = _make_paper(
            title="x state-of-the-art benchmark",
            abstract="We propose a novel approach that surpasses prior work.",
        )
        bland = _make_paper(
            title="x discussion",
            abstract="A summary of existing techniques.",
        )

        rec_innov = await _score_one(scorer, innovative, _make_ctx())
        rec_bland = await _score_one(scorer, bland, _make_ctx())

        assert rec_innov.score.novelty > rec_bland.score.novelty


class TestMomentum:
    async def test_momentum_scales_with_citation_count(self) -> None:
        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["x"])])
        cited = _make_paper(title="x", abstract="x", citation_count=200)
        uncited = _make_paper(title="x", abstract="x", citation_count=0)

        rec_cited = await _score_one(scorer, cited, _make_ctx())
        rec_uncited = await _score_one(scorer, uncited, _make_ctx())

        assert rec_cited.score.momentum > rec_uncited.score.momentum

    async def test_momentum_clamped_to_one(self) -> None:
        scorer = CompositeScorer(
            topics=[Topic(name="x", keywords=["x"])],
            momentum_full_citations=10,
        )
        paper = _make_paper(title="x", abstract="x", citation_count=100_000)
        rec = await _score_one(scorer, paper, _make_ctx())
        assert rec.score.momentum == 1.0

    async def test_missing_citation_count_uses_recency_bonus(self) -> None:
        # Without citation data, fresh papers still get a momentum signal.
        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["x"])])
        fresh = _make_paper(title="x", abstract="x", citation_count=None, days_old=1)
        stale = _make_paper(title="x", abstract="x", citation_count=None, days_old=300)

        rec_fresh = await _score_one(scorer, fresh, _make_ctx())
        rec_stale = await _score_one(scorer, stale, _make_ctx())

        assert rec_fresh.score.momentum > rec_stale.score.momentum


class TestRigor:
    async def test_rigor_boosts_on_experiment_keywords(self) -> None:
        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["x"])])
        rigorous = _make_paper(
            title="x",
            abstract="We conduct experiments and ablation studies on a benchmark.",
        )
        sketchy = _make_paper(title="x", abstract="A philosophical essay.")

        rec_r = await _score_one(scorer, rigorous, _make_ctx())
        rec_s = await _score_one(scorer, sketchy, _make_ctx())

        assert rec_r.score.rigor > rec_s.score.rigor


# ---------------------------------------------------------------------------
# Composite + integration
# ---------------------------------------------------------------------------


class TestComposite:
    async def test_composite_within_unit_interval(self) -> None:
        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["foundation model"])])
        paper = _make_paper(
            title="A Foundation Model for Vision",
            abstract="We propose a novel approach with experiments.",
            citation_count=50,
        )
        rec = await _score_one(scorer, paper, _make_ctx())

        assert 0.0 <= rec.score.composite <= 1.0
        # Composite must equal weighted sum of individual axes.
        expected = rec.score.compute_composite(scorer.weights)
        assert abs(rec.score.composite - expected) < 1e-9

    async def test_yields_recommendation_per_paper(self) -> None:
        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["x"])])
        papers = [
            _make_paper(canonical_id="arxiv:1", title="x"),
            _make_paper(canonical_id="arxiv:2", title="x"),
            _make_paper(canonical_id="arxiv:3", title="x"),
        ]
        ctx = _make_ctx()
        recs = [r async for r in scorer.score(_stream(papers), ctx)]

        assert len(recs) == 3
        assert all(isinstance(r, Recommendation) for r in recs)
        assert {r.paper.canonical_id for r in recs} == {"arxiv:1", "arxiv:2", "arxiv:3"}

    async def test_scorer_satisfies_protocol(self) -> None:
        from paperwiki.core.protocols import Scorer

        scorer = CompositeScorer(topics=[Topic(name="x", keywords=["x"])])
        assert isinstance(scorer, Scorer)


# ---------------------------------------------------------------------------
# Per-topic strengths (Task 9.9)
# ---------------------------------------------------------------------------


class TestPerTopicStrengths:
    async def test_composite_scorer_emits_per_topic_strengths(self) -> None:
        """score() must serialise per-topic strengths into ScoreBreakdown.notes."""
        import json

        scorer = CompositeScorer(
            topics=[
                Topic(name="vlm", keywords=["vision", "language"]),
                Topic(name="pathology", keywords=["pathology", "WSI"]),
            ],
        )
        paper = _make_paper(
            title="Vision language model for pathology",
            abstract="We study vision language models applied to pathology WSI slides.",
        )
        rec = await _score_one(scorer, paper, _make_ctx())

        assert rec.score.notes is not None
        assert "topic_strengths" in rec.score.notes

        strengths = json.loads(rec.score.notes["topic_strengths"])
        assert isinstance(strengths, dict)
        assert "vlm" in strengths
        assert "pathology" in strengths
        # Both topics matched — strengths must be positive
        assert strengths["vlm"] > 0.0
        assert strengths["pathology"] > 0.0

    async def test_unmatched_topic_has_zero_strength(self) -> None:
        """Topics that produce no keyword or category hits must have strength 0.0."""
        import json

        scorer = CompositeScorer(
            topics=[
                Topic(name="matched", keywords=["vision"]),
                Topic(name="unmatched", keywords=["combinatorics"]),
            ],
        )
        paper = _make_paper(title="Vision model", abstract="Study of vision systems.")
        rec = await _score_one(scorer, paper, _make_ctx())

        strengths = json.loads(rec.score.notes["topic_strengths"])  # type: ignore[index]
        assert strengths["matched"] > 0.0
        assert strengths["unmatched"] == 0.0
