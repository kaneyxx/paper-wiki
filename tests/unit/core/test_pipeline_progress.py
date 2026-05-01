"""Pipeline progress reporting (task 9.166).

The digest pipeline emits one ``loguru`` line per stage transition so
runners and SKILLs can show real-time progress. Stage names are stable
because 9.167 (run-status ledger) keys off them.

Stage contract (from `tasks/todo.md`):

* ``source.fetch.start`` / ``source.fetch.complete`` — wraps the entire
  source fan-in (one start/complete pair per pipeline run, NOT per
  source). Per-source stats live on the complete record under
  ``per_source``.
* ``filter.<name>.start`` / ``filter.<name>.complete`` — one pair per
  filter in declaration order. ``papers_in`` and ``papers_out`` track
  drops.
* ``scorer.start`` / ``scorer.complete`` — wraps scoring. Records
  ``papers_scored``.
* ``report.write.start`` / ``report.write.complete`` — wraps the
  reporter fan-out (parallel via ``asyncio.gather``). Records
  ``reporters`` count.

Each ``*.complete`` line carries ``elapsed_ms: int`` (rounded to ms)
plus stage-specific counts. ``*.start`` lines establish the stage name
in the log so consumers can correlate.

Verification: tests capture loguru via a custom sink and assert log
record presence + ordering + structure.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from loguru import logger

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.core.pipeline import Pipeline


def _make_paper(canonical_id: str) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title="Stub",
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


class DropAllFilter:
    name = "drop-all"

    async def apply(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Paper]:
        async for _paper in papers:
            ctx.increment(f"filter.{self.name}.dropped")
            # drop everything
        return
        yield  # pragma: no cover - unreachable, here for typing


class ConstantScorer:
    name = "constant"

    async def score(
        self, papers: AsyncIterator[Paper], ctx: RunContext
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            yield Recommendation(paper=paper, score=ScoreBreakdown())


class NoopReporter:
    def __init__(self, name: str = "noop") -> None:
        self.name = name

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        return None


@pytest.fixture
def captured_records() -> list[dict[str, Any]]:
    """Capture loguru records emitted by the pipeline as structured dicts."""
    records: list[dict[str, Any]] = []

    def _sink(message: Any) -> None:
        rec = message.record
        records.append(
            {
                "level": rec["level"].name,
                "message": rec["message"],
                "extra": dict(rec["extra"]),
            }
        )

    handler_id = logger.add(_sink, level="DEBUG", format="{message}")
    try:
        yield records
    finally:
        logger.remove(handler_id)


def _events(records: list[dict[str, Any]]) -> list[str]:
    return [r["message"] for r in records]


def _by_event(records: list[dict[str, Any]], event: str) -> dict[str, Any]:
    """Return the extras dict for the *first* record whose message matches event."""
    for r in records:
        if r["message"] == event:
            return r["extra"]
    pytest.fail(f"event {event!r} not found in records: {_events(records)}")


# ---------------------------------------------------------------------------
# Stage start / complete contract
# ---------------------------------------------------------------------------


class TestPipelineProgressLogging:
    async def test_logs_source_fetch_start_and_complete(
        self, captured_records: list[dict[str, Any]]
    ) -> None:
        papers = [_make_paper("arxiv:0001.0001"), _make_paper("arxiv:0002.0002")]
        pipeline = Pipeline(
            sources=[StaticSource("arxiv", papers)],
            filters=[],
            scorer=ConstantScorer(),
            reporters=[NoopReporter()],
        )
        await pipeline.run(_make_ctx())

        events = _events(captured_records)
        assert "source.fetch.start" in events
        assert "source.fetch.complete" in events

        complete = _by_event(captured_records, "source.fetch.complete")
        assert complete.get("papers_out") == 2
        assert "elapsed_ms" in complete
        assert isinstance(complete["elapsed_ms"], int)
        assert complete["elapsed_ms"] >= 0
        # per_source breakdown
        assert complete.get("per_source") == {"arxiv": 2}

    async def test_logs_each_filter_start_and_complete(
        self, captured_records: list[dict[str, Any]]
    ) -> None:
        papers = [
            _make_paper("arxiv:0001.0001"),
            _make_paper("arxiv:0002.0002"),
            _make_paper("arxiv:0003.0003"),
        ]
        pipeline = Pipeline(
            sources=[StaticSource("arxiv", papers)],
            filters=[IdentityFilter(), DropAllFilter()],
            scorer=ConstantScorer(),
            reporters=[NoopReporter()],
        )
        await pipeline.run(_make_ctx())

        events = _events(captured_records)
        # Filters log under their own name.
        assert "filter.identity.start" in events
        assert "filter.identity.complete" in events
        assert "filter.drop-all.start" in events
        assert "filter.drop-all.complete" in events

        identity_done = _by_event(captured_records, "filter.identity.complete")
        assert identity_done["papers_in"] == 3
        assert identity_done["papers_out"] == 3
        assert "elapsed_ms" in identity_done

        drop_done = _by_event(captured_records, "filter.drop-all.complete")
        assert drop_done["papers_in"] == 3
        assert drop_done["papers_out"] == 0

    async def test_logs_scorer_start_and_complete(
        self, captured_records: list[dict[str, Any]]
    ) -> None:
        papers = [_make_paper("arxiv:0001.0001")]
        pipeline = Pipeline(
            sources=[StaticSource("arxiv", papers)],
            filters=[],
            scorer=ConstantScorer(),
            reporters=[NoopReporter()],
        )
        await pipeline.run(_make_ctx())

        events = _events(captured_records)
        assert "scorer.start" in events
        assert "scorer.complete" in events

        complete = _by_event(captured_records, "scorer.complete")
        assert complete.get("papers_scored") == 1
        assert "elapsed_ms" in complete

    async def test_logs_report_write_start_and_complete(
        self, captured_records: list[dict[str, Any]]
    ) -> None:
        papers = [_make_paper("arxiv:0001.0001")]
        pipeline = Pipeline(
            sources=[StaticSource("arxiv", papers)],
            filters=[],
            scorer=ConstantScorer(),
            reporters=[NoopReporter("md"), NoopReporter("obsidian")],
        )
        await pipeline.run(_make_ctx())

        events = _events(captured_records)
        assert "report.write.start" in events
        assert "report.write.complete" in events

        complete = _by_event(captured_records, "report.write.complete")
        assert complete.get("reporters") == 2
        assert complete.get("recommendations") == 1
        assert "elapsed_ms" in complete

    async def test_stage_order_is_source_filter_scorer_report(
        self, captured_records: list[dict[str, Any]]
    ) -> None:
        papers = [_make_paper("arxiv:0001.0001")]
        pipeline = Pipeline(
            sources=[StaticSource("arxiv", papers)],
            filters=[IdentityFilter()],
            scorer=ConstantScorer(),
            reporters=[NoopReporter()],
        )
        await pipeline.run(_make_ctx())

        events = _events(captured_records)
        # Distill to just the stage-marker events for ordering check.
        markers = [
            e
            for e in events
            if e
            in {
                "source.fetch.start",
                "source.fetch.complete",
                "filter.identity.start",
                "filter.identity.complete",
                "scorer.start",
                "scorer.complete",
                "report.write.start",
                "report.write.complete",
            }
        ]
        assert markers == [
            "source.fetch.start",
            "source.fetch.complete",
            "filter.identity.start",
            "filter.identity.complete",
            "scorer.start",
            "scorer.complete",
            "report.write.start",
            "report.write.complete",
        ]
