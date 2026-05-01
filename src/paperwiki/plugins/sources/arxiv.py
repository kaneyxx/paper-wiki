"""arXiv source plugin.

Fetches recently submitted papers from the arXiv Atom-feed API and
yields them as canonical :class:`~paperwiki.core.models.Paper` objects.

Why this design:

* The arXiv API speaks Atom, so we use stdlib :mod:`xml.etree.ElementTree`
  to parse — no extra dependency.
* The fetch pulls a single batch of up to ``max_results`` items sorted
  by submission date desc; pagination is deferred to the dedup-aware
  topup logic in Phase 3.
* Broken entries (missing required fields, unparseable ids) are
  skipped silently rather than failing the whole feed; one bad row
  should not lose the rest of a digest.

The class is async-iterator-friendly per
:class:`paperwiki.core.protocols.Source`. Tests inject a custom
``httpx.AsyncClient`` to bypass the network entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

from loguru import logger

from paperwiki._internal.http import build_client, fetch_with_retry
from paperwiki._internal.normalize import normalize_arxiv_id
from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import Author, Paper

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import httpx

    from paperwiki.core.models import RunContext

# Atom + arxiv namespaces used in the feed.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_DEFAULT_BASE_URL = "https://export.arxiv.org/api/query"


class ArxivSource:
    """Fetch recent papers from the arXiv Atom API.

    Parameters
    ----------
    categories:
        Non-empty list of arXiv category codes (``"cs.AI"``, ``"cs.LG"``, …).
    lookback_days:
        How far back from ``ctx.target_date`` to search.
    max_results:
        Upper bound on entries returned in a single request.
    base_url:
        Override for tests or alternative arXiv mirrors.
    client:
        Optional pre-built ``httpx.AsyncClient``. The source does not
        own the lifecycle when one is injected; test code must close it.
    """

    name = "arxiv"

    def __init__(
        self,
        categories: list[str],
        *,
        lookback_days: int = 30,
        max_results: int = 100,
        base_url: str = _DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not categories:
            msg = "ArxivSource requires at least one category"
            raise ValueError(msg)
        self.categories = list(categories)
        self.lookback_days = lookback_days
        self.max_results = max_results
        self.base_url = base_url
        self._injected_client = client

    async def fetch(
        self,
        ctx: RunContext,
        *,
        _retry_kwargs: dict[str, Any] | None = None,
    ) -> AsyncIterator[Paper]:
        """Yield papers matching the configured categories and lookback window.

        ``_retry_kwargs`` is a private hook used by tests to disable
        backoff sleeps; production callers should not set it.
        """
        params = self._build_query_params(target_date=ctx.target_date)
        retry_kwargs = _retry_kwargs or {}

        client = self._injected_client or build_client()
        owns_client = self._injected_client is None
        try:
            ctx.increment("source.arxiv.requests")
            response = await fetch_with_retry(
                client,
                "GET",
                self.base_url,
                params=params,
                **retry_kwargs,
            )
            # arXiv returns 200 even for empty results; non-2xx that
            # survived retry is an IntegrationError.
            if response.status_code >= 400:
                ctx.increment("source.arxiv.http_errors")
                msg = f"arxiv returned HTTP {response.status_code}"
                raise IntegrationError(msg)

            body = response.text
        finally:
            if owns_client:
                await client.aclose()

        # Task 9.169: source-level dedup. arXiv sometimes returns the
        # same paper twice in a single response (cross-listed papers,
        # pagination boundary races). Collapsing here keeps downstream
        # filters from having to re-implement the same logic. Counter
        # surfaces the collapse for observability.
        seen_ids: set[str] = set()
        for paper in self._parse_atom_feed(body):
            if paper.canonical_id in seen_ids:
                ctx.increment("source.arxiv.duplicates")
                continue
            seen_ids.add(paper.canonical_id)
            yield paper

    def _build_query_params(self, *, target_date: datetime) -> dict[str, Any]:
        """Assemble the GET query string parameters.

        Returns a dict suitable for ``httpx.AsyncClient.request(params=...)``.
        """
        # Build "cat:cs.AI OR cat:cs.LG" expression.
        category_query = " OR ".join(f"cat:{c}" for c in self.categories)

        # Build submittedDate window. arXiv expects YYYYMMDDHHMM-HHMM form
        # joined with " TO " inside square brackets.
        end = target_date
        start = end - timedelta(days=self.lookback_days)
        date_query = (
            f"submittedDate:[{start.strftime('%Y%m%d')}0000 TO {end.strftime('%Y%m%d')}2359]"
        )

        return {
            "search_query": f"({category_query}) AND {date_query}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": self.max_results,
        }

    @staticmethod
    def _parse_atom_feed(xml_text: str) -> list[Paper]:
        """Parse an arXiv Atom feed into a list of :class:`Paper`.

        Returns an empty list for a feed with no entries. Unparseable
        feeds raise :class:`IntegrationError`. Individual entries that
        fail validation are skipped with a warning.
        """
        try:
            root = ET.fromstring(xml_text)  # noqa: S314 — input is trusted server response
        except ET.ParseError as exc:
            msg = f"failed to parse arxiv Atom feed: {exc}"
            raise IntegrationError(msg) from exc

        papers: list[Paper] = []
        for entry in root.findall("atom:entry", _NS):
            paper = _parse_entry(entry)
            if paper is not None:
                papers.append(paper)
        return papers


def _parse_entry(entry: ET.Element) -> Paper | None:
    """Convert an Atom ``<entry>`` element into a :class:`Paper`.

    Returns ``None`` (and logs a warning) if any required field is
    missing or invalid; the caller skips those entries.
    """
    raw_id = _text(entry.find("atom:id", _NS))
    if not raw_id:
        logger.warning("arxiv.parse.skip", reason="missing id")
        return None

    arxiv_id_part = raw_id.rsplit("/", 1)[-1]
    normalized_id = normalize_arxiv_id(arxiv_id_part)
    if normalized_id is None:
        logger.warning("arxiv.parse.skip", reason="invalid id", raw=raw_id)
        return None
    canonical_id = f"arxiv:{normalized_id}"

    title = _text(entry.find("atom:title", _NS))
    abstract = _text(entry.find("atom:summary", _NS))
    if not title or not abstract:
        logger.warning("arxiv.parse.skip", reason="missing title/abstract", id=raw_id)
        return None

    published_raw = _text(entry.find("atom:published", _NS))
    if not published_raw:
        logger.warning("arxiv.parse.skip", reason="missing published", id=raw_id)
        return None
    try:
        published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("arxiv.parse.skip", reason="bad published", id=raw_id)
        return None

    authors: list[Author] = []
    for author_el in entry.findall("atom:author", _NS):
        name = _text(author_el.find("atom:name", _NS))
        if not name:
            continue
        affiliation = _text(author_el.find("arxiv:affiliation", _NS))
        authors.append(Author(name=name, affiliation=affiliation))

    if not authors:
        logger.warning("arxiv.parse.skip", reason="no authors", id=raw_id)
        return None

    categories = [c.attrib.get("term", "") for c in entry.findall("atom:category", _NS)]
    categories = [c for c in categories if c]

    pdf_url: str | None = None
    landing_url: str | None = None
    for link in entry.findall("atom:link", _NS):
        rel = link.attrib.get("rel")
        title_attr = link.attrib.get("title")
        href = link.attrib.get("href")
        if not href:
            continue
        if title_attr == "pdf":
            pdf_url = href
        elif rel == "alternate":
            landing_url = href

    try:
        return Paper(
            canonical_id=canonical_id,
            title=title.strip(),
            authors=authors,
            abstract=abstract.strip(),
            published_at=published_at,
            categories=categories,
            pdf_url=pdf_url,
            landing_url=landing_url,
        )
    except ValueError as exc:
        logger.warning("arxiv.parse.skip", reason="model validation", id=raw_id, error=str(exc))
        return None


def _text(element: ET.Element | None) -> str | None:
    """Return ``element.text`` or ``None`` when the element is missing."""
    if element is None:
        return None
    return element.text


__all__ = ["ArxivSource"]
