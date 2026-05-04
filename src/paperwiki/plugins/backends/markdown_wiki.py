"""Markdown wiki backend — persists papers + concepts as Markdown files.

Layout produced inside ``vault_path / WIKI_SUBDIR`` (v0.4.2 canonical,
per **D-T**)::

    Wiki/
    ├── papers/         # one file per ingested paper (was ``sources/``
    │   │               # in v0.3.x — read-only fallback until v0.5.0)
    │   └── arxiv_2506.13063.md
    └── concepts/       # synthesized topic articles
        └── Vision-Language_Foundation_Models.md

This backend is the file-IO half of the wiki story. It does **not**
synthesize prose — concept bodies are written by SKILLs that have run
through Claude. Backends are intentionally narrow:

* ``upsert_paper`` (protocol method) writes a per-paper source summary
  to ``Wiki/papers/`` (Task 9.185 / D-T).
* ``upsert_concept`` (extension) writes a synthesized concept article.
* ``query`` (protocol method) is a thin substring search across paper
  titles. Heavier ranking lives in the ``wiki_query`` runner so storage
  and presentation stay decoupled.
* ``list_sources`` / ``list_concepts`` are typed discovery helpers used
  by the lint and compile runners. ``list_sources`` reads ``papers/``
  first AND surfaces any surviving ``Wiki/sources/`` files (v0.3.x
  layout) for one release with a one-shot deprecation warning.

Frontmatter conventions match the format documented in
``tasks/plan.md`` §6.2.1, mirroring the ``status`` / ``confidence`` /
``sources`` / ``related_concepts`` fields used by ``kytmanov``'s
reference implementation so users can layer their own tools on top.
The ``sources`` field name is a *frontmatter schema key* (back-compat
contract, NOT a path) and stays as ``sources`` regardless of where
the on-disk file lives.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import yaml
from loguru import logger

from paperwiki.config.layout import (
    CONCEPTS_SUBDIR,
    LEGACY_PAPERS_SUBDIR,
    PAPERS_SUBDIR,
    WIKI_SUBDIR,
)
from paperwiki.core.properties import build_properties_block

if TYPE_CHECKING:
    from paperwiki.core.models import Recommendation, ScoreBreakdown


# Task 9.185 (D-T): the canonical write target for per-paper notes is
# ``Wiki/papers/`` (PAPERS_SUBDIR). For one release, the backend's
# read path additionally surfaces files surviving in the v0.3.x
# ``Wiki/sources/`` legacy layout (LEGACY_PAPERS_SUBDIR). Each
# legacy file is warned about exactly once per process via the
# module-level ``_LEGACY_WARNED`` set so chatty operators don't see
# the same noise every time ``list_sources()`` is called from
# ``wiki-compile`` / ``wiki-lint`` / ``wiki-query``.
_LEGACY_WARNED: set[Path] = set()
_FRONTMATTER_END_RE = re.compile(r"\n---\n", re.MULTILINE)
_FILENAME_UNSAFE_RE = re.compile(r'[\\/:#?*|<>"\[\]^]+')
_RUN_OF_UNDERSCORE_OR_WHITESPACE = re.compile(r"[\s_]+")


def filter_topics_by_strength(
    matched_topics: list[str],
    score: ScoreBreakdown,
    threshold: float,
) -> list[str]:
    """Filter ``matched_topics`` by per-topic strength gating.

    Both ``MarkdownWikiBackend.upsert_paper`` (frontmatter
    ``related_concepts``) and ``ObsidianReporter`` (digest callout
    ``Matched topics`` line) need to apply the same threshold so the
    two surfaces stay consistent. v0.3.17 added the gate at the
    backend; v0.3.26 (Task 9.28) extracts it here so the reporter can
    call the same code path.

    Per-topic strengths are stored as a JSON string under
    ``score.notes["topic_strengths"]`` (the composite scorer encodes
    them this way to keep ``ScoreBreakdown.notes`` typed as
    ``dict[str, str]``).

    Behavior:

    * ``threshold <= 0.0`` -> return ``list(matched_topics)`` unchanged
      (gate disabled).
    * ``score.notes`` missing or has no ``topic_strengths`` key ->
      return ``list(matched_topics)`` unchanged (legacy data, e.g.
      hand-built Recommendations or non-composite scorers — must not
      silently drop wikilinks).
    * ``topic_strengths`` payload malformed (bad JSON, non-dict) ->
      same fallback as above; defensively preserve all topics.
    * Otherwise drop any topic whose recorded strength is below
      ``threshold``. Topics absent from the strengths dict are
      treated as strength 0.0 (so any positive threshold drops
      them).
    """
    if threshold <= 0.0:
        return list(matched_topics)

    notes = score.notes or {}
    raw = notes.get("topic_strengths")
    if not raw:
        return list(matched_topics)

    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return list(matched_topics)
    if not isinstance(decoded, dict):
        return list(matched_topics)

    topic_strengths: dict[str, float] = {}
    for key, value in decoded.items():
        try:
            topic_strengths[str(key)] = float(value)
        except (TypeError, ValueError):
            continue

    if not topic_strengths:
        return list(matched_topics)

    return [t for t in matched_topics if topic_strengths.get(t, 0.0) >= threshold]


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
    """File-system backed implementation of :class:`WikiBackend`.

    ``callouts`` (task 9.162 / **D-N**) controls whether the per-paper
    source body wraps its Abstract section in an Obsidian
    ``> [!abstract] Abstract`` callout (default) or a plain
    ``## Abstract`` heading (recipe override for plain-Markdown export).
    """

    def __init__(
        self,
        vault_path: Path,
        *,
        wiki_subdir: str = WIKI_SUBDIR,
        callouts: bool = True,
        templater: bool = False,
    ) -> None:
        self.vault_path = vault_path
        self.wiki_root = vault_path / wiki_subdir
        self.callouts = callouts
        self.templater = templater

    # ------------------------------------------------------------------
    # WikiBackend protocol methods
    # ------------------------------------------------------------------

    async def upsert_paper(
        self,
        rec: Recommendation,
        *,
        topic_strength_threshold: float = 0.0,
    ) -> Path:
        """Write or refresh a per-paper source file under ``Wiki/papers/``.

        The frontmatter carries everything downstream tools need to surface
        the paper without re-reading the body: identifiers (``canonical_id``,
        ``landing_url``, ``pdf_url``), publication metadata
        (``published_at``, ``citation_count``, ``domain``), the full
        ``score_breakdown``, and the live ``status`` / ``confidence`` /
        ``last_synthesized`` triple. The body is section-organized so
        Obsidian's outline pane is useful and SKILLs can target individual
        sections during ingest / extract / analyze.

        ``topic_strength_threshold`` gates which topics from
        ``rec.matched_topics`` are written into ``related_concepts``
        frontmatter.  Only topics whose per-topic strength (from
        ``rec.score.notes["topic_strengths"]``) meets or exceeds this
        value are written; topics below it are dropped.  When
        ``topic_strengths`` is absent from ``notes`` (legacy data or the
        composite scorer was not used), all matched topics are written
        (no gating) to preserve backward compatibility.
        """
        paper = rec.paper
        score = rec.score

        filtered_topics = filter_topics_by_strength(
            rec.matched_topics,
            score,
            threshold=topic_strength_threshold,
        )
        related = [f"[[{topic}]]" for topic in filtered_topics]
        now = datetime.now(UTC)
        # Per task 9.161 / **D-D**, every paper-wiki output carries the
        # canonical six-field Obsidian Properties block. ``status`` is
        # already part of the legacy frontmatter; the Properties block
        # supplies it via ``status="draft"`` so the Properties pane and
        # the legacy ``status`` consumer (wiki-lint STATUS_MISMATCH) see
        # the same value.
        properties = build_properties_block(
            when=now,
            tags=list(paper.categories),
            aliases=[],
            status="draft",
        )
        frontmatter: dict[str, object] = {
            "canonical_id": paper.canonical_id,
            "title": paper.title,
            **properties,  # tags / aliases / status / cssclasses / created / updated
            "confidence": round(score.composite, 4),
            "domain": _infer_domain(paper.categories),
            "published_at": paper.published_at.strftime("%Y-%m-%d"),
            "landing_url": paper.landing_url or "",
            "pdf_url": paper.pdf_url or "",
            "citation_count": (paper.citation_count if paper.citation_count is not None else 0),
            "score_breakdown": {
                "composite": round(score.composite, 4),
                "relevance": round(score.relevance, 4),
                "novelty": round(score.novelty, 4),
                "momentum": round(score.momentum, 4),
                "rigor": round(score.rigor, 4),
            },
            "related_concepts": related,
            "last_synthesized": now.strftime("%Y-%m-%d"),
        }

        body = self._default_source_body(
            rec,
            callouts=self.callouts,
            templater=self.templater,
        )
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
        now = datetime.now(UTC)
        # Per task 9.161 / **D-D**, concept articles also carry the
        # six-field Properties block. The legacy ``status`` field stays
        # at the top of the frontmatter for backward compat with
        # wiki-lint STATUS_MISMATCH; ``build_properties_block`` mirrors
        # it inside the Properties block so Obsidian's Properties pane
        # sees a single ``status`` value.
        properties = build_properties_block(
            when=now,
            tags=[],
            aliases=[],
            status=status,
        )
        frontmatter: dict[str, object] = {
            "title": clean_name,
            **properties,
            "confidence": round(confidence, 4),
            "sources": list(sources),
            "related_concepts": list(related_concepts or []),
            "last_synthesized": now.strftime("%Y-%m-%d"),
        }
        path = self._concept_path(clean_name)
        await self._write_markdown(path, frontmatter, body)
        return path

    async def list_sources(self) -> list[SourceSummary]:
        """Return one :class:`SourceSummary` per per-paper file in the vault.

        Reads from ``Wiki/papers/`` (the v0.4.2 canonical layout)
        first; any file surviving in ``Wiki/sources/`` (v0.3.x
        legacy) is also surfaced for one release with a one-shot
        ``backend.legacy.sources_path`` warning per file. v0.5.0
        drops the legacy fallback — see the ``LEGACY_PAPERS_SUBDIR``
        constant in :mod:`paperwiki.config.layout`.

        When a filename appears in BOTH directories the canonical
        ``papers/`` copy wins (legacy is silently skipped to avoid
        duplicate ``SourceSummary`` records, which would mislead
        ``wiki_compile`` / ``wiki_lint``).
        """
        out: list[SourceSummary] = []
        seen_filenames: set[str] = set()

        canonical_dir = self.wiki_root / PAPERS_SUBDIR
        if canonical_dir.is_dir():
            for path in sorted(canonical_dir.glob("*.md")):
                summary = await _build_source_summary(path)
                if summary is None:
                    continue
                seen_filenames.add(path.name)
                out.append(summary)

        legacy_dir = self.wiki_root / LEGACY_PAPERS_SUBDIR
        if legacy_dir.is_dir():
            for path in sorted(legacy_dir.glob("*.md")):
                if path.name in seen_filenames:
                    # Canonical copy already collected — skip silently
                    # so we don't double-count.
                    continue
                summary = await _build_source_summary(path)
                if summary is None:
                    continue
                if path not in _LEGACY_WARNED:
                    _LEGACY_WARNED.add(path)
                    logger.warning(
                        "backend.legacy.sources_path path={path}",
                        path=str(path),
                    )
                out.append(summary)

        return out

    async def list_concepts(self) -> list[ConceptSummary]:
        """Return one :class:`ConceptSummary` per file under ``concepts/``."""
        directory = self.wiki_root / CONCEPTS_SUBDIR
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
        # Task 9.185 (D-T): all NEW per-paper writes land at
        # ``Wiki/papers/`` (PAPERS_SUBDIR). The legacy
        # ``Wiki/sources/`` (LEGACY_PAPERS_SUBDIR) is read-only via
        # ``list_sources`` for one release before deletion in v0.5.0.
        filename = _canonical_id_to_filename(canonical_id)
        return self.wiki_root / PAPERS_SUBDIR / f"{filename}.md"

    def _concept_path(self, name: str) -> Path:
        return self.wiki_root / CONCEPTS_SUBDIR / f"{_concept_name_to_filename(name)}.md"

    @staticmethod
    def _default_source_body(
        rec: Recommendation,
        *,
        callouts: bool = True,
        templater: bool = False,
    ) -> str:
        """Render the section-organized body for a fresh source stub.

        The five sections are stable so SKILLs (analyze, wiki-ingest,
        extract-images) can target them deterministically. Empty
        sections include "(Run /paper-wiki:<skill>)" hints so users know
        what fills them.

        ``callouts`` (task 9.162 / **D-N**): when ``True`` (default), the
        Abstract section uses an Obsidian ``> [!abstract] Abstract``
        callout; when ``False``, falls back to ``## Abstract`` for
        plain-Markdown export.

        ``templater`` (task 9.164): when ``True``, the Notes section is
        stamped with a Templater ``<%* tp.file.last_modified_date(...) %>``
        block so the user gets a live "last edited" timestamp every time
        Obsidian re-renders the file. Default-off because non-Templater
        users would see ``<%* %>`` as literal text.
        """
        paper = rec.paper
        score = rec.score
        author_names = ", ".join(a.name for a in paper.authors) or "(unknown)"
        published = paper.published_at.strftime("%Y-%m-%d")
        landing = paper.landing_url or paper.canonical_id
        pdf_line = f"- **PDF**: <{paper.pdf_url}>\n" if paper.pdf_url else ""
        citation_line = (
            f"- **Citations**: {paper.citation_count}\n"
            if paper.citation_count is not None
            else "- **Citations**: —\n"
        )

        abstract_text = paper.abstract.strip()
        if callouts:
            quoted = "\n".join(f"> {ln}" if ln else ">" for ln in abstract_text.splitlines())
            abstract_section = f"> [!abstract] Abstract\n{quoted}\n"
        else:
            abstract_section = f"## Abstract\n\n{abstract_text}\n"

        # Per task 9.164: when ``templater=True``, prepend a Templater
        # ``<%* %>`` block to the Notes section so the user gets a live
        # "last edited" stamp via ``tp.file.last_modified_date``. Off by
        # default — non-Templater users would see this as literal text.
        notes_templater_stamp = (
            ("\n_Last edit: <%* tR += tp.file.last_modified_date('YYYY-MM-DD HH:mm') %>_\n\n")
            if templater
            else ""
        )

        return (
            f"# {paper.title}\n"
            "\n"
            "## Core Information\n"
            "\n"
            f"- **Authors**: {author_names}\n"
            f"- **Published**: {published}\n"
            f"- **Source**: {landing}\n"
            + pdf_line
            + citation_line
            + (
                f"- **Score**: {score.composite:.2f} "
                f"(relevance {score.relevance:.2f}, novelty {score.novelty:.2f}, "
                f"momentum {score.momentum:.2f}, rigor {score.rigor:.2f})\n"
            )
            + "\n"
            + abstract_section
            + "\n"
            "## Key Takeaways\n"
            "\n"
            "_Run `/paper-wiki:wiki-ingest "
            f"{paper.canonical_id}` to fold this paper into concept articles "
            "and replace this placeholder with synthesized takeaways._\n"
            "\n"
            "## Figures\n"
            "\n"
            "_Run `/paper-wiki:extract-images "
            f"{paper.canonical_id}` to download the arXiv source tarball "
            "and embed real paper figures here._\n"
            "\n"
            "## Notes\n" + notes_templater_stamp + "\n"
            "_Your annotations and follow-up questions go here. Survives "
            "re-ingest because SKILLs only rewrite the sections above._\n"
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


_DOMAIN_LABELS: dict[str, str] = {
    # CS
    "cs.AI": "Artificial Intelligence",
    "cs.LG": "Machine Learning",
    "cs.CL": "NLP",
    "cs.CV": "Computer Vision",
    "cs.MA": "Multi-Agent Systems",
    "cs.MM": "Multimedia",
    "cs.RO": "Robotics",
    # EE
    "eess.IV": "Image / Video Processing",
    # Q-bio
    "q-bio.QM": "Quantitative Biology",
    "q-bio.BM": "Biomolecules",
    "q-bio.GN": "Genomics",
    # Stat
    "stat.ML": "Statistics / Machine Learning",
}


def _infer_domain(categories: list[str]) -> str:
    """Pick a human-readable domain label from arxiv-style categories.

    Heuristic: first match in a curated translation table; falls back
    to the first category verbatim, or ``"unknown"`` if the list is
    empty. The result is for display only — the original category
    list still lives in ``tags`` frontmatter.
    """
    for cat in categories:
        if cat in _DOMAIN_LABELS:
            return _DOMAIN_LABELS[cat]
    return categories[0] if categories else "unknown"


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


async def _build_source_summary(path: Path) -> SourceSummary | None:
    """Read frontmatter + return a :class:`SourceSummary` (or ``None``).

    Extracted from :meth:`MarkdownWikiBackend.list_sources` (Task 9.185)
    so the canonical-vs-legacy walk can re-use the same conversion
    logic without duplicating the frontmatter handling.
    """
    fm = await _read_frontmatter(path)
    if fm is None:
        return None
    return SourceSummary(
        canonical_id=str(fm.get("canonical_id") or ""),
        title=str(fm.get("title") or path.stem),
        path=path,
        status=str(fm.get("status") or "draft"),
        confidence=_as_float(fm.get("confidence")),
        related_concepts=_str_list(fm.get("related_concepts")),
        tags=_str_list(fm.get("tags")),
    )


__all__ = [
    "ConceptSummary",
    "MarkdownWikiBackend",
    "SourceSummary",
    "filter_topics_by_strength",
]
