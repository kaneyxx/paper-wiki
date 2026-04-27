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
    *,
    vault_path: Path | None = None,
) -> str:
    """Render an Obsidian-flavored Markdown digest string.

    ``vault_path`` is used to detect already-extracted figures under
    ``Wiki/sources/<id>/images/`` so the daily entry can inline a
    teaser. When ``None`` (e.g., the markdown reporter or a unit test
    that doesn't write a vault), the figure-embed slot is silently
    skipped.
    """
    target_date = ctx.target_date.strftime("%Y-%m-%d")

    parts: list[str] = []
    parts.append(_render_frontmatter(target_date, len(recommendations)))
    parts.append(f"# Paper Digest — {target_date}\n")

    if not recommendations:
        parts.append("_No recommendations matched the pipeline today._\n")
        return "\n".join(parts)

    parts.append(f"{len(recommendations)} recommendations from the configured pipeline.\n")
    parts.append(_render_overview_callout())
    parts.append("---\n")

    for index, rec in enumerate(recommendations, start=1):
        parts.append(_render_recommendation(index, rec, vault_path=vault_path))
        parts.append("---\n")

    return "\n".join(parts)


def _render_overview_callout() -> str:
    """Top-of-digest synthesis slot (SKILL fills this in via paper-wiki:overview-slot)."""
    return "> [!summary] Today's Overview\n> <!-- paper-wiki:overview-slot -->\n"


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


def _render_recommendation(
    index: int,
    rec: Recommendation,
    *,
    vault_path: Path | None = None,
) -> str:
    """Render one recommendation as a section-organized Obsidian block.

    Layout:

    1. ``## N. [[arxiv_<id>|Title]]`` — clicks straight through to the
       rich source stub under ``Wiki/sources/`` instead of a free-form
       title-derived target (which Obsidian would treat as a brand new
       note).
    2. ``> [!info]`` callout for compact metadata.
    3. Inline teaser figure when ``Wiki/sources/<id>/images/`` already
       has files (extract-images was run for this paper).
    4. ``### Abstract`` — abstract under a proper heading so Obsidian's
       outline pane shows it as a collapsible block.
    5. ``### Detailed report`` — HTML-comment marker
       ``<!-- paper-wiki:per-paper-slot:{canonical_id} -->`` that SKILL
       synthesis passes (v0.3.7+) will replace with synthesized content.
    """
    paper = rec.paper
    score = rec.score

    canonical_id = paper.canonical_id
    source_filename = canonical_id.replace(":", "_")
    title_link = f"[[{source_filename}|{paper.title}]]"

    author_names = ", ".join(a.name for a in paper.authors)
    published = paper.published_at.strftime("%Y-%m-%d")
    citations = str(paper.citation_count) if paper.citation_count is not None else "—"
    landing_link = f"[arXiv]({paper.landing_url})" if paper.landing_url else "—"
    pdf_link = f"[PDF](<{paper.pdf_url}>)" if paper.pdf_url else ""
    links_pieces = [landing_link]
    if pdf_link:
        links_pieces.append(pdf_link)
    links_line = " · ".join(links_pieces)
    topic_links = ", ".join(f"[[{t}]]" for t in rec.matched_topics) if rec.matched_topics else "—"
    score_line = (
        f"{score.composite:.2f} (relevance {score.relevance:.2f} · "
        f"novelty {score.novelty:.2f} · momentum {score.momentum:.2f} · "
        f"rigor {score.rigor:.2f})"
    )

    callout = "\n".join(
        [
            "> [!info] Metadata",
            f"> - **Authors**: {author_names}",
            f"> - **Published**: {published} · **Citations**: {citations}",
            f"> - **Score**: {score_line}",
            f"> - **Matched topics**: {topic_links}",
            f"> - **Links**: {links_line}",
        ]
    )

    figure_block = _try_inline_teaser(canonical_id, source_filename, vault_path)

    abstract_block = "### Abstract\n\n" + paper.abstract.strip()

    detailed = f"### Detailed report\n\n<!-- paper-wiki:per-paper-slot:{canonical_id} -->"

    blocks = [
        f"## {index}. {title_link}\n",
        callout,
        "",
    ]
    if figure_block:
        blocks.append(figure_block)
    blocks.extend([abstract_block, "", detailed, ""])
    return "\n".join(blocks)


def _try_inline_teaser(
    canonical_id: str,
    source_filename: str,
    vault_path: Path | None,
) -> str:
    """Embed the first extracted figure as a teaser if one exists on disk."""
    if vault_path is None:
        return ""
    images_dir = vault_path / "Wiki" / "sources" / source_filename / "images"
    if not images_dir.is_dir():
        return ""
    candidates = sorted(images_dir.iterdir())
    image = next(
        (p for p in candidates if p.is_file() and p.suffix.lower() in _FIGURE_EXTS),
        None,
    )
    if image is None:
        return ""
    return f"![[{source_filename}/images/{image.name}|700]]\n"


_FIGURE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}


class ObsidianReporter:
    """Persist an Obsidian-flavored digest under ``vault_path/daily_subdir``.

    When ``wiki_backend`` is true the reporter additionally writes each
    recommendation as a per-paper source file under
    ``vault_path/Wiki/sources/`` via :class:`MarkdownWikiBackend`. This is
    the digest-side half of the wiki ingest loop — concept synthesis is
    still driven by ``/paper-wiki:wiki-ingest`` afterwards.
    """

    name = "obsidian"

    def __init__(
        self,
        vault_path: Path,
        *,
        daily_subdir: str = DAILY_SUBDIR,
        filename_template: str = "{date}-paper-digest.md",
        wiki_backend: bool = False,
    ) -> None:
        self.vault_path = vault_path
        self.daily_subdir = daily_subdir
        self.filename_template = filename_template
        self.wiki_backend = wiki_backend

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
        rendered = render_obsidian_digest(recs, ctx, vault_path=self.vault_path)
        path = target_dir / filename
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(rendered)
        ctx.increment("reporter.obsidian.written")

        if self.wiki_backend:
            # Lazy-import keeps the daily-digest fast path free of the
            # backend's yaml round-trip overhead when the flag is off.
            from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

            backend = MarkdownWikiBackend(vault_path=self.vault_path)
            for rec in recs:
                await backend.upsert_paper(rec)
                ctx.increment("reporter.obsidian.wiki_backend.written")


__all__ = [
    "ObsidianReporter",
    "render_obsidian_digest",
    "title_to_wikilink_target",
]
