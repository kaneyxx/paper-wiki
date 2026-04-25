"""Unit tests for paperwiki.plugins.sources.arxiv.ArxivSource.

Tests are split into:

* parser tests with literal Atom XML fixtures (no I/O)
* fetch tests using ``httpx.MockTransport`` (no network)
* query-construction tests
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from paperwiki._internal.http import build_client
from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import Paper, RunContext
from paperwiki.plugins.sources.arxiv import ArxivSource

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2506.13063v1</id>
    <updated>2026-04-20T17:00:00Z</updated>
    <published>2026-04-20T16:30:00Z</published>
    <title>PRISM2: Unlocking Multi-Modal General Pathology AI with Clinical Dialogue</title>
    <summary>We present PRISM2, a vision-language foundation model for pathology.</summary>
    <author>
      <name>George Shaikovski</name>
      <arxiv:affiliation>Paige AI</arxiv:affiliation>
    </author>
    <author>
      <name>Eugene Vorontsov</name>
    </author>
    <link href="http://arxiv.org/abs/2506.13063v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2506.13063v1" rel="related" title="pdf"/>
    <category term="cs.CV" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2603.26653v1</id>
    <updated>2026-03-30T12:00:00Z</updated>
    <published>2026-03-30T12:00:00Z</published>
    <title>PerceptionComp: A Video Benchmark</title>
    <summary>A benchmark for video reasoning.</summary>
    <author><name>Shaoxuan Li</name></author>
    <link href="http://arxiv.org/abs/2603.26653v1" rel="alternate"/>
    <link href="http://arxiv.org/pdf/2603.26653v1" rel="related" title="pdf"/>
    <category term="cs.CV" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

_EMPTY_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""

_FEED_WITH_BROKEN_ENTRY = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>not-a-valid-arxiv-url</id>
    <title>Broken Entry</title>
    <summary>No published date.</summary>
    <author><name>Anon</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2506.13063v1</id>
    <updated>2026-04-20T17:00:00Z</updated>
    <published>2026-04-20T16:30:00Z</published>
    <title>Good Entry</title>
    <summary>This one parses cleanly.</summary>
    <author><name>Author A</name></author>
    <category term="cs.AI"/>
  </entry>
</feed>
"""


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParseAtomFeed:
    def test_parses_two_entries(self) -> None:
        papers = ArxivSource._parse_atom_feed(_VALID_FEED)
        assert len(papers) == 2

    def test_first_paper_fields(self) -> None:
        papers = ArxivSource._parse_atom_feed(_VALID_FEED)
        p = papers[0]
        assert isinstance(p, Paper)
        assert p.canonical_id == "arxiv:2506.13063"
        assert p.title.startswith("PRISM2")
        assert len(p.authors) == 2
        assert p.authors[0].name == "George Shaikovski"
        assert p.authors[0].affiliation == "Paige AI"
        assert p.authors[1].name == "Eugene Vorontsov"
        assert p.authors[1].affiliation is None
        assert p.abstract.startswith("We present")
        assert p.published_at == datetime(2026, 4, 20, 16, 30, tzinfo=UTC)
        assert p.categories == ["cs.CV", "cs.LG"]
        assert p.pdf_url == "http://arxiv.org/pdf/2506.13063v1"
        assert p.landing_url == "http://arxiv.org/abs/2506.13063v1"

    def test_canonical_id_strips_version(self) -> None:
        # Source id is "...v1"; we want "arxiv:2506.13063" without the version.
        papers = ArxivSource._parse_atom_feed(_VALID_FEED)
        for p in papers:
            assert "v" not in p.canonical_id.split(":")[1]

    def test_empty_feed_yields_no_papers(self) -> None:
        assert ArxivSource._parse_atom_feed(_EMPTY_FEED) == []

    def test_broken_entry_is_skipped(self) -> None:
        # First entry has no valid arxiv id and no published date — skip it.
        # Second entry is valid — keep it.
        papers = ArxivSource._parse_atom_feed(_FEED_WITH_BROKEN_ENTRY)
        assert len(papers) == 1
        assert papers[0].title == "Good Entry"

    def test_malformed_xml_raises_integration_error(self) -> None:
        with pytest.raises(IntegrationError, match="parse"):
            ArxivSource._parse_atom_feed("<not valid xml")


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


class TestBuildQuery:
    def test_includes_category_filter(self) -> None:
        src = ArxivSource(categories=["cs.AI", "cs.LG"], lookback_days=7, max_results=50)
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        assert "cat:cs.AI" in params["search_query"]
        assert "cat:cs.LG" in params["search_query"]

    def test_includes_date_window(self) -> None:
        src = ArxivSource(categories=["cs.AI"], lookback_days=7)
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        # 2026-04-25 minus 7 days = 2026-04-18.
        assert "20260418" in params["search_query"]
        assert "20260425" in params["search_query"]

    def test_sorts_by_submitted_date_descending(self) -> None:
        src = ArxivSource(categories=["cs.AI"])
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        assert params["sortBy"] == "submittedDate"
        assert params["sortOrder"] == "descending"

    def test_max_results_is_passed_through(self) -> None:
        src = ArxivSource(categories=["cs.AI"], max_results=42)
        params = src._build_query_params(target_date=datetime(2026, 4, 25, tzinfo=UTC))
        assert params["max_results"] == 42

    def test_empty_categories_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one category"):
            ArxivSource(categories=[])


# ---------------------------------------------------------------------------
# fetch (HTTP)
# ---------------------------------------------------------------------------


class TestFetch:
    async def test_fetch_yields_papers_from_response(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, text=_VALID_FEED)

        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = ArxivSource(categories=["cs.AI", "cs.LG"], client=client)
            papers = [p async for p in src.fetch(_make_ctx())]

        assert len(papers) == 2
        assert papers[0].canonical_id == "arxiv:2506.13063"
        assert "search_query=" in str(captured["url"])

    async def test_fetch_increments_counter(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_VALID_FEED)

        ctx = _make_ctx()
        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = ArxivSource(categories=["cs.AI"], client=client)
            _ = [p async for p in src.fetch(ctx)]

        # Counter naming convention: source.<name>.fetched (set by Pipeline,
        # not by source). The source instead reports HTTP-level counters.
        assert ctx.counters.get("source.arxiv.requests") == 1

    async def test_fetch_propagates_integration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = build_client(transport=httpx.MockTransport(handler))
        async with client:
            src = ArxivSource(categories=["cs.AI"], client=client)
            with pytest.raises(IntegrationError):
                _ = [p async for p in src.fetch(_make_ctx(), _retry_kwargs={"initial_backoff": 0})]

    async def test_source_satisfies_protocol(self) -> None:
        from paperwiki.core.protocols import Source

        src = ArxivSource(categories=["cs.AI"])
        assert isinstance(src, Source)
