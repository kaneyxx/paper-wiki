"""paperclip source plugin.

Wraps the third-party `paperclip <https://gxl.ai/blog/paperclip>`_ CLI
as a paper-wiki :class:`Source`. paperclip indexes 8M+ biomedical
papers across bioRxiv, medRxiv, and PubMed Central; this plugin lets a
recipe pull from that corpus alongside arXiv and Semantic Scholar.

Why subprocess and not direct HTTP:

* paperclip's CLI handles auth (``paperclip login``), token storage,
  and per-tier rate limiting. Re-implementing those would duplicate
  upstream surface area we don't own.
* The plugin stays hermetic in tests because we mock at the
  ``asyncio.create_subprocess_exec`` boundary; no network, no real
  binary needed in CI.

Identifier convention (per Phase 7 plan §7.2.2):

* If a hit exposes an arXiv id under ``external_ids.arxiv``, the
  canonical id is ``arxiv:<id>`` so dedup converges with
  :class:`ArxivSource`.
* Otherwise, bioRxiv/medRxiv hits become ``paperclip:bio_<id>`` and
  PMC hits become ``paperclip:pmc_<id>``. Other sources fall back to
  ``paperclip:<source>_<id>``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from paperwiki._internal.normalize import normalize_arxiv_id
from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import Author, Paper

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from paperwiki.core.models import RunContext


_DEFAULT_TIMEOUT_SECONDS = 60.0


class PaperclipSource:
    """Subprocess-backed source plugin for the paperclip biomedical search CLI.

    Parameters
    ----------
    query:
        Free-text search expression handed to ``paperclip search``.
    limit:
        Upper bound on results to return per fetch (default 20).
    sources:
        Optional list of upstream sources to restrict (e.g.,
        ``["biorxiv", "pmc"]``). ``None`` means all sources paperclip
        knows about.
    paperclip_bin:
        CLI binary name. Defaults to ``"paperclip"`` (resolved via PATH
        by ``asyncio.create_subprocess_exec``). Override for tests or
        non-standard installs.
    timeout_seconds:
        Hard timeout for the search call.
    """

    name = "paperclip"

    def __init__(
        self,
        query: str,
        *,
        limit: int = 20,
        sources: Sequence[str] | None = None,
        paperclip_bin: str = "paperclip",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not query or not query.strip():
            msg = "PaperclipSource requires a non-empty query"
            raise ValueError(msg)
        self.query = query.strip()
        self.limit = limit
        self.sources = list(sources) if sources else []
        self.paperclip_bin = paperclip_bin
        self.timeout_seconds = timeout_seconds

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        """Yield :class:`Paper` objects from one paperclip search call."""
        argv = [
            self.paperclip_bin,
            "search",
            self.query,
            "--limit",
            str(self.limit),
            "--json",
        ]
        for src in self.sources:
            argv.extend(["--source", src])

        ctx.increment("source.paperclip.requests")

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            ctx.increment("source.paperclip.errors")
            msg = (
                "paperclip not installed; see docs/paperclip-setup.md to "
                "install the CLI and register the MCP endpoint."
            )
            raise IntegrationError(msg) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError as exc:
            ctx.increment("source.paperclip.errors")
            proc.kill()
            await proc.wait()
            msg = f"paperclip search timed out after {self.timeout_seconds}s"
            raise IntegrationError(msg) from exc

        if proc.returncode != 0:
            ctx.increment("source.paperclip.errors")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            msg = f"paperclip search exited {proc.returncode}: {stderr_text or 'no stderr'}"
            raise IntegrationError(msg)

        try:
            payload = json.loads(stdout_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            ctx.increment("source.paperclip.errors")
            msg = f"paperclip search returned non-JSON output: {exc}"
            raise IntegrationError(msg) from exc

        if not isinstance(payload, list):
            msg = f"paperclip search must return a JSON array; got {type(payload).__name__}"
            raise IntegrationError(msg)

        for hit in payload:
            paper = _hit_to_paper(hit) if isinstance(hit, dict) else None
            if paper is not None:
                yield paper


# ---------------------------------------------------------------------------
# Hit -> Paper mapping
# ---------------------------------------------------------------------------


def _hit_to_paper(hit: dict[str, Any]) -> Paper | None:
    """Convert a paperclip JSON hit into a :class:`Paper`, or ``None``.

    Defensive: missing/malformed entries are skipped (logged at warn
    level) so one bad row never poisons a whole batch.
    """
    canonical_id = _canonical_id_for_hit(hit)
    if canonical_id is None:
        logger.warning("paperclip.parse.skip", reason="no canonical id", hit=hit.get("id"))
        return None

    title = _safe_str(hit.get("title"))
    abstract = _safe_str(hit.get("abstract"))
    if not title or not abstract:
        logger.warning("paperclip.parse.skip", reason="missing title/abstract", id=canonical_id)
        return None

    raw_authors = hit.get("authors")
    authors: list[Author] = []
    if isinstance(raw_authors, list):
        for entry in raw_authors:
            name = _author_name(entry)
            if name:
                authors.append(Author(name=name))
    if not authors:
        logger.warning("paperclip.parse.skip", reason="no authors", id=canonical_id)
        return None

    published_at = _parse_published(hit.get("published"))
    if published_at is None:
        logger.warning("paperclip.parse.skip", reason="bad published", id=canonical_id)
        return None

    landing_url = _safe_str(hit.get("url"))
    pdf_url = _safe_str(hit.get("pdf_url"))

    try:
        return Paper(
            canonical_id=canonical_id,
            title=title.strip(),
            authors=authors,
            abstract=abstract.strip(),
            published_at=published_at,
            categories=[],
            pdf_url=pdf_url,
            landing_url=landing_url,
        )
    except ValueError as exc:
        logger.warning(
            "paperclip.parse.skip", reason="model validation", id=canonical_id, error=str(exc)
        )
        return None


def _canonical_id_for_hit(hit: dict[str, Any]) -> str | None:
    """Pick the right canonical-id namespace for a paperclip hit."""
    external = hit.get("external_ids")
    if isinstance(external, dict):
        arxiv_raw = external.get("arxiv")
        if isinstance(arxiv_raw, str):
            normalized = normalize_arxiv_id(arxiv_raw)
            if normalized is not None:
                return f"arxiv:{normalized}"

    raw_id = _safe_str(hit.get("id"))
    if not raw_id:
        return None

    source = (_safe_str(hit.get("source")) or "").lower()
    prefix_map = {
        "biorxiv": "bio",
        "medrxiv": "bio",
        "pmc": "pmc",
    }
    prefix = prefix_map.get(source, source) if source else "unknown"
    return f"paperclip:{prefix}_{raw_id}"


def _author_name(entry: object) -> str | None:
    """Authors arrive as either bare strings or ``{"name": "..."}`` dicts."""
    if isinstance(entry, str):
        cleaned = entry.strip()
        return cleaned or None
    if isinstance(entry, dict):
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _parse_published(raw: object) -> datetime | None:
    """Accept either ISO 8601 or ``YYYY-MM-DD`` for the publish date."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(candidate, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _safe_str(value: object) -> str | None:
    """Return ``str(value).strip()`` for non-empty string-like values, else ``None``."""
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


__all__ = ["PaperclipSource"]
