"""Unit tests for paperwiki.plugins.filters.relevance.RelevanceFilter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from paperwiki.core.models import Author, Paper, RunContext
from paperwiki.plugins.filters.relevance import RelevanceFilter, Topic


def _make_paper(
    *,
    canonical_id: str = "arxiv:0001.0001",
    title: str = "Generic Paper",
    abstract: str = "Generic abstract content.",
    categories: list[str] | None = None,
) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="A. Author")],
        abstract=abstract,
        published_at=datetime(2026, 4, 20, tzinfo=UTC),
        categories=categories or [],
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


async def _stream(papers: list[Paper]) -> AsyncIterator[Paper]:
    for paper in papers:
        yield paper


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------


class TestTopic:
    def test_topic_requires_non_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name"):
            Topic(name="")

    def test_topic_lowercases_keywords_and_categories(self) -> None:
        topic = Topic(
            name="LLM",
            keywords=["Foundation Model", "TRANSFORMER"],
            categories=["CS.AI"],
        )
        # Stored canonical lowercase for fast comparison.
        assert "foundation model" in topic.keyword_set
        assert "transformer" in topic.keyword_set
        assert "cs.ai" in topic.category_set


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_topic_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one topic"):
            RelevanceFilter(topics=[])

    def test_topic_must_have_signal(self) -> None:
        # A topic with neither keywords nor categories matches nothing,
        # which is almost certainly user error — fail fast.
        with pytest.raises(ValueError, match="keywords or categories"):
            RelevanceFilter(topics=[Topic(name="empty")])


# ---------------------------------------------------------------------------
# Matching behavior
# ---------------------------------------------------------------------------


class TestApply:
    async def test_keyword_match_in_title_kept(self) -> None:
        topic = Topic(name="LLM", keywords=["foundation model"])
        flt = RelevanceFilter(topics=[topic])
        paper = _make_paper(title="A Foundation Model for Vision")

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == [paper]

    async def test_keyword_match_in_abstract_kept(self) -> None:
        topic = Topic(name="LLM", keywords=["transformer"])
        flt = RelevanceFilter(topics=[topic])
        paper = _make_paper(
            title="Some Paper",
            abstract="We use a Transformer architecture for the backbone.",
        )

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == [paper]

    async def test_category_match_kept(self) -> None:
        topic = Topic(name="ml", categories=["cs.LG"])
        flt = RelevanceFilter(topics=[topic])
        paper = _make_paper(
            title="Unrelated Title",
            abstract="Unrelated abstract.",
            categories=["cs.LG"],
        )

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == [paper]

    async def test_no_match_dropped(self) -> None:
        topic = Topic(name="LLM", keywords=["foundation model"], categories=["cs.AI"])
        flt = RelevanceFilter(topics=[topic])
        paper = _make_paper(
            title="A Paper on Combinatorics",
            abstract="Pure math content.",
            categories=["math.CO"],
        )

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == []
        assert ctx.counters["filter.relevance.dropped"] == 1

    async def test_match_across_topics(self) -> None:
        topic_a = Topic(name="vision", keywords=["segmentation"])
        topic_b = Topic(name="llm", keywords=["transformer"])
        flt = RelevanceFilter(topics=[topic_a, topic_b])
        paper = _make_paper(title="Transformer-based Approach")

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == [paper]

    async def test_keyword_matching_is_case_insensitive(self) -> None:
        topic = Topic(name="x", keywords=["foo"])
        flt = RelevanceFilter(topics=[topic])
        paper = _make_paper(title="FOO bar")

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == [paper]

    async def test_keyword_matches_word_boundary(self) -> None:
        # "ai" should NOT match inside "rain" — naive substring matching
        # would make this a false positive.
        topic = Topic(name="ai", keywords=["ai"])
        flt = RelevanceFilter(topics=[topic])
        paper = _make_paper(
            title="Rain Falls Mostly on the Plain",
            abstract="Climate data.",
        )

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == []

    async def test_keyword_with_spaces_matches_phrase(self) -> None:
        topic = Topic(name="vlm", keywords=["vision language model"])
        flt = RelevanceFilter(topics=[topic])
        paper = _make_paper(
            title="Bench for Vision Language Model Evaluation",
            abstract="A new benchmark.",
        )

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([paper]), ctx)]

        assert kept == [paper]

    async def test_filter_satisfies_protocol(self) -> None:
        from paperwiki.core.protocols import Filter

        flt = RelevanceFilter(topics=[Topic(name="x", keywords=["x"])])
        assert isinstance(flt, Filter)

    async def test_mixed_stream(self) -> None:
        topic = Topic(name="ml", keywords=["transformer"], categories=["cs.LG"])
        flt = RelevanceFilter(topics=[topic])

        keep = _make_paper(canonical_id="arxiv:1", title="Transformer Paper")
        keep_cat = _make_paper(canonical_id="arxiv:2", categories=["cs.LG"])
        drop = _make_paper(canonical_id="arxiv:3", title="Unrelated")

        ctx = _make_ctx()
        kept = [p async for p in flt.apply(_stream([keep, keep_cat, drop]), ctx)]

        assert {p.canonical_id for p in kept} == {"arxiv:1", "arxiv:2"}
        assert ctx.counters["filter.relevance.dropped"] == 1
