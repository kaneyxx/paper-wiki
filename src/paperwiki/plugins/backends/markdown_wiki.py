"""Markdown wiki backend — persists sources + concepts as Markdown files.

Layout produced inside ``vault_path / WIKI_SUBDIR``::

    Wiki/
    ├── sources/        # one file per ingested paper
    │   └── arxiv_2506.13063.md
    └── concepts/       # synthesized topic articles
        └── Vision-Language_Foundation_Models.md

This backend is the file-IO half of the wiki story. It does **not**
synthesize prose — concept bodies are written by SKILLs that have run
through Claude. Backends are intentionally narrow:

* ``upsert_paper`` (protocol method) writes a per-paper source summary.
* ``upsert_concept`` (extension) writes a synthesized concept article.
* ``query`` (protocol method) is a thin substring search across source
  titles. Heavier ranking lives in the ``wiki_query`` runner so storage
  and presentation stay decoupled.
* ``list_sources`` / ``list_concepts`` are typed discovery helpers used
  by the lint and compile runners.

Frontmatter conventions match the format documented in
``tasks/plan.md`` §6.2.1, mirroring the ``status`` / ``confidence`` /
``sources`` / ``related_concepts`` fields used by ``kytmanov``'s
reference implementation so users can layer their own tools on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import yaml

from paperwiki.config.layout import WIKI_SUBDIR

if TYPE_CHECKING:
    from paperwiki.core.models import Recommendation


_SOURCES_DIRNAME = "sources"
_CONCEPTS_DIRNAME = "concepts"
_FRONTMATTER_END_RE = re.compile(r"\n---\n", re.MULTILINE)
_FILENAME_UNSAFE_RE = re.compile(r'[\\/:#?*|<>"\[\]^]+')
_RUN_OF_UNDERSCORE_OR_WHITESPACE = re.compile(r"[\s_]+")


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """Discovery record for a per-paper source file."""

    canonical_id: str
    title: str
    path: Path
    status: str
    confidence: float
    related_concepts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConceptSummary:
    """Discovery record for a concept article."""

    name: str
    title: str
    path: Path
    status: str
    confidence: float
    sources: list[str] = field(default_factory=list)
    related_concepts: list[str] = field(default_factory=list)


class MarkdownWikiBackend:
    """File-system backed implementation of :class:`WikiBackend`."""

    def __init__(
        self,
        vault_path: Path,
        *,
        wiki_subdir: str = WIKI_SUBDIR,
    ) -> None:
        self.vault_path = vault_path
        self.wiki_root = vault_path / wiki_subdir

    # ------------------------------------------------------------------
    # WikiBackend protocol methods
    # ------------------------------------------------------------------

    async def upsert_paper(self, rec: Recommendation) -> Path:
        """Write or refresh a per-paper source file under ``sources/``.

        The file's frontmatter mirrors the recommendation: ``canonical_id``
        and ``title`` are stable; ``confidence`` is initialized from the
        composite score; ``tags`` carry over the paper's categories;
        ``related_concepts`` is seeded from ``matched_topics`` (each
        becomes a wikilink). The body is intentionally minimal — SKILLs
        regenerate it during ingest.
        """
        paper = rec.paper
        score = rec.score

        related = [f"[[{topic}]]" for topic in rec.matched_topics]
        frontmatter: dict[str, object] = {
            "canonical_id": paper.canonical_id,
            "title": paper.title,
            "status": "draft",
            "confidence": round(score.composite, 4),
            "tags": list(paper.categories),
            "related_concepts": related,
            "last_synthesized": datetime.now(UTC).strftime("%Y-%m-%d"),
        }

        body = self._default_source_body(rec)
        path = self._source_path(paper.canonical_id)
        await self._write_markdown(path, frontmatter, body)
        return path

    async def query(self, q: str) -> list[Recommendation]:
        """Substring search across source titles.

        Concept results are not surfaced here — heavy ranking happens
        in the ``wiki_query`` runner. The protocol's
        :class:`Recommendation` return type only fits sources cleanly,
        so this backend method stays narrow.
        """
        from paperwiki.core.models import (
            Author,
            Paper,
            Recommendation,
            ScoreBreakdown,
        )

        if not q.strip():
            return []
        needle = q.lower()

        results: list[Recommendation] = []
        for summary in await self.list_sources():
            if needle not in summary.title.lower():
                continue
            results.append(
                Recommendation(
                    paper=Paper(
                        canonical_id=summary.canonical_id,
                        title=summary.title,
                        authors=[Author(name="(from wiki)")],
                        abstract=summary.path.name,
                        published_at=datetime.now(UTC),
                        categories=summary.tags,
                    ),
                    score=ScoreBreakdown(composite=summary.confidence),
                )
            )
        return results

    # ------------------------------------------------------------------
    # MarkdownWikiBackend extensions
    # ------------------------------------------------------------------

    async def upsert_concept(
        self,
        name: str,
        body: str,
        *,
        sources: list[str],
        related_concepts: list[str] | None = None,
        confidence: float = 0.5,
        status: str = "draft",
    ) -> Path:
        """Write or refresh a synthesized concept article under ``concepts/``."""
        if not name or not name.strip():
            msg = "concept name must be non-empty"
            raise ValueError(msg)
        if not 0.0 <= confidence <= 1.0:
            msg = f"confidence must be in [0, 1]; got {confidence!r}"
            raise ValueError(msg)
        if status not in {"draft", "reviewed", "stale"}:
            msg = f"status must be draft|reviewed|stale; got {status!r}"
            raise ValueError(msg)

        clean_name = name.strip()
        frontmatter: dict[str, object] = {
            "title": clean_name,
            "status": status,
            "confidence": round(confidence, 4),
            "sources": list(sources),
            "related_concepts": list(related_concepts or []),
            "last_synthesized": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        path = self._concept_path(clean_name)
        await self._write_markdown(path, frontmatter, body)
        return path

    async def list_sources(self) -> list[SourceSummary]:
        """Return one :class:`SourceSummary` per file under ``sources/``."""
        directory = self.wiki_root / _SOURCES_DIRNAME
        if not directory.is_dir():
            return []
        out: list[SourceSummary] = []
        for path in sorted(directory.glob("*.md")):
            fm = await _read_frontmatter(path)
            if fm is None:
                continue
            out.append(
                SourceSummary(
                    canonical_id=str(fm.get("canonical_id") or ""),
                    title=str(fm.get("title") or path.stem),
                    path=path,
                    status=str(fm.get("status") or "draft"),
                    confidence=_as_float(fm.get("confidence")),
                    related_concepts=_str_list(fm.get("related_concepts")),
                    tags=_str_list(fm.get("tags")),
                )
            )
        return out

    async def list_concepts(self) -> list[ConceptSummary]:
        """Return one :class:`ConceptSummary` per file under ``concepts/``."""
        directory = self.wiki_root / _CONCEPTS_DIRNAME
        if not directory.is_dir():
            return []
        out: list[ConceptSummary] = []
        for path in sorted(directory.glob("*.md")):
            fm = await _read_frontmatter(path)
            if fm is None:
                continue
            out.append(
                ConceptSummary(
                    name=path.stem,
                    title=str(fm.get("title") or path.stem),
                    path=path,
                    status=str(fm.get("status") or "draft"),
                    confidence=_as_float(fm.get("confidence")),
                    sources=_str_list(fm.get("sources")),
                    related_concepts=_str_list(fm.get("related_concepts")),
                )
            )
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _source_path(self, canonical_id: str) -> Path:
        return self.wiki_root / _SOURCES_DIRNAME / f"{_canonical_id_to_filename(canonical_id)}.md"

    def _concept_path(self, name: str) -> Path:
        return self.wiki_root / _CONCEPTS_DIRNAME / f"{_concept_name_to_filename(name)}.md"

    @staticmethod
    def _default_source_body(rec: Recommendation) -> str:
        paper = rec.paper
        author_names = ", ".join(a.name for a in paper.authors)
        link = paper.landing_url or paper.canonical_id
        return (
            f"# {paper.title}\n\n"
            f"- **Authors**: {author_names}\n"
            f"- **Source**: {link}\n\n"
            f"{paper.abstract.strip()}\n"
        )

    @staticmethod
    async def _write_markdown(
        path: Path,
        frontmatter: dict[str, object],
        body: str,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = (
            "---\n"
            + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
            + "---\n\n"
            + body.rstrip()
            + "\n"
        )
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(rendered)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_id_to_filename(canonical_id: str) -> str:
    """``arxiv:2506.13063`` -> ``arxiv_2506.13063``.

    The colon is filename-unsafe on Windows; we always replace it with
    an underscore so the same canonical id round-trips cleanly between
    Linux, macOS, and Windows.
    """
    return canonical_id.replace(":", "_")


def _concept_name_to_filename(name: str) -> str:
    """Sanitize a concept name into a filename-safe slug.

    Replaces filename-unsafe characters with underscores, collapses
    whitespace + underscore runs, and trims leading/trailing
    underscores. Hyphens and periods are preserved because Obsidian
    handles them gracefully in note names.
    """
    safe = _FILENAME_UNSAFE_RE.sub("_", name)
    safe = _RUN_OF_UNDERSCORE_OR_WHITESPACE.sub("_", safe)
    return safe.strip("_") or "untitled"


def _str_list(value: object) -> list[str]:
    """Coerce a frontmatter list-like value into ``list[str]``."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _as_float(value: object, default: float = 0.0) -> float:
    """Coerce a frontmatter value to ``float``, falling back to ``default``."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


async def _read_frontmatter(path: Path) -> dict[str, object] | None:
    """Return the YAML frontmatter for a markdown file or ``None`` if missing."""
    async with aiofiles.open(path, encoding="utf-8") as fh:
        text = await fh.read()
    if not text.startswith("---\n"):
        return None
    match = _FRONTMATTER_END_RE.search(text, pos=4)
    if match is None:
        return None
    block = text[4 : match.start()]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


__all__ = [
    "ConceptSummary",
    "MarkdownWikiBackend",
    "SourceSummary",
]
