"""Unit tests for paperwiki.plugins.sources.semantic_scholar.SemanticScholarSource.

Tests are split into:

* parser tests with literal JSON fixtures (no I/O)
* fetch tests using ``httpx.MockTransport`` (no network)
* query-construction tests
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from paperwiki._internal.http import build_client
from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import Paper, RunContext
from paperwiki.plugins.sources.semantic_scholar import SemanticScholarSource

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_VALID_RESPONSE = {
    "total": 2,
    "offset": 0,
    "data": [
        {
            "paperId": "abc123",
            "title": "Foundation Models in Pathology",
            "abstract": "We present a foundation model for pathology.",
            "publicationDate": "2026-04-20",
            "citationCount": 42,
            "externalIds": {"ArXiv": "2506.13063", "DOI": "10.1234/example"},
            "authors": [
                {
                    "name": "Jane Doe",
                    "affiliations": [{"name": "MIT"}],
                },
                {
                    "name": "John Roe",
                    "affiliations": [],
                },
            ],
        },
        {
            "paperId": "def456",
            "title": "S2-Only Paper Without Arxiv",
            "abstract": "Some abstract text.",
            "publicationDate": "2026-02-15",
            "citationCount": 5,
            "externalIds": {"DOI": "10.9999/another"},
            "authors": [{"name": "Alice"}],
        },
    ],
}

_RESPONSE_WITH_BROKEN_ENTRY = {
    "total": 2,
    "data": [
        {
            "paperId": "broken",
            # Missing title.
            "abstract": "...",
            "publicationDate": "2026-01-01",
            "authors": [{"name": "Anon"}],
        },
        {
            "paperId": "good",
            "title": "Valid Entry",
            "abstract": "Valid abstract",
            "publicationDate": "2026-03-01",
            "authors": [{"name": "Author"}],
            "externalIds": {},
        },
    ],
}


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_parses_two_papers(self) -> None:
        papers = SemanticScholarSource._parse_response(_VALID_RESPONSE)
        assert len(papers) == 2

    def test_arxiv_external_id_normalizes_to_arxiv_namespace(self) -> None:
        papers = SemanticScholarSource._parse_response(_VALID_RESPONSE)
        assert papers[0].canonical_id == "arxiv:2506.13063"

    def test_paper_without_arxiv_id_uses_s2_namespace(self) -> None:
        papers = SemanticScholarSource._parse_response(_VALID_RESPONSE)
        assert papers[1].canonical_id == "s2:def456"

    def test_paper_fields(self) -> None:
        papers = SemanticScholarSource._parse_response(_VALID_RESPONSE)
        p = papers[0]
        assert isinstance(p, Paper)
        assert p.title == "Foundation Models in Pathology"
        assert len(p.authors) == 2
        assert p.authors[0].name == "Jane Doe"
        assert p.authors[0].affiliation == "MIT"
        assert p.authors[1].affiliation is None
        assert p.citation_count == 42
        assert p.published_at == datetime(2026, 4, 20, tzinfo=UTC)
        # raw should keep the externalIds for downstream plugins.
        assert p.raw.get("externalIds", {}).get("DOI") == "10.1234/example"

    def test_empty_data_yields_no_papers(self) -> None:
        assert SemanticScholarSource._parse_response({"data": []}) == []
        assert SemanticScholarSource._parse_response({}) == []

    def test_broken_entry_skipped(self) -> None:
        papers = SemanticScholarSource._parse_response(_RESPONSE_WITH_BROKEN_ENTRY)
        assert len(papers) == 1
        assert papers[0].title == "Valid Entry"
        assert papers[0].canonical_id == "s2:good"

    def test_partial_publication_date_year_only(self) -> None:
        # S2 sometimes returns publicationDate as "YYYY" or "YYYY-MM".
        # We treat those as January 1st / day 1 of the month at UTC.
        partial_year = {
            "data": [
                {
                    "paperId": "y1",
                    "title": "Year-only",
                    "abstract": "abc",
                    "publicationDate": "2025",
                    "authors": [{"name": "A"}],
                }
            ]
        }
        papers = SemanticScholarSource._parse_response(partial_year)
        assert len(papers) == 1
        assert papers[0].published_at == datetime(2025, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


class TestBuildQuery:
    def test_query_includes_keyword(self) -> None:
        src = SemanticScholarSource(query="foundation model pathology", lookback_days=30)
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        assert params["query"] == "foundation model pathology"

    def test_query_includes_publication_date_window(self) -> None:
        src = SemanticScholarSource(query="x", lookback_days=30)
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        # Window is [target - 30 days, target]
        assert params["publicationDateOrYear"] == "2026-03-26:2026-04-25"

    def test_query_includes_fields(self) -> None:
        src = SemanticScholarSource(query="x")
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        for required in ("title", "abstract", "authors", "publicationDate", "externalIds"):
            assert required in params["fields"]

    def test_query_explicitly_requests_author_names(self) -> None:
        """S2 returns ``authors`` with only ``authorId + affiliations`` unless
        ``authors.name`` is named explicitly in the ``fields`` param. Without
        the name, our parser drops every paper as "no authors".
        """
        src = SemanticScholarSource(query="x")
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        assert "authors.name" in params["fields"]

    def test_limit_is_passed_through(self) -> None:
        src = SemanticScholarSource(query="x", limit=33)
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        assert params["limit"] == 33

    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty query"):
            SemanticScholarSource(query="   ")

    def test_limit_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="limit must be"):
            SemanticScholarSource(query="x", limit=0)


# ---------------------------------------------------------------------------
# fetch (HTTP)
# ---------------------------------------------------------------------------


class TestFetch:
    async def test_fetch_yields_papers_from_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_VALID_RESPONSE)

        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = SemanticScholarSource(query="foundation model", client=client)
            papers = [p async for p in src.fetch(_make_ctx())]

        assert len(papers) == 2

    async def test_fetch_includes_api_key_header_when_provided(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["key"] = request.headers.get("x-api-key", "")
            return httpx.Response(200, json={"data": []})

        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = SemanticScholarSource(query="x", api_key="secret-key", client=client)
            _ = [p async for p in src.fetch(_make_ctx())]

        assert captured["key"] == "secret-key"

    async def test_fetch_omits_api_key_header_when_absent(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["key"] = request.headers.get("x-api-key", "<absent>")
            return httpx.Response(200, json={"data": []})

        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = SemanticScholarSource(query="x", client=client)
            _ = [p async for p in src.fetch(_make_ctx())]

        assert captured["key"] == "<absent>"

    async def test_fetch_increments_counter(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        ctx = _make_ctx()
        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = SemanticScholarSource(query="x", client=client)
            _ = [p async for p in src.fetch(ctx)]

        assert ctx.counters.get("source.semantic_scholar.requests") == 1

    async def test_fetch_propagates_integration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = SemanticScholarSource(query="x", client=client)
            with pytest.raises(IntegrationError):
                _ = [p async for p in src.fetch(_make_ctx(), _retry_kwargs={"initial_backoff": 0})]

    async def test_malformed_json_raises_integration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = SemanticScholarSource(query="x", client=client)
            with pytest.raises(IntegrationError, match="parse"):
                _ = [p async for p in src.fetch(_make_ctx())]

    async def test_source_satisfies_protocol(self) -> None:
        from paperwiki.core.protocols import Source

        src = SemanticScholarSource(query="x")
        assert isinstance(src, Source)

    async def test_round_trip_fixture_is_real_json(self) -> None:
        # Sanity: the fixture is JSON-serializable so MockTransport's
        # json= parameter does not raise.
        json.dumps(_VALID_RESPONSE)


# ---------------------------------------------------------------------------
# Task 9.19 — s2.parse.skip log level
# ---------------------------------------------------------------------------


class TestSkipLogLevel:
    def test_semantic_scholar_skip_branches_log_at_debug_level(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AC-9.19.4: sparse-record skip branches emit DEBUG, not WARNING."""
        from paperwiki._internal.logging import configure_runner_logging

        configure_runner_logging(verbose=True)

        sparse_responses = [
            # missing title/abstract
            {"data": [{"paperId": "x1", "title": "", "abstract": ""}]},
            # bad publication date
            {
                "data": [
                    {
                        "paperId": "x2",
                        "title": "T",
                        "abstract": "A",
                        "publicationDate": "not-a-date",
                        "authors": [{"name": "A"}],
                    }
                ]
            },
            # no authors
            {
                "data": [
                    {
                        "paperId": "x3",
                        "title": "T",
                        "abstract": "A",
                        "publicationDate": "2026-01-01",
                        "authors": [],
                    }
                ]
            },
            # no usable id (no externalIds, no paperId)
            {
                "data": [
                    {
                        "title": "T",
                        "abstract": "A",
                        "publicationDate": "2026-01-01",
                        "authors": [{"name": "A"}],
                    }
                ]
            },
        ]
        for payload in sparse_responses:
            SemanticScholarSource._parse_response(payload)

        captured = capsys.readouterr()
        # s2.parse.skip must appear in DEBUG output (verbose=True)
        assert "s2.parse.skip" in captured.err, "sparse-record skip must log s2.parse.skip"
        # Must NOT appear as WARNING-level — only DEBUG
        lines = captured.err.splitlines()
        warning_skip_lines = [ln for ln in lines if "s2.parse.skip" in ln and "WARNING" in ln]
        assert not warning_skip_lines, (
            "s2.parse.skip must NOT appear at WARNING level for sparse records; "
            f"found: {warning_skip_lines}"
        )

    def test_semantic_scholar_emits_skip_summary_at_info_level(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AC-9.19.5: summary line emitted once per fetch when at least one skip."""
        from paperwiki._internal.logging import configure_runner_logging

        configure_runner_logging(verbose=False)

        # Two broken entries + one good entry → skips counted
        mixed = {
            "data": [
                {"paperId": "bad1", "title": "", "abstract": ""},
                {
                    "paperId": "bad2",
                    "title": "T",
                    "abstract": "A",
                    "publicationDate": "2026-01-01",
                    "authors": [],
                },
                {
                    "paperId": "good",
                    "title": "Valid Entry",
                    "abstract": "Valid abstract",
                    "publicationDate": "2026-03-01",
                    "authors": [{"name": "Author"}],
                    "externalIds": {},
                },
            ]
        }
        papers = SemanticScholarSource._parse_response(mixed)
        captured = capsys.readouterr()

        # Exactly one good paper parsed
        assert len(papers) == 1
        # INFO summary line must appear
        assert "s2.parse.skipped_summary" in captured.err, (
            "must emit s2.parse.skipped_summary when at least one skip occurred"
        )

    def test_semantic_scholar_no_summary_when_all_parse_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AC-9.19.5 (inverse): no summary line when zero skips."""
        from paperwiki._internal.logging import configure_runner_logging

        configure_runner_logging(verbose=False)

        SemanticScholarSource._parse_response(_VALID_RESPONSE)
        captured = capsys.readouterr()
        assert "s2.parse.skipped_summary" not in captured.err, (
            "must NOT emit s2.parse.skipped_summary when all entries parse successfully"
        )
