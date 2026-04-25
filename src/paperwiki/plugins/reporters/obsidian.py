"""Obsidian-flavored reporter — Markdown digest with wikilinks.

Same shape as :class:`MarkdownReporter` but tailored for Obsidian
vaults:

* the paper title is rendered as ``[[target|display]]`` so a user can
  click through to a stub note (or have Obsidian create one),
* matched topics are wikilinks (``[[topic]]``) so Obsidian's graph
  view connects digest entries to topic notes the user maintains,
* the file is written under ``{vault_path}/{daily_subdir}/`` instead of
  a free-form output directory.

The wikilink *target* is a sanitized version of the title with
filename-unsafe characters replaced by underscores; the *display* keeps
the original title intact via the ``|`` alias form so the digest reads
naturally.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import aiofiles

from paperwiki import __version__
from paperwiki.config.layout import DAILY_SUBDIR
from paperwiki.core.errors import UserError

if TYPE_CHECKING:
    from pathlib import Path

    from paperwiki.core.models import Recommendation, RunContext


# Characters that break Obsidian wikilinks or filenames on common OSes.
# We replace them with underscores and collapse runs.
_UNSAFE_TARGET_PATTERN = re.compile(r'[\\/:#?*|<>"\[\]^]+')
_UNDERSCORE_RUN = re.compile(r"_+")


def title_to_wikilink_target(title: str) -> str:
    """Convert a paper title to a safe Obsidian wikilink target.

    Replaces filename-unsafe characters with underscores, collapses
    runs, and trims leading/trailing underscores. Spaces are preserved
    because Obsidian supports them in note names.
    """
    if not title:
        return ""
    target = _UNSAFE_TARGET_PATTERN.sub("_", title)
    target = _UNDERSCORE_RUN.sub("_", target)
    return target.strip("_")


def render_obsidian_digest(
    recommendations: list[Recommendation],
    ctx: RunContext,
) -> str:
    """Render an Obsidian-flavored Markdown digest string."""
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
        "  - obsidian\n"
        "---\n"
    )


def _render_recommendation(index: int, rec: Recommendation) -> str:
    paper = rec.paper
    score = rec.score

    target = title_to_wikilink_target(paper.title)
    title_link = f"[[{target}|{paper.title}]]"

    author_names = ", ".join(a.name for a in paper.authors)
    published = paper.published_at.strftime("%Y-%m-%d")

    source_line = (
        f"[{paper.canonical_id}]({paper.landing_url})" if paper.landing_url else paper.canonical_id
    )
    score_line = (
        f"**Score**: {score.composite:.2f} "
        f"(relevance {score.relevance:.2f}, novelty {score.novelty:.2f}, "
        f"momentum {score.momentum:.2f}, rigor {score.rigor:.2f})"
    )
    topic_links = ", ".join(f"[[{t}]]" for t in rec.matched_topics) if rec.matched_topics else "—"
    citation_line = f"{paper.citation_count}" if paper.citation_count is not None else "—"

    body_lines = [
        f"## {index}. {title_link}\n",
        f"- **Authors**: {author_names}",
        f"- **Published**: {published}",
        f"- **Source**: {source_line}",
        f"- **Citations**: {citation_line}",
        f"- {score_line}",
        f"- **Matched topics**: {topic_links}",
        "",
        paper.abstract.strip(),
        "",
    ]
    if paper.pdf_url:
        body_lines.insert(4, f"- **PDF**: <{paper.pdf_url}>")
    return "\n".join(body_lines)


class ObsidianReporter:
    """Persist an Obsidian-flavored digest under ``vault_path/daily_subdir``."""

    name = "obsidian"

    def __init__(
        self,
        vault_path: Path,
        *,
        daily_subdir: str = DAILY_SUBDIR,
        filename_template: str = "{date}-paper-digest.md",
    ) -> None:
        self.vault_path = vault_path
        self.daily_subdir = daily_subdir
        self.filename_template = filename_template

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

        target_dir = self.vault_path / self.daily_subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        rendered = render_obsidian_digest(recs, ctx)
        path = target_dir / filename
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(rendered)
        ctx.increment("reporter.obsidian.written")


__all__ = [
    "ObsidianReporter",
    "render_obsidian_digest",
    "title_to_wikilink_target",
]
