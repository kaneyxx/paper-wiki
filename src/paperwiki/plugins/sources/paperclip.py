"""paperclip source plugin.

Wraps the third-party `paperclip <https://gxl.ai/blog/paperclip>`_ CLI
as a paper-wiki :class:`Source`. paperclip indexes 8M+ biomedical
papers across bioRxiv, medRxiv, and PubMed Central; this plugin lets a
recipe pull from that corpus alongside arXiv and Semantic Scholar.

CLI flow (paperclip 0.2.x):

1. ``paperclip search QUERY [-n N] [--since Nd] [--journal NAME] [-T TYPE]``
   prints a human-readable result list and a session id of the form
   ``s_<hex>``. The session id is the only structured handle the CLI
   exposes.
2. ``paperclip results <session_id> --save <file.csv>`` exports the
   structured CSV with columns
   ``title, authors, id, source, date, url, abstract``.

The plugin chains both calls inside :meth:`PaperclipSource.fetch` and
parses the CSV. Tests stub at ``asyncio.create_subprocess_exec`` so
the suite stays hermetic.

Identifier convention:

* Hits whose ``id`` starts with ``bio_`` (paperclip's bioRxiv /
  medRxiv namespace) yield ``paperclip:<id>``.
* Hits whose ``id`` starts with ``PMC`` yield
  ``paperclip:pmc_<id>``.
* Anything else falls back to ``paperclip:<id>`` verbatim.
"""

from __future__ import annotations

import asyncio
import csv
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from paperwiki.core.errors import IntegrationError
from paperwiki.core.models import Author, Paper

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from paperwiki.core.models import RunContext


_DEFAULT_TIMEOUT_SECONDS = 60.0
_SESSION_ID_RE = re.compile(r"\[(s_[0-9a-f]+)\]")


