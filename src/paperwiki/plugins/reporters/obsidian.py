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
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiofiles
import yaml

from paperwiki._internal.locking import acquire_vault_lock
from paperwiki.config.layout import DAILY_SUBDIR
from paperwiki.core.errors import UserError
from paperwiki.plugins.reporters.markdown import _digest_frontmatter_payload

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
    topic_strength_threshold: float = 0.3,
    now: datetime | None = None,
    callouts: bool = True,
) -> str:
    """Render an Obsidian-flavored Markdown digest string.

    ``vault_path`` is used to detect already-extracted figures under
    ``Wiki/sources/<id>/images/`` so the daily entry can inline a
    teaser. When ``None`` (e.g., the markdown reporter or a unit test
    that doesn't write a vault), the figure-embed slot is silently
    skipped.

    ``topic_strength_threshold`` (Task 9.28 / D-9.28.1) gates the
    ``Matched topics`` callout entries. Topics whose per-topic strength
    (encoded in ``score.notes['topic_strengths']``) falls below this
    threshold are dropped from the rendered wikilinks. Defaults to
    ``0.3`` to match :class:`MarkdownWikiBackend`'s default for
    ``related_concepts`` frontmatter — same gate, two surfaces.
    Backward-compatible: when ``topic_strengths`` is missing (legacy
    data, hand-built fixtures, non-composite scorers), all matched
    topics are retained.

    ``now`` is the timestamp written to the v0.4.x Obsidian Properties
    ``created`` / ``updated`` fields (task 9.161). Defaults to
    ``datetime.now(UTC)``; tests pin it for byte-stable snapshots.
    """
    target_date = ctx.target_date.strftime("%Y-%m-%d")
    when = now if now is not None else datetime.now(UTC)

    parts: list[str] = []
    parts.append(_render_frontmatter(target_date, len(recommendations), when=when))
    parts.append(f"# Paper Digest — {target_date}\n")

    if not recommendations:
        parts.append("_No recommendations matched the pipeline today._\n")
        return "\n".join(parts)

    parts.append(f"{len(recommendations)} recommendations from the configured pipeline.\n")
    parts.append(_render_overview_callout())
    parts.append("---\n")

    for index, rec in enumerate(recommendations, start=1):
        parts.append(
            _render_recommendation(
                index,
                rec,
                vault_path=vault_path,
                topic_strength_threshold=topic_strength_threshold,
                callouts=callouts,
            )
        )
        parts.append("---\n")

    return "\n".join(parts)


def _render_overview_callout() -> str:
    """Top-of-digest synthesis slot (SKILL fills this in via paper-wiki:overview-slot)."""
    return "> [!summary] Today's Overview\n> <!-- paper-wiki:overview-slot -->\n"


def _render_abstract_block(abstract: str, *, callouts: bool) -> str:
    """Render the per-paper abstract block, callout-aware.

    Per task 9.162 / **D-N**, the default is an Obsidian
    ``> [!abstract] Abstract`` callout (lines prefixed ``> ``). When
    ``callouts=False`` the digest falls back to a ``### Abstract``
    heading + plain paragraph so non-Obsidian Markdown viewers stay
    readable.
    """
    if not callouts:
        return f"### Abstract\n\n{abstract}"
    quoted = "\n".join(f"> {line}" if line else ">" for line in abstract.splitlines())
    return f"> [!abstract] Abstract\n{quoted}"


def _render_frontmatter(target_date: str, count: int, *, when: datetime) -> str:
    """Build the Obsidian-flavored digest frontmatter.

    Reuses the shared payload helper from
    :mod:`paperwiki.plugins.reporters.markdown` so both reporters carry
    the v0.4.x Obsidian Properties block (task 9.161 / **D-D**); the
    Obsidian reporter additionally tags the digest with ``"obsidian"``
    so users can filter generated digests in graph view.
    """
    payload = _digest_frontmatter_payload(
        target_date,
        count,
        when=when,
        extra_tags=("obsidian",),
    )
    body = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"---\n{body}---\n"


