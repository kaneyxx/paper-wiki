"""Semantic Scholar source plugin.

Fetches papers from the Semantic Scholar Graph API
(``/graph/v1/paper/search``) and yields canonical
:class:`~paperwiki.core.models.Paper` objects.

Why this design:

* The S2 API speaks JSON; no XML parsing is needed.
* The fetch issues a single search request bounded by a
  ``publicationDateOrYear`` window; pagination is deferred to Phase 3
  (dedup-aware topup).
* Papers with an ``externalIds.ArXiv`` value are namespaced
  ``arxiv:<id>`` so they collide with :class:`ArxivSource` results in
  the dedup filter. Papers without an arXiv id fall back to the
  ``s2:<paperId>`` namespace.
* An optional ``api_key`` is forwarded as ``x-api-key`` and considerably
  raises the rate limit. 429 responses still flow through
  :func:`fetch_with_retry` so they back off automatically.

The class is async-iterator-friendly per
:class:`paperwiki.core.protocols.Source`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger

from paperwiki._internal.http import build_client, fetch_with_retry
from paperwiki._internal.normalize import normalize_arxiv_id
from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import Author, Paper

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import httpx

    from paperwiki.core.models import RunContext


_DEFAULT_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
# NB: ``authors.name`` MUST be listed explicitly. Without it, S2 returns
# author objects shaped like ``{authorId, affiliations}`` with NO ``name``
# field, and our parser drops the entire paper as "no authors". Verified
# against the live API on 2026-04-25.
_FIELDS = (
    "title,abstract,"
    "authors,authors.name,authors.affiliations,"
    "publicationDate,citationCount,externalIds"
)
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m", "%Y")


class SemanticScholarSource:
    """Fetch papers from Semantic Scholar's keyword-search endpoint.

    Parameters
    ----------
    query:
        Non-empty keyword query (e.g. ``"foundation model pathology"``).
    lookback_days:
        Width of the publication-date window in days, ending at
        ``ctx.target_date``.
    limit:
        Maximum results per request (1-100 per S2 docs; we do not enforce
        the upper bound here).
    api_key:
        Optional Semantic Scholar API key sent as ``x-api-key``. Raises
        the rate limit substantially.
    base_url:
        Override for tests or alternative S2 hosts.
    client:
        Optional pre-built ``httpx.AsyncClient``; the source does not
        own the lifecycle when one is injected.
    """

    name = "semantic_scholar"

    def __init__(
        self,
        query: str,
        *,
        lookback_days: int = 90,
        limit: int = 50,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not query or not query.strip():
            msg = "SemanticScholarSource requires a non-empty query"
            raise ValueError(msg)
        if limit <= 0:
            msg = "limit must be positive"
            raise ValueError(msg)
        self.query = query.strip()
        self.lookback_days = lookback_days
        self.limit = limit
        self.api_key = api_key
        self.base_url = base_url
        self._injected_client = client

    async def fetch(
        self,
        ctx: RunContext,
        *,
        _retry_kwargs: dict[str, Any] | None = None,
    ) -> AsyncIterator[Paper]:
        """Yield papers matching the configured query and date window."""
        params = self._build_query_params(target_date=ctx.target_date)
        retry_kwargs = _retry_kwargs or {}
        headers: dict[str, str] = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        client = self._injected_client or build_client()
        owns_client = self._injected_client is None
        try:
            ctx.increment("source.semantic_scholar.requests")
            response = await fetch_with_retry(
                client,
                "GET",
                self.base_url,
                params=params,
                headers=headers,
                **retry_kwargs,
            )
            if response.status_code >= 400:
                ctx.increment("source.semantic_scholar.http_errors")
                msg = f"semantic_scholar returned HTTP {response.status_code}"
                raise IntegrationError(msg)
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                msg = "failed to parse semantic_scholar JSON response"
                raise IntegrationError(msg) from exc
        finally:
            if owns_client:
                await client.aclose()

        for paper in self._parse_response(data):
            yield paper

    def _build_query_params(self, *, target_date: datetime) -> dict[str, Any]:
        end = target_date
        start = end - timedelta(days=self.lookback_days)
        return {
            "query": self.query,
            "publicationDateOrYear": (f"{start.strftime('%Y-%m-%d')}:{end.strftime('%Y-%m-%d')}"),
            "limit": self.limit,
            "fields": _FIELDS,
        }

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> list[Paper]:
        """Convert a Semantic Scholar JSON payload into a list of :class:`Paper`."""
        entries = payload.get("data") or []
        papers: list[Paper] = []
        for entry in entries:
            paper = _parse_entry(entry)
            if paper is not None:
                papers.append(paper)
        return papers


def _parse_entry(entry: dict[str, Any]) -> Paper | None:
    """Map a single S2 paper dict into a :class:`Paper`, or ``None`` to skip."""
    title = (entry.get("title") or "").strip()
    abstract = (entry.get("abstract") or "").strip()
    if not title or not abstract:
        logger.warning("s2.parse.skip", reason="missing title/abstract")
        return None

    published_at = _parse_publication_date(entry.get("publicationDate"))
    if published_at is None:
        logger.warning("s2.parse.skip", reason="bad publication date", title=title)
        return None

    authors_raw = entry.get("authors") or []
    authors: list[Author] = []
    for author in authors_raw:
        name = (author.get("name") or "").strip() if isinstance(author, dict) else ""
        if not name:
            continue
        affiliations = author.get("affiliations") if isinstance(author, dict) else None
        affiliation = _first_affiliation(affiliations)
        authors.append(Author(name=name, affiliation=affiliation))
    if not authors:
        logger.warning("s2.parse.skip", reason="no authors", title=title)
        return None

    canonical_id = _canonical_id(entry)
    if canonical_id is None:
        logger.warning("s2.parse.skip", reason="no usable id", title=title)
        return None

    citation_count = entry.get("citationCount")
    if not isinstance(citation_count, int) or citation_count < 0:
        citation_count = None

    try:
        return Paper(
            canonical_id=canonical_id,
            title=title,
            authors=authors,
            abstract=abstract,
            published_at=published_at,
            citation_count=citation_count,
            raw={
                "externalIds": entry.get("externalIds") or {},
                "paperId": entry.get("paperId"),
            },
        )
    except ValueError as exc:
        logger.warning("s2.parse.skip", reason="model validation", error=str(exc), title=title)
        return None


def _canonical_id(entry: dict[str, Any]) -> str | None:
    """Pick a canonical id, preferring arXiv when available."""
    external = entry.get("externalIds") or {}
    arxiv_raw = external.get("ArXiv") if isinstance(external, dict) else None
    if isinstance(arxiv_raw, str):
        normalized = normalize_arxiv_id(arxiv_raw)
        if normalized is not None:
            return f"arxiv:{normalized}"
    paper_id = entry.get("paperId")
    if isinstance(paper_id, str) and paper_id.strip():
        return f"s2:{paper_id.strip()}"
    return None


def _parse_publication_date(value: Any) -> datetime | None:
    """Parse the various date formats S2 returns into a UTC datetime."""
    from datetime import UTC

    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _first_affiliation(value: Any) -> str | None:
    """Return the first non-empty affiliation name, or ``None``."""
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        elif isinstance(item, str) and item.strip():
            return item.strip()
    return None


__all__ = ["SemanticScholarSource"]
