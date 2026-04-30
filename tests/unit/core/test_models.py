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
    Edge,
    EdgeType,
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


# ---------------------------------------------------------------------------
# EdgeType (v0.4.x knowledge graph — task 9.156, D-L)
# ---------------------------------------------------------------------------


class TestEdgeType:
    def test_canonical_values(self) -> None:
        # Closed enum used at write-time. Writers may only emit these values.
        assert EdgeType.BUILDS_ON.value == "builds_on"
        assert EdgeType.IMPROVES_ON.value == "improves_on"
        assert EdgeType.SAME_PROBLEM_AS.value == "same_problem_as"
        assert EdgeType.CITES.value == "cites"
        assert EdgeType.CONTRADICTS.value == "contradicts"

    def test_extension_reserved_for_forward_compat(self) -> None:
        # Reserved per consensus plan iter-2 R12 forward-compat strategy:
        # v0.5+ patches add new edge classes via EdgeType.EXTENSION + subtype
        # field on Edge, without invalidating existing on-disk edges.
        assert EdgeType.EXTENSION.value == "extension"

    def test_str_enum_membership(self) -> None:
        # EdgeType is a str-enum so YAML/JSON serialization is natural.
        assert isinstance(EdgeType.BUILDS_ON, str)
        assert EdgeType("builds_on") is EdgeType.BUILDS_ON


# ---------------------------------------------------------------------------
# Edge (v0.4.x knowledge graph — task 9.156)
# ---------------------------------------------------------------------------


class TestEdge:
    def test_minimal_edge_constructs(self) -> None:
        edge = Edge(
            src="arxiv:2401.00001",
            dst="arxiv:2401.00002",
            type=EdgeType.BUILDS_ON,
        )
        assert edge.type is EdgeType.BUILDS_ON
        assert edge.weight == 1.0
        assert edge.evidence is None
        assert edge.subtype is None

    def test_edge_accepts_canonical_string_for_known_type(self) -> None:
        # Pydantic should coerce "builds_on" to EdgeType.BUILDS_ON when the
        # input is a known canonical value.
        edge = Edge(src="arxiv:a", dst="arxiv:b", type="builds_on")
        assert edge.type is EdgeType.BUILDS_ON

    def test_edge_preserves_unknown_type_verbatim(self) -> None:
        # Forward-compat (consensus plan iter-2 MS4 / Scenario 7):
        # readers must preserve unknown edge-type strings verbatim, not
        # raise. Idempotent re-emit writes them back unchanged. Writer-side
        # (this constructor) tolerates them as a str when no enum match.
        edge = Edge(src="arxiv:a", dst="arxiv:b", type="evaluates_on")
        assert edge.type == "evaluates_on"
        assert not isinstance(edge.type, EdgeType)

    def test_edge_unknown_type_round_trip_preserves_value(self) -> None:
        # `model_dump` must emit the unknown string verbatim so the on-disk
        # edges.jsonl can be byte-identical across rebuilds.
        edge = Edge(src="arxiv:a", dst="arxiv:b", type="evaluates_on")
        dumped = edge.model_dump(mode="json")
        assert dumped["type"] == "evaluates_on"
        rebuilt = Edge.model_validate(dumped)
        assert rebuilt.type == "evaluates_on"

    def test_edge_weight_bounds(self) -> None:
        # weight is constrained to [0.0, 1.0] mirroring ScoreBreakdown axes.
        with pytest.raises(ValidationError):
            Edge(src="arxiv:a", dst="arxiv:b", type=EdgeType.BUILDS_ON, weight=1.5)
        with pytest.raises(ValidationError):
            Edge(src="arxiv:a", dst="arxiv:b", type=EdgeType.BUILDS_ON, weight=-0.1)

    def test_edge_extension_carries_subtype(self) -> None:
        # EXTENSION is the forward-compat hook: the user (or a future
        # paperwiki version) sets `subtype` to disambiguate without enum
        # churn. v0.4.0 Python emits the canonical enum members only.
        edge = Edge(
            src="arxiv:a",
            dst="arxiv:b",
            type=EdgeType.EXTENSION,
            subtype="evaluates_on",
        )
        assert edge.type is EdgeType.EXTENSION
        assert edge.subtype == "evaluates_on"

    def test_edge_src_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            Edge(src="", dst="arxiv:b", type=EdgeType.BUILDS_ON)
        with pytest.raises(ValidationError):
            Edge(src="   ", dst="arxiv:b", type=EdgeType.BUILDS_ON)

    def test_edge_dst_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            Edge(src="arxiv:a", dst="", type=EdgeType.BUILDS_ON)
        with pytest.raises(ValidationError):
            Edge(src="arxiv:a", dst="  ", type=EdgeType.BUILDS_ON)

    def test_edge_evidence_is_optional_string(self) -> None:
        edge = Edge(
            src="arxiv:a",
            dst="arxiv:b",
            type=EdgeType.CITES,
            evidence="cited in §3.2 of arxiv:a",
        )
        assert edge.evidence == "cited in §3.2 of arxiv:a"

    def test_edge_serializable_round_trip_canonical(self) -> None:
        edge = Edge(
            src="arxiv:2401.00001",
            dst="concepts/transformer",
            type=EdgeType.BUILDS_ON,
            weight=0.8,
            evidence="builds attention layer on §3 of arxiv:transformer",
        )
        rebuilt = Edge.model_validate(edge.model_dump(mode="json"))
        assert rebuilt == edge
