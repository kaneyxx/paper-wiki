"""arXiv source robustness (task 9.169).

Three new contract surfaces beyond the existing fetch_with_retry
behaviour:

1. **Source-level dedup.** When the arXiv Atom feed returns the same
   canonical id twice in a single response (this happens during
   pagination boundary races and when the same paper is cross-listed
   under multiple categories), the source collapses duplicates so
   downstream filters never see them. Counts collapse-events under
   ``source.arxiv.duplicates`` for observability.

2. **Structured ``RateLimitError``.** A 429 response that survives
   retries used to surface as a generic :class:`IntegrationError`;
   9.169 promotes it to a typed :class:`RateLimitError` (still an
   :class:`IntegrationError` subclass for backward-compat exit codes)
   so SKILLs and the run-status ledger can spot rate-limit-driven
   failures specifically.

3. **No regression on retry.** The existing exp-backoff retry on
   429/5xx still works — only the final-failure exception class
   changes for the 429 case.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from paperwiki._internal.http import build_client
from paperwiki.core.errors import IntegrationError, RateLimitError
from paperwiki.core.models import RunContext
from paperwiki.plugins.sources.arxiv import ArxivSource

_DUPLICATE_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2506.13063v1</id>
    <updated>2026-04-20T17:00:00Z</updated>
    <published>2026-04-20T16:30:00Z</published>
    <title>Same Paper</title>
    <summary>First listing.</summary>
    <author><name>A</name></author>
    <category term="cs.CV"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2506.13063v1</id>
    <updated>2026-04-20T17:00:00Z</updated>
    <published>2026-04-20T16:30:00Z</published>
    <title>Same Paper</title>
    <summary>Second listing — cross-listed under another category.</summary>
    <author><name>A</name></author>
    <category term="cs.LG"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2506.99999v1</id>
    <updated>2026-04-20T17:00:00Z</updated>
    <published>2026-04-20T16:30:00Z</published>
    <title>Different Paper</title>
    <summary>Distinct.</summary>
    <author><name>B</name></author>
    <category term="cs.CV"/>
  </entry>
</feed>
"""


def _ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


def _mock_transport(handler):  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Source-level dedup
# ---------------------------------------------------------------------------


async def test_collapses_duplicate_canonical_ids_in_one_fetch() -> None:
    """A paper appearing twice in the feed yields exactly once."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_DUPLICATE_FEED)

    client = build_client(transport=_mock_transport(_handler))
    source = ArxivSource(categories=["cs.CV"], client=client)
    ctx = _ctx()
    try:
        papers = [p async for p in source.fetch(ctx)]
    finally:
        await client.aclose()

    ids = [p.canonical_id for p in papers]
    assert ids.count("arxiv:2506.13063") == 1, f"duplicate canonical id should collapse, got {ids}"
    assert "arxiv:2506.99999" in ids
    # Counter records the collapse for observability.
    assert ctx.counters.get("source.arxiv.duplicates", 0) == 1


# ---------------------------------------------------------------------------
# Structured RateLimitError
# ---------------------------------------------------------------------------


async def test_persistent_429_raises_rate_limit_error() -> None:
    """Three 429s in a row should raise the typed RateLimitError."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = build_client(transport=_mock_transport(_handler))
    source = ArxivSource(categories=["cs.CV"], client=client)
    ctx = _ctx()
    try:
        with pytest.raises(RateLimitError):
            async for _paper in source.fetch(
                ctx,
                _retry_kwargs={"initial_backoff": 0, "backoff_factor": 1},
            ):
                pass
    finally:
        await client.aclose()


async def test_rate_limit_error_is_subclass_of_integration_error() -> None:
    """Backward-compat: existing IntegrationError handlers must still catch."""
    assert issubclass(RateLimitError, IntegrationError)


async def test_persistent_503_still_raises_generic_integration_error() -> None:
    """Non-429 5xx exhaustion is NOT a rate limit — keeps the generic class."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = build_client(transport=_mock_transport(_handler))
    source = ArxivSource(categories=["cs.CV"], client=client)
    ctx = _ctx()
    try:
        with pytest.raises(IntegrationError) as exc_info:
            async for _paper in source.fetch(
                ctx,
                _retry_kwargs={"initial_backoff": 0, "backoff_factor": 1},
            ):
                pass
        assert not isinstance(exc_info.value, RateLimitError), (
            "503 should not be misclassified as rate-limit"
        )
    finally:
        await client.aclose()
