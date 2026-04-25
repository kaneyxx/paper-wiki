"""Unit tests for paperwiki.plugins.filters.recency.RecencyFilter.

The recency filter is a sliding window centered on ``ctx.target_date``:
papers published more than ``max_days`` before that date are dropped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from paperwiki.core.models import Author, Paper, RunContext
from paperwiki.plugins.filters.recency import RecencyFilter


def _make_paper(canonical_id: str, published_at: datetime) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title="Stub Title",
        authors=[Author(name="A. Author")],
        abstract="Stub abstract.",
        published_at=published_at,
    )


def _make_ctx(target: datetime | None = None) -> RunContext:
    return RunContext(
        target_date=target or datetime(2026, 4, 25, tzinfo=UTC),
        config_snapshot={},
    )


async def _stream(papers: list[Paper]) -> AsyncIterator[Paper]:
    for paper in papers:
        yield paper


class TestRecencyFilterConstruction:
    def test_max_days_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_days must be"):
            RecencyFilter(max_days=0)

    def test_max_days_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_days must be"):
            RecencyFilter(max_days=-1)


class TestRecencyFilterApply:
    async def test_keeps_recent_paper_inside_window(self) -> None:
        ctx = _make_ctx()
        recent = _make_paper("arxiv:1", ctx.target_date - timedelta(days=2))

        flt = RecencyFilter(max_days=7)
        kept = [p async for p in flt.apply(_stream([recent]), ctx)]

        assert kept == [recent]

    async def test_drops_paper_outside_window(self) -> None:
        ctx = _make_ctx()
        old = _make_paper("arxiv:old", ctx.target_date - timedelta(days=30))

        flt = RecencyFilter(max_days=7)
        kept = [p async for p in flt.apply(_stream([old]), ctx)]

        assert kept == []
        assert ctx.counters["filter.recency.dropped"] == 1

    async def test_paper_at_exact_cutoff_kept(self) -> None:
        # ``max_days=7`` means papers from the past 7 days are kept,
        # including those exactly 7 days old to the second.
        ctx = _make_ctx()
        edge = _make_paper("arxiv:edge", ctx.target_date - timedelta(days=7))

        flt = RecencyFilter(max_days=7)
        kept = [p async for p in flt.apply(_stream([edge]), ctx)]

        assert len(kept) == 1

    async def test_future_papers_kept_by_default(self) -> None:
        # arXiv occasionally lists papers with published_at slightly in the
        # future of the target date (timezone drift). Keep them — the user
        # didn't ask to drop the future.
        ctx = _make_ctx()
        future = _make_paper("arxiv:future", ctx.target_date + timedelta(days=1))

        flt = RecencyFilter(max_days=7)
        kept = [p async for p in flt.apply(_stream([future]), ctx)]

        assert len(kept) == 1

    async def test_mixed_stream_drops_only_old(self) -> None:
        ctx = _make_ctx()
        new1 = _make_paper("arxiv:1", ctx.target_date - timedelta(days=1))
        old1 = _make_paper("arxiv:2", ctx.target_date - timedelta(days=400))
        new2 = _make_paper("arxiv:3", ctx.target_date - timedelta(days=3))
        old2 = _make_paper("arxiv:4", ctx.target_date - timedelta(days=20))

        flt = RecencyFilter(max_days=10)
        kept = [p async for p in flt.apply(_stream([new1, old1, new2, old2]), ctx)]

        assert {p.canonical_id for p in kept} == {"arxiv:1", "arxiv:3"}
        assert ctx.counters["filter.recency.dropped"] == 2

    async def test_filter_satisfies_protocol(self) -> None:
        from paperwiki.core.protocols import Filter

        assert isinstance(RecencyFilter(max_days=7), Filter)
