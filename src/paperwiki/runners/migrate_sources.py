"""``paperwiki.runners.migrate_sources`` — upgrade legacy source stubs.

The format of ``Wiki/sources/<id>.md`` evolves. Each format change is
written into ``MarkdownWikiBackend`` and pinned by the backend's unit
tests. Existing source files in user vaults stay on whatever format
they were originally written under, which leaves the user with a
mixed-format wiki and confused outline panes.

This runner walks every ``Wiki/sources/*.md`` and rewrites legacy
files to the current canonical format while preserving any
user-authored content under ``## Notes``, ``## Key Takeaways``, and
``## Figures``. It is idempotent: re-running on a fresh vault is a
no-op.

Whenever the source-stub format changes again, update both:

1. ``MarkdownWikiBackend.upsert_paper`` and
   ``MarkdownWikiBackend._default_source_body`` (write path).
2. The detection / extraction helpers below (read path).

Tests in ``tests/unit/runners/test_migrate_sources.py`` should grow
a regression case for the new shape so future migrations stay
backwards-compatible.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from loguru import logger

from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.core.models import Author, Paper, Recommendation, ScoreBreakdown
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

app = typer.Typer(
    add_completion=False,
    help="Upgrade legacy Wiki/sources/<id>.md files to the current format.",
    no_args_is_help=True,
)


# A file is considered "current format" when it has the canonical
# section heading set introduced in v0.3.2.
_CURRENT_FORMAT_MARKER = "## Core Information"

# Generic per-section regex; captures from the heading to the next
# ``## ``-level heading or end-of-text.
_SECTION_RE_TEMPLATE = r"(?P<heading>^## {section}\n)(?P<body>.*?)(?=^## |\Z)"
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_AUTHORS_LINE_RE = re.compile(r"^\s*-\s+\*\*Authors?\*\*:\s*(.+?)$", re.MULTILINE)
_SOURCE_LINE_RE = re.compile(r"^\s*-\s+\*\*Source\*\*:\s*(.+?)$", re.MULTILINE)


@dataclass(slots=True)
class MigrateReport:
    """Machine-readable summary returned by :func:`migrate_vault`."""

    checked: int = 0
    migrated: int = 0
    skipped: int = 0
    migrated_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Single-file migration (sync — file-IO + parsing, no network)
# ---------------------------------------------------------------------------


def migrate_source(path: Path) -> bool:
    """Rewrite ``path`` into the current source-stub format.

    Returns ``True`` when the file was rewritten, ``False`` when it
    was already in the current format (no-op). Raises if the file is
    so malformed that we can't even read its frontmatter.
    """
    text = path.read_text(encoding="utf-8")
    if _CURRENT_FORMAT_MARKER in text:
        return False

    front, body = _split_frontmatter(text)
    rec = _build_recommendation(front, body)
    preserved = _extract_user_sections(text)

    backend = MarkdownWikiBackend(vault_path=_synthetic_vault_path(path))
    new_body = backend._default_source_body(rec)
    new_front = _build_frontmatter(rec, front)

    rendered = (
        "---\n"
        + yaml.safe_dump(new_front, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + _merge_preserved_sections(new_body, preserved)
    )
    path.write_text(rendered, encoding="utf-8")
    return True


def _synthetic_vault_path(source_path: Path) -> Path:
    """Reverse-engineer the vault path from a ``Wiki/sources/<id>.md`` path.

    ``MarkdownWikiBackend._default_source_body`` is a static method so
    it doesn't actually need a vault path, but instantiating the
    backend keeps the call signature explicit.
    """
    # source_path = <vault>/Wiki/sources/<file>.md → vault is parents[2].
    return source_path.parents[2]


# ---------------------------------------------------------------------------
# Vault-wide migration
# ---------------------------------------------------------------------------


async def migrate_vault(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    dry_run: bool = False,
) -> MigrateReport:
    """Walk every ``Wiki/sources/*.md`` and migrate where needed.

    ``dry_run=True`` returns the same counts but never writes.
    """
    report = MigrateReport()
    sources_dir = vault_path / wiki_subdir / "sources"
    if not sources_dir.is_dir():
        return report

    for path in sorted(sources_dir.glob("*.md")):
        report.checked += 1
        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except OSError as exc:
            report.errors.append(f"{path.name}: {exc}")
            continue

        if _CURRENT_FORMAT_MARKER in text:
            report.skipped += 1
            continue

        if dry_run:
            report.migrated += 1
            report.migrated_paths.append(str(path.relative_to(vault_path)))
            continue

        try:
            await asyncio.to_thread(migrate_source, path)
        except (yaml.YAMLError, ValueError, OSError) as exc:
            report.errors.append(f"{path.name}: {exc}")
            continue
        report.migrated += 1
        report.migrated_paths.append(str(path.relative_to(vault_path)))

    return report


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``({frontmatter dict}, body)``. Frontmatter optional."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, body


def _build_recommendation(
    frontmatter: dict[str, Any],
    body: str,
) -> Recommendation:
    """Reconstruct a synthetic ``Recommendation`` from old-format content.

    Missing fields default to safe values (``citation_count=0``, empty
    URLs, ``score_breakdown.relevance/novelty/momentum/rigor=0``).
    """
    canonical_id = str(frontmatter.get("canonical_id") or "unknown:legacy")
    title = str(frontmatter.get("title") or "(unknown title)")
    confidence = _coerce_float(frontmatter.get("confidence"), default=0.5)

    authors_match = _AUTHORS_LINE_RE.search(body)
    if authors_match:
        author_names = [
            n.strip().rstrip("*").strip() for n in authors_match.group(1).split(",") if n.strip()
        ]
    else:
        author_names = []
    authors = [Author(name=n) for n in author_names] if author_names else [Author(name="(unknown)")]

    source_match = _SOURCE_LINE_RE.search(body)
    landing_url = source_match.group(1).strip() if source_match else None
    # Strip ``[label](url)`` markdown-link syntax if present.
    if landing_url and landing_url.startswith("["):
        inner = landing_url.split("](", 1)
        if len(inner) == 2:
            landing_url = inner[1].rstrip(")")
    pdf_url = _derive_pdf_url(landing_url) if landing_url else None

    abstract = _extract_abstract(body) or "(abstract unavailable in legacy format)"

    published_at = _parse_published(
        frontmatter.get("published_at") or frontmatter.get("last_synthesized")
    )
    citation_count_raw = frontmatter.get("citation_count")
    citation_count = int(citation_count_raw) if isinstance(citation_count_raw, int) else None

    paper = Paper(
        canonical_id=canonical_id,
        title=title,
        authors=authors,
        abstract=abstract,
        published_at=published_at,
        categories=_str_list(frontmatter.get("tags")),
        landing_url=landing_url if landing_url and landing_url.startswith("http") else None,
        pdf_url=pdf_url,
        citation_count=citation_count,
    )
    score = ScoreBreakdown(composite=confidence)
    matched_topics = [
        t.strip("[]") for t in _str_list(frontmatter.get("related_concepts")) if t.strip("[]")
    ]
    return Recommendation(paper=paper, score=score, matched_topics=matched_topics)


def _build_frontmatter(
    rec: Recommendation,
    legacy_frontmatter: dict[str, Any],
) -> dict[str, Any]:
    """Compose the new-format frontmatter, copying through fields the
    backend writes. Stable fields (``status``, ``last_synthesized``)
    are taken from the legacy entry when present."""
    paper = rec.paper
    score = rec.score
    from paperwiki.plugins.backends.markdown_wiki import _infer_domain

    status = str(legacy_frontmatter.get("status") or "draft")
    if status not in {"draft", "reviewed", "stale"}:
        status = "draft"
    last_synthesized = legacy_frontmatter.get("last_synthesized") or datetime.now(UTC).strftime(
        "%Y-%m-%d"
    )

    return {
        "canonical_id": paper.canonical_id,
        "title": paper.title,
        "status": status,
        "confidence": round(score.composite, 4),
        "domain": _infer_domain(paper.categories),
        "tags": list(paper.categories),
        "published_at": paper.published_at.strftime("%Y-%m-%d"),
        "landing_url": paper.landing_url or "",
        "pdf_url": paper.pdf_url or "",
        "citation_count": paper.citation_count if paper.citation_count is not None else 0,
        "score_breakdown": {
            "composite": round(score.composite, 4),
            "relevance": round(score.relevance, 4),
            "novelty": round(score.novelty, 4),
            "momentum": round(score.momentum, 4),
            "rigor": round(score.rigor, 4),
        },
        "related_concepts": [f"[[{t}]]" for t in rec.matched_topics],
        "last_synthesized": str(last_synthesized),
    }


# ---------------------------------------------------------------------------
# User-content preservation
# ---------------------------------------------------------------------------


def _extract_user_sections(text: str) -> dict[str, str]:
    """Pull preservable per-section content out of an existing file.

    Returns ``{section_name: section_body}`` for any of the three
    user-editable sections (``Notes``, ``Key Takeaways``, ``Figures``)
    that exist in ``text``. Section bodies that look like the
    placeholder we ship are dropped (so they get re-inserted fresh
    from the backend's default body).
    """
    out: dict[str, str] = {}
    for section in ("Notes", "Key Takeaways", "Figures"):
        regex = re.compile(
            _SECTION_RE_TEMPLATE.format(section=re.escape(section)),
            re.DOTALL | re.MULTILINE,
        )
        match = regex.search(text)
        if match is None:
            continue
        body = match.group("body").strip()
        if not body or _looks_like_placeholder(body):
            continue
        out[section] = body
    return out


def _merge_preserved_sections(new_body: str, preserved: dict[str, str]) -> str:
    """Re-inject preserved section bodies into the freshly rendered body."""
    if not preserved:
        return new_body
    out = new_body
    for section, content in preserved.items():
        regex = re.compile(
            _SECTION_RE_TEMPLATE.format(section=re.escape(section)),
            re.DOTALL | re.MULTILINE,
        )

        def _sub(match: re.Match[str], _c: str = content) -> str:
            return f"{match.group('heading')}\n{_c}\n\n"

        out = regex.sub(_sub, out, count=1)
    return out


def _looks_like_placeholder(body: str) -> bool:
    """Heuristic: paper-wiki's own placeholders start with ``_Run`` or
    ``_arXiv source`` and live entirely inside a single italic block."""
    stripped = body.strip()
    return stripped.startswith("_") and stripped.endswith("_")


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _coerce_float(value: object, *, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


def _parse_published(raw: object) -> datetime:
    """``published_at`` is required by ``Paper``; default to today UTC."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _extract_abstract(body: str) -> str:
    """Pull the abstract paragraph from a legacy old-format body.

    Heuristic: skip the leading ``# Title`` line and any ``- **Foo**:``
    bullet lines; everything after that until end-of-body (or until
    we hit a ``## `` heading) is the abstract.
    """
    lines = body.splitlines()
    paragraph: list[str] = []
    in_paragraph = False
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("## "):
            break
        if not in_paragraph:
            if not line or line.startswith("#") or line.startswith("- "):
                continue
            in_paragraph = True
        if in_paragraph:
            paragraph.append(line)
    return "\n".join(paragraph).strip()


def _derive_pdf_url(landing_url: str) -> str | None:
    """Best-effort: ``https://arxiv.org/abs/<id>`` → ``.../pdf/<id>``."""
    if "/abs/" in landing_url:
        return landing_url.replace("/abs/", "/pdf/", 1)
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command()
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report only; do not write")] = False,
) -> None:
    """Run the migration and emit a JSON report."""
    try:
        report = asyncio.run(migrate_vault(vault, dry_run=dry_run))
    except PaperWikiError as exc:
        logger.error("migrate_sources.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["MigrateReport", "app", "migrate_source", "migrate_vault"]
