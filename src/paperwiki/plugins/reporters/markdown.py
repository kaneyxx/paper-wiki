"""Markdown reporter — write a digest of recommendations to a file.

The output is a single Markdown file with YAML frontmatter (date,
generator metadata, count, tags) followed by one section per
recommendation. The format is intentionally vault-agnostic: any tool
that accepts standard Markdown will display it cleanly.

For Obsidian-flavored output (wikilinks, additional metadata),
see :mod:`paperwiki.plugins.reporters.obsidian`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiofiles

from paperwiki import __version__
from paperwiki.core.errors import UserError

if TYPE_CHECKING:
    from pathlib import Path

    from paperwiki.core.models import Recommendation, RunContext


def render_markdown_digest(
    recommendations: list[Recommendation],
    ctx: RunContext,
) -> str:
    """Render the list of recommendations as a Markdown digest string.

    Pure function — separates rendering from file I/O so tests can
    snapshot the body without touching disk.
    """
    target_date = ctx.target_date.strftime("%Y-%m-%d")

    parts: list[str] = []
    parts.append(_render_frontmatter(target_date, len(recommendations)))
    parts.append(f"# Paper Digest — {target_date}\n")

    if not recommendations:
        parts.append("_No recommendations matched the pipeline today._\n")
        return "\n".join(parts)

    parts.append(f"{len(recommendations)} recommendations from the configured pipeline.\n")
    parts.append("---\n")

    for index, rec in enumerate(recommendations, start=1):
        parts.append(_render_recommendation(index, rec))
        parts.append("---\n")

    return "\n".join(parts)


def _render_frontmatter(target_date: str, count: int) -> str:
    return (
        "---\n"
        f'date: "{target_date}"\n'
        f'generated_by: "paper-wiki/{__version__}"\n'
        f"recommendations: {count}\n"
        "tags:\n"
        "  - paper-digest\n"
        "  - paper-wiki\n"
        "---\n"
    )


def _render_recommendation(index: int, rec: Recommendation) -> str:
    paper = rec.paper
    score = rec.score

    author_names = ", ".join(a.name for a in paper.authors)
    published = paper.published_at.strftime("%Y-%m-%d")

    source_line = _format_source_line(paper.canonical_id, paper.landing_url)
    score_line = (
        f"**Score**: {score.composite:.2f} "
        f"(relevance {score.relevance:.2f}, novelty {score.novelty:.2f}, "
        f"momentum {score.momentum:.2f}, rigor {score.rigor:.2f})"
    )
    topics_line = ", ".join(rec.matched_topics) if rec.matched_topics else "—"
    citation_line = f"{paper.citation_count}" if paper.citation_count is not None else "—"

    body_lines = [
        f"## {index}. {paper.title}\n",
        f"- **Authors**: {author_names}",
        f"- **Published**: {published}",
        f"- **Source**: {source_line}",
        f"- **Citations**: {citation_line}",
        f"- {score_line}",
        f"- **Matched topics**: {topics_line}",
        "",
        paper.abstract.strip(),
        "",
    ]
    if paper.pdf_url:
        body_lines.insert(4, f"- **PDF**: <{paper.pdf_url}>")
    return "\n".join(body_lines)


def _format_source_line(canonical_id: str, landing_url: str | None) -> str:
    if landing_url:
        return f"[{canonical_id}]({landing_url})"
    return canonical_id


class MarkdownReporter:
    """Persist a digest as ``{output_dir}/{filename_template}``.

    ``archive_retention_days`` (Task 9.30 / v0.3.28) is a recipe-level
    field that documents the user's intended retention window for files
    written under ``output_dir``.  The reporter intentionally does NOT
    GC at emit time (avoids hot-path slowdown and surprise mutation);
    the field is informational metadata that ``paperwiki gc-archive``
    can read in future revisions.  v0.3.28's runner uses ``--max-age-days``
    on the CLI; the recipe-driven retention path is a 9.32 candidate.
    """

    name = "markdown"

    def __init__(
        self,
        output_dir: Path,
        *,
        filename_template: str = "{date}-paper-digest.md",
        archive_retention_days: int | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.filename_template = filename_template
        self.archive_retention_days = archive_retention_days

    async def emit(
        self,
        recs: list[Recommendation],
        ctx: RunContext,
    ) -> None:
        target_date = ctx.target_date.strftime("%Y-%m-%d")
        try:
            filename = self.filename_template.format(date=target_date)
        except KeyError as exc:
            msg = (
                f"filename_template references unknown placeholder {exc.args[0]!r};"
                " supported placeholders: {date}"
            )
            raise UserError(msg) from exc

        self.output_dir.mkdir(parents=True, exist_ok=True)
        rendered = render_markdown_digest(recs, ctx)
        path = self.output_dir / filename
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(rendered)
        ctx.increment("reporter.markdown.written")


__all__ = [
    "MarkdownReporter",
    "render_markdown_digest",
]
