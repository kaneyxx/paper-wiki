"""Unit tests for paperwiki.core.protocols.

Verifies that the runtime-checkable Protocols recognize a properly-shaped
plugin via :func:`isinstance` and reject ones missing required attributes.

Note: ``runtime_checkable`` only checks attribute presence, not signatures
or types. That is a Python limitation; signature/type compliance is
checked statically by mypy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.core.protocols import (
    Filter,
    Reporter,
    Scorer,
    Source,
    WikiBackend,
)


def _make_paper() -> Paper:
    return Paper(
        canonical_id="arxiv:0001.0001",
        title="A Test Paper",
        authors=[Author(name="Test Author")],
        abstract="Stub abstract.",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 1, 1, tzinfo=UTC), config_snapshot={})


# ---------------------------------------------------------------------------
# Conforming and non-conforming stubs
# ---------------------------------------------------------------------------


class StubSource:
    name = "stub-source"

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        yield _make_paper()


class StubFilter:
    name = "stub-filter"

    async def apply(self, papers: AsyncIterator[Paper], ctx: RunContext) -> AsyncIterator[Paper]:
        async for paper in papers:
            yield paper


class StubScorer:
    name = "stub-scorer"

    async def score(
        self, papers: AsyncIterator[Paper], ctx: RunContext
    ) -> AsyncIterator[Recommendation]:
        async for paper in papers:
            yield Recommendation(paper=paper, score=ScoreBreakdown())


class StubReporter:
    name = "stub-reporter"
    received: list[Recommendation]

    def __init__(self) -> None:
        self.received = []

    async def emit(self, recs: list[Recommendation], ctx: RunContext) -> None:
        self.received.extend(recs)


class StubWikiBackend:
    async def upsert_paper(self, rec: Recommendation) -> None:
        return None

    async def query(self, q: str) -> list[Recommendation]:
        return []


class MissingFetch:
    name = "broken"
    # No fetch method.


class MissingName:
    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        yield _make_paper()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSourceProtocol:
    def test_stub_source_satisfies_protocol(self) -> None:
        assert isinstance(StubSource(), Source)

    def test_class_missing_fetch_rejected(self) -> None:
        assert not isinstance(MissingFetch(), Source)

    def test_class_missing_name_rejected(self) -> None:
        assert not isinstance(MissingName(), Source)


class TestFilterProtocol:
    def test_stub_filter_satisfies_protocol(self) -> None:
        assert isinstance(StubFilter(), Filter)

    def test_unrelated_object_rejected(self) -> None:
        assert not isinstance(object(), Filter)


class TestScorerProtocol:
    def test_stub_scorer_satisfies_protocol(self) -> None:
        assert isinstance(StubScorer(), Scorer)


class TestReporterProtocol:
    def test_stub_reporter_satisfies_protocol(self) -> None:
        assert isinstance(StubReporter(), Reporter)


class TestWikiBackendProtocol:
    def test_stub_backend_satisfies_protocol(self) -> None:
        # WikiBackend is unique in that it has no `name` attribute — backends
        # are referenced by config, not by registry name.
        assert isinstance(StubWikiBackend(), WikiBackend)

    def test_partial_backend_rejected(self) -> None:
        class PartialBackend:
            async def upsert_paper(self, rec: Recommendation) -> None:
                return None

        assert not isinstance(PartialBackend(), WikiBackend)