class PaperclipSource:
    """Subprocess-backed source plugin for the paperclip biomedical search CLI.

    Parameters
    ----------
    query:
        Free-text search expression handed to ``paperclip search``.
    limit:
        Upper bound on results per fetch, passed via ``-n``.
    since_days:
        Optional ``--since {N}d`` filter (e.g. ``since_days=14``).
    journal:
        Optional ``--journal NAME`` filter.
    document_type:
        Optional ``-T TYPE`` filter (paperclip's user-defined
        collections: youtube, meeting, cber, toc_review, crl, …).
        Empty by default — searches the whole biomedical corpus.
    paperclip_bin:
        CLI binary name. Override for tests or non-standard installs.
    timeout_seconds:
        Hard timeout for each subprocess call (search and results).
    """

    name = "paperclip"

    def __init__(
        self,
        query: str,
        *,
        limit: int = 20,
        since_days: int | None = None,
        journal: str | None = None,
        document_type: str | None = None,
        paperclip_bin: str = "paperclip",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not query or not query.strip():
            msg = "PaperclipSource requires a non-empty query"
            raise ValueError(msg)
        if limit < 1:
            msg = f"limit must be >= 1; got {limit!r}"
            raise ValueError(msg)
        self.query = query.strip()
        self.limit = limit
        self.since_days = since_days
        self.journal = journal.strip() if isinstance(journal, str) else None
        self.document_type = document_type.strip() if isinstance(document_type, str) else None
        self.paperclip_bin = paperclip_bin
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------
    # Source protocol
    # ------------------------------------------------------------------

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        """Yield :class:`Paper` objects from a paperclip search session."""
        ctx.increment("source.paperclip.requests")

        session_id = await self._run_search(ctx)
        with tempfile.TemporaryDirectory(prefix="paperwiki-paperclip-") as tmp:
            csv_path = Path(tmp) / "results.csv"
            await self._save_results(ctx, session_id, csv_path)
            for hit in _read_csv(csv_path):
                paper = _hit_to_paper(hit)
                if paper is not None:
                    yield paper

    # ------------------------------------------------------------------
    # Subprocess helpers
    # ------------------------------------------------------------------

    async def _run_search(self, ctx: RunContext) -> str:
        """Run ``paperclip search`` and return the session id printed in stdout."""
        argv = [self.paperclip_bin, "search", self.query, "-n", str(self.limit)]
        if self.since_days is not None and self.since_days > 0:
            argv.extend(["--since", f"{self.since_days}d"])
        if self.journal:
            argv.extend(["--journal", self.journal])
        if self.document_type:
            argv.extend(["-T", self.document_type])

        stdout_text, stderr_text = await self._communicate(ctx, argv)

        for haystack in (stdout_text, stderr_text):
            match = _SESSION_ID_RE.search(haystack)
            if match is not None:
                return match.group(1)

        ctx.increment("source.paperclip.errors")
        msg = (
            "paperclip search returned no session id; expected `[s_<hex>]` "
            f"in output. stdout={stdout_text!r} stderr={stderr_text!r}"
        )
        raise IntegrationError(msg)

    async def _save_results(self, ctx: RunContext, session_id: str, csv_path: Path) -> None:
        """Run ``paperclip results <id> --save <file>`` and verify the CSV exists."""
        argv = [
            self.paperclip_bin,
            "results",
            session_id,
            "--save",
            str(csv_path),
        ]
        await self._communicate(ctx, argv)
        if not csv_path.is_file():
            ctx.increment("source.paperclip.errors")
            msg = (
                f"paperclip results --save wrote no file at {csv_path}; "
                "session may have expired or storage is read-only."
            )
            raise IntegrationError(msg)

    async def _communicate(self, ctx: RunContext, argv: list[str]) -> tuple[str, str]:
        """Spawn one paperclip subprocess and return (stdout, stderr) decoded."""
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
                "install the CLI and authenticate."
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
            msg = f"paperclip {argv[1]} timed out after {self.timeout_seconds}s"
            raise IntegrationError(msg) from exc

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            ctx.increment("source.paperclip.errors")
            msg = (
                f"paperclip {argv[1]} exited {proc.returncode}: "
                f"{stderr_text.strip() or 'no stderr'}"
            )
            raise IntegrationError(msg)

        return stdout_text, stderr_text


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read paperclip's ``results --save`` CSV into a list of row dicts."""
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


_EMPTY_ABSTRACT_PLACEHOLDER = "_(no abstract available from paperclip)_"


def _hit_to_paper(hit: dict[str, str]) -> Paper | None:
    """Convert a paperclip CSV row into a :class:`Paper`, or ``None``.

    Real paperclip CSVs frequently ship empty ``abstract`` cells —
    that is normal upstream data, not a parse failure. We keep the
    paper and substitute a placeholder so dedup/scoring/reporters
    still see a usable record; the placeholder also signals to the
    user that paperclip itself did not provide an abstract for this
    hit.
    """
    raw_id = (hit.get("id") or "").strip()
    if not raw_id:
        logger.warning("paperclip.parse.skip", reason="missing id")
        return None

    canonical_id = _canonical_id_for_id(raw_id)

    title = (hit.get("title") or "").strip()
    if not title:
        logger.warning("paperclip.parse.skip", reason="missing title", id=canonical_id)
        return None
    abstract = (hit.get("abstract") or "").strip() or _EMPTY_ABSTRACT_PLACEHOLDER

    authors = _split_authors(hit.get("authors", ""))
    if not authors:
        logger.warning("paperclip.parse.skip", reason="no authors", id=canonical_id)
        return None

    published_at = _parse_date(hit.get("date", ""))
    if published_at is None:
        logger.warning("paperclip.parse.skip", reason="bad date", id=canonical_id)
        return None

    landing_url = (hit.get("url") or "").strip() or None
    journal = (hit.get("source") or "").strip()
    categories = [journal] if journal else []

    try:
        return Paper(
            canonical_id=canonical_id,
            title=title,
            authors=authors,
            abstract=abstract,
            published_at=published_at,
            categories=categories,
            pdf_url=None,
            landing_url=landing_url,
        )
    except ValueError as exc:
        logger.warning(
            "paperclip.parse.skip",
            reason="model validation",
            id=canonical_id,
            error=str(exc),
        )
        return None


def _canonical_id_for_id(raw_id: str) -> str:
    """Pick the right canonical-id namespace based on the raw paperclip id."""
    if raw_id.startswith("bio_"):
        return f"paperclip:{raw_id}"
    if raw_id.startswith("PMC"):
        return f"paperclip:pmc_{raw_id}"
    return f"paperclip:{raw_id}"


def _split_authors(raw: str) -> list[Author]:
    """Authors in CSV arrive as a comma-separated string (trailing ``*`` allowed)."""
    if not raw:
        return []
    return [
        Author(name=cleaned)
        for cleaned in (chunk.strip().rstrip("*").strip() for chunk in raw.split(","))
        if cleaned
    ]


def _parse_date(raw: str) -> datetime | None:
    """paperclip CSV uses ``YYYY-MM-DD``; missing/invalid values yield ``None``."""
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        return datetime.strptime(candidate, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


__all__ = ["PaperclipSource"]