def _render_recommendation(
    index: int,
    rec: Recommendation,
    *,
    vault_path: Path | None = None,
    topic_strength_threshold: float = 0.3,
    callouts: bool = True,
) -> str:
    """Render one recommendation as a section-organized Obsidian block.

    Layout:

    1. ``## N. [[arxiv_<id>|Title]]`` — clicks straight through to the
       rich source stub under ``Wiki/sources/`` instead of a free-form
       title-derived target (which Obsidian would treat as a brand new
       note).
    2. ``> [!info]`` callout for compact metadata. The
       ``Matched topics`` line is filtered by ``topic_strength_threshold``
       (Task 9.28) so single-keyword leakage from the relevance scorer
       doesn't surface as misleading ``[[concept]]`` wikilinks.
    3. Inline teaser figure when ``Wiki/sources/<id>/images/`` already
       has files (extract-images was run for this paper).
    4. Abstract block (task 9.162 / **D-N**): ``> [!abstract] Abstract``
       Obsidian callout when ``callouts=True`` (default), or a plain
       ``### Abstract`` heading when ``callouts=False`` for non-Obsidian
       Markdown viewers.
    5. ``### Detailed report`` — HTML-comment marker
       ``<!-- paper-wiki:per-paper-slot:{canonical_id} -->`` that SKILL
       synthesis passes (v0.3.7+) will replace with synthesized content.
    """
    # Local import keeps the reporter and backend modules from
    # forming an import cycle at module load time (the reporter only
    # needs the helper at render time).
    from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

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
    filtered_topics = filter_topics_by_strength(
        rec.matched_topics,
        score,
        threshold=topic_strength_threshold,
    )
    topic_links = ", ".join(f"[[{t}]]" for t in filtered_topics) if filtered_topics else "—"
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

    abstract_block = _render_abstract_block(paper.abstract.strip(), callouts=callouts)

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
        wiki_topic_strength_threshold: float = 0.3,
        topic_strength_threshold: float = 0.3,
        callouts: bool = True,
        templater: bool = False,
    ) -> None:
        # ``topic_strength_threshold`` (Task 9.28 / D-9.28.1) gates the
        # digest callout's ``Matched topics`` wikilinks. Default 0.3
        # matches ``wiki_topic_strength_threshold`` so the two surfaces
        # agree out of the box; conservative readers can raise to 0.6
        # to suppress single-keyword leakage entirely. The two fields
        # stay separate (D-9.28.2): one gate per consumer.
        #
        # ``callouts`` (Task 9.162 / **D-N**) controls whether the
        # per-paper Abstract block renders as ``> [!abstract]`` (default,
        # Obsidian-flavored) or as a plain ``### Abstract`` heading
        # (recipe override for plain-Markdown export).
        self.vault_path = vault_path
        self.daily_subdir = daily_subdir
        self.filename_template = filename_template
        self.wiki_backend = wiki_backend
        self.wiki_topic_strength_threshold = wiki_topic_strength_threshold
        self.topic_strength_threshold = topic_strength_threshold
        self.callouts = callouts
        self.templater = templater

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
        rendered = render_obsidian_digest(
            recs,
            ctx,
            vault_path=self.vault_path,
            topic_strength_threshold=self.topic_strength_threshold,
            callouts=self.callouts,
        )
        path = target_dir / filename
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(rendered)
        ctx.increment("reporter.obsidian.written")

        if self.wiki_backend:
            # Lazy-import keeps the daily-digest fast path free of the
            # backend's yaml round-trip overhead when the flag is off.
            from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

            backend = MarkdownWikiBackend(
                vault_path=self.vault_path,
                callouts=self.callouts,
                templater=self.templater,
            )
            async with acquire_vault_lock(self.vault_path):
                for rec in recs:
                    await backend.upsert_paper(
                        rec,
                        topic_strength_threshold=self.wiki_topic_strength_threshold,
                    )
                    ctx.increment("reporter.obsidian.wiki_backend.written")


__all__ = [
    "ObsidianReporter",
    "render_obsidian_digest",
    "title_to_wikilink_target",
]
