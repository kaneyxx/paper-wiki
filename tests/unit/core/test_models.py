"""Unit tests for paperwiki.core.models.

The models are the canonical, source-agnostic representation of the data
that flows through the pipeline. They must validate aggressively at the
boundary so downstream stages can trust their inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)

# ---------------------------------------------------------------------------
# Author
# ---------------------------------------------------------------------------


class TestAuthor:
    def test_author_requires_non_empty_name(self) -> None:
        with pytest.raises(ValidationError):
            Author(name="")

    def test_author_strips_whitespace_in_name(self) -> None:
        author = Author(name="  Yann LeCun  ")
        assert author.name == "Yann LeCun"

    def test_author_optional_affiliation(self) -> None:
        author = Author(name="Yann LeCun")
        assert author.affiliation is None
        author = Author(name="Yann LeCun", affiliation="Meta AI")
        assert author.affiliation == "Meta AI"


# ---------------------------------------------------------------------------
# Paper
# ---------------------------------------------------------------------------


def _sample_paper(**overrides: object) -> Paper:
    """Construct a valid Paper, allowing field overrides for negative tests."""
    defaults: dict[str, object] = {
        "canonical_id": "arxiv:2506.13063",
        "title": "PRISM2: Unlocking Multi-Modal General Pathology AI",
        "authors": [Author(name="George Shaikovski")],
        "abstract": "We present PRISM2, a vision-language foundation model for pathology...",
        "published_at": datetime(2026, 4, 20, tzinfo=UTC),
        "categories": ["cs.CV", "cs.LG"],
        "pdf_url": "https://arxiv.org/pdf/2506.13063",
        "landing_url": "https://arxiv.org/abs/2506.13063",
    }
    defaults.update(overrides)
    return Paper(**defaults)  # type: ignore[arg-type]


class TestPaper:
    def test_minimal_paper_constructs(self) -> None:
        paper = _sample_paper()
        assert paper.canonical_id == "arxiv:2506.13063"
        assert paper.title.startswith("PRISM2")
        assert paper.authors[0].name == "George Shaikovski"
        assert paper.citation_count is None
        assert paper.raw == {}
        assert paper.categories == ["cs.CV", "cs.LG"]

    def test_canonical_id_must_be_namespaced(self) -> None:
        # Plain numeric id is invalid — caller must namespace by source.
        with pytest.raises(ValidationError):
            _sample_paper(canonical_id="2506.13063")

    def test_canonical_id_lowercases_namespace(self) -> None:
        paper = _sample_paper(canonical_id="ArXiv:2506.13063")
        assert paper.canonical_id == "arxiv:2506.13063"

    def test_canonical_id_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            _sample_paper(canonical_id="")

    def test_title_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError):
            _sample_paper(title="   ")

    def test_authors_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            _sample_paper(authors=[])

    def test_published_at_must_be_timezone_aware(self) -> None:
        # Naive datetimes ambiguate local vs UTC; we require explicit tz.
        with pytest.raises(ValidationError):
            _sample_paper(published_at=datetime(2026, 4, 20))  # noqa: DTZ001

    def test_paper_is_serializable_round_trip(self) -> None:
        paper = _sample_paper()
        dumped = paper.model_dump(mode="json")
        rebuilt = Paper.model_validate(dumped)
        assert rebuilt == paper


# ---------------------------------------------------------------------------
# ScoreBreakdown
# ---------------------------------------------------------------------------


class TestScoreBreakdown:
    def test_default_score_is_all_zero(self) -> None:
        score = ScoreBreakdown()
        assert score.relevance == score.novelty == score.momentum == 0.0
        assert score.rigor == score.composite == 0.0
        assert score.notes == {}

    def test_negative_scores_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScoreBreakdown(relevance=-0.1)

    def test_scores_above_one_rejected(self) -> None:
        # Internal contract: each axis is normalized to [0, 1].
        with pytest.raises(ValidationError):
            ScoreBreakdown(novelty=1.1)

    def test_compute_composite_default_weights(self) -> None:
        score = ScoreBreakdown(relevance=0.8, novelty=0.4, momentum=0.6, rigor=0.5)
        # Default weights: 0.4/0.2/0.3/0.1
        composite = score.compute_composite()
        assert pytest.approx(composite, rel=1e-9) == 0.8 * 0.4 + 0.4 * 0.2 + 0.6 * 0.3 + 0.5 * 0.1

    def test_compute_composite_custom_weights(self) -> None:
        score = ScoreBreakdown(relevance=1.0, novelty=1.0, momentum=1.0, rigor=1.0)
        composite = score.compute_composite(
            weights={"relevance": 0.25, "novelty": 0.25, "momentum": 0.25, "rigor": 0.25}
        )
        assert composite == pytest.approx(1.0)

    def test_compute_composite_weights_must_sum_to_one(self) -> None:
        score = ScoreBreakdown()
        with pytest.raises(ValueError, match="sum to 1"):
            score.compute_composite(
                weights={"relevance": 0.6, "novelty": 0.6, "momentum": 0.0, "rigor": 0.0}
            )

    def test_compute_composite_weights_must_cover_all_axes(self) -> None:
        score = ScoreBreakdown()
        with pytest.raises(ValueError, match="missing axes"):
            score.compute_composite(weights={"relevance": 0.5, "novelty": 0.5})


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


class TestRecommendation:
    def test_minimal_recommendation(self) -> None:
        rec = Recommendation(paper=_sample_paper(), score=ScoreBreakdown(relevance=0.5))
        assert rec.matched_topics == []
        assert rec.rationale is None

    def test_recommendation_round_trip(self) -> None:
        rec = Recommendation(
            paper=_sample_paper(),
            score=ScoreBreakdown(relevance=0.7, novelty=0.3, composite=0.5),
            matched_topics=["pathology", "vision-language"],
            rationale="High relevance and novel multimodal architecture.",
        )
        rebuilt = Recommendation.model_validate(rec.model_dump(mode="json"))
        assert rebuilt == rec


# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------


class TestRunContext:
    def test_run_context_increment_counter(self) -> None:
        ctx = RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})
        ctx.increment("source.fetch")
        ctx.increment("source.fetch")
        ctx.increment("filter.dropped", by=3)
        assert ctx.counters == {"source.fetch": 2, "filter.dropped": 3}

    def test_run_context_target_date_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValidationError):
            RunContext(target_date=datetime(2026, 4, 25), config_snapshot={})  # noqa: DTZ001
