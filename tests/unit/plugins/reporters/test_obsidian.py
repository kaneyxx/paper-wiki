"""Unit tests for paperwiki.plugins.reporters.obsidian.ObsidianReporter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from paperwiki.core.errors import UserError
from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.plugins.reporters.obsidian import (
    ObsidianReporter,
    render_obsidian_digest,
    title_to_wikilink_target,
)


def _make_recommendation(
    *,
    canonical_id: str = "arxiv:2506.13063",
    title: str = "PRISM2: Unlocking Multi-Modal AI",
    matched_topics: list[str] | None = None,
) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name="Jane Doe")],
            abstract="A vision-language foundation model for pathology.",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=["cs.CV"],
            landing_url="https://arxiv.org/abs/2506.13063",
            citation_count=42,
        ),
        score=ScoreBreakdown(
            relevance=0.9,
            novelty=0.5,
            momentum=0.8,
            rigor=0.7,
            composite=0.78,
        ),
        matched_topics=(
            matched_topics if matched_topics is not None else ["vlm", "foundation-model"]
        ),
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


# ---------------------------------------------------------------------------
# title_to_wikilink_target
# ---------------------------------------------------------------------------


class TestTitleToWikilinkTarget:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Simple Title", "Simple Title"),
            ("PRISM2: Unlocking AI", "PRISM2_ Unlocking AI"),
            ("Path/With/Slashes", "Path_With_Slashes"),
            ("Has [brackets] and |pipes", "Has _brackets_ and _pipes"),
            ("Has #hash and ?question", "Has _hash and _question"),
            ("trailing colon:", "trailing colon"),
            ("multiple    spaces", "multiple    spaces"),
            ("___leading and trailing___", "leading and trailing"),
        ],
    )
    def test_sanitization_examples(self, raw: str, expected: str) -> None:
        assert title_to_wikilink_target(raw) == expected

    def test_empty_string_returns_empty(self) -> None:
        # Defensive: caller is expected to validate before passing,
        # but we still don't crash.
        assert title_to_wikilink_target("") == ""


# ---------------------------------------------------------------------------
# render_obsidian_digest
# ---------------------------------------------------------------------------


class TestRenderObsidianDigest:
    def test_includes_frontmatter_with_obsidian_tags(self) -> None:
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert body.startswith("---\n")
        # Obsidian-flavored output adds a "obsidian" tag so users can
        # filter generated digests in Graph view.
        assert "obsidian" in body

    def test_paper_title_uses_wikilink_with_display_alias(self) -> None:
        """Title links at the canonical-id source stub, with the display
        alias keeping the original (colon-bearing) title intact."""
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        # Target is the canonical-id-derived source filename, not a
        # sanitized title — that way clicking the wikilink jumps
        # straight into ``Wiki/sources/arxiv_2506.13063.md``.
        target = "arxiv_2506.13063"
        title = "PRISM2: Unlocking Multi-Modal AI"
        assert f"[[{target}|{title}]]" in body

    def test_matched_topics_are_wikilinks(self) -> None:
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "[[vlm]]" in body
        assert "[[foundation-model]]" in body

    def test_no_matched_topics_renders_em_dash(self) -> None:
        rec = _make_recommendation(matched_topics=[])
        body = render_obsidian_digest([rec], _make_ctx())
        assert "**Matched topics**: —" in body

    def test_empty_recommendations_renders_placeholder(self) -> None:
        body = render_obsidian_digest([], _make_ctx())
        assert "_No recommendations matched the pipeline today._" in body

    def test_includes_canonical_id_link(self) -> None:
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "arxiv:2506.13063" in body
        assert "https://arxiv.org/abs/2506.13063" in body

    def test_score_breakdown_is_included(self) -> None:
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "0.78" in body
        assert "relevance" in body

    def test_today_overview_placeholder_at_top(self) -> None:
        """A ``> [!summary] Today's Overview`` callout points at the
        synthesize step (Claude side, separate SKILL invocation)."""
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "Today's Overview" in body
        # Pre-recommendations placeholder lives between the H1 and the
        # first ``## 1.`` entry.
        h1_idx = body.index("# Paper Digest")
        first_entry_idx = body.index("## 1.")
        overview_idx = body.index("Today's Overview")
        assert h1_idx < overview_idx < first_entry_idx

    def test_per_paper_uses_obsidian_info_callout(self) -> None:
        """Metadata block is a single Obsidian ``> [!info]`` callout, not a
        bare bullet list — much more compact in preview."""
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "> [!info]" in body

    def test_per_paper_links_to_wiki_source_stub(self) -> None:
        """Title wikilink points at ``Wiki/sources/arxiv_<id>`` (the rich
        per-paper note) rather than a free-form title-based target."""
        rec = _make_recommendation(canonical_id="arxiv:2506.13063")
        body = render_obsidian_digest([rec], _make_ctx())
        assert "[[arxiv_2506.13063" in body, (
            "title link must reference the Wiki/sources stub, not just the title"
        )

    def test_per_paper_has_abstract_subheading(self) -> None:
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        # Each entry uses ``### Abstract`` so Obsidian's outline pane
        # shows abstracts as collapsible blocks.
        assert "### Abstract" in body

    def test_per_paper_has_detailed_report_wikilink(self) -> None:
        """Each entry suggests opening the deep-analysis note."""
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        # Pointer at the analyze workflow.
        assert "/paperwiki:analyze" in body or "Detailed report" in body


# ---------------------------------------------------------------------------
# ObsidianReporter (file output)
# ---------------------------------------------------------------------------


class TestObsidianReporter:
    async def test_emit_writes_file_under_vault_daily_subdir(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        reporter = ObsidianReporter(vault_path=vault, daily_subdir="10_Daily")

        ctx = _make_ctx()
        await reporter.emit([_make_recommendation()], ctx)

        expected = vault / "10_Daily" / "2026-04-25-paper-digest.md"
        assert expected.exists()
        text = expected.read_text(encoding="utf-8")
        assert "[[" in text  # contains at least one wikilink
        assert ctx.counters["reporter.obsidian.written"] == 1

    async def test_default_daily_subdir(self, tmp_path: Path) -> None:
        reporter = ObsidianReporter(vault_path=tmp_path)
        await reporter.emit([_make_recommendation()], _make_ctx())
        # Default subdir is "Daily" — friendly, no Johnny.Decimal prefix.
        assert (tmp_path / "Daily" / "2026-04-25-paper-digest.md").exists()

    async def test_custom_filename_template(self, tmp_path: Path) -> None:
        reporter = ObsidianReporter(
            vault_path=tmp_path,
            daily_subdir="dailies",
            filename_template="{date}_obsidian.md",
        )
        await reporter.emit([_make_recommendation()], _make_ctx())
        assert (tmp_path / "dailies" / "2026-04-25_obsidian.md").exists()

    async def test_invalid_filename_template_raises_user_error(self, tmp_path: Path) -> None:
        reporter = ObsidianReporter(
            vault_path=tmp_path,
            filename_template="{notakey}.md",
        )
        with pytest.raises(UserError, match="filename_template"):
            await reporter.emit([_make_recommendation()], _make_ctx())

    async def test_reporter_satisfies_protocol(self, tmp_path: Path) -> None:
        from paperwiki.core.protocols import Reporter

        reporter = ObsidianReporter(vault_path=tmp_path)
        assert isinstance(reporter, Reporter)

    async def test_wiki_backend_default_does_not_create_sources(self, tmp_path: Path) -> None:
        """Without ``wiki_backend=True`` the reporter must not touch ``Wiki/``."""
        reporter = ObsidianReporter(vault_path=tmp_path)
        await reporter.emit([_make_recommendation()], _make_ctx())
        assert not (tmp_path / "Wiki").exists()

    async def test_wiki_backend_true_writes_per_paper_source(self, tmp_path: Path) -> None:
        """With ``wiki_backend=True`` each rec lands as ``Wiki/sources/<id>.md``."""
        reporter = ObsidianReporter(vault_path=tmp_path, wiki_backend=True)
        ctx = _make_ctx()
        await reporter.emit([_make_recommendation()], ctx)

        expected = tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md"
        assert expected.exists()
        body = expected.read_text(encoding="utf-8")
        assert "canonical_id: arxiv:2506.13063" in body
        assert "PRISM2" in body
        assert ctx.counters["reporter.obsidian.wiki_backend.written"] == 1

    async def test_inline_teaser_figure_embed_when_extracted(self, tmp_path: Path) -> None:
        """If ``Wiki/sources/<id>/images/`` already has figures (via
        extract-images), the daily entry inlines the first one as a
        teaser. Otherwise the section is silently skipped — no clutter."""
        images_dir = tmp_path / "Wiki" / "sources" / "arxiv_2506.13063" / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "Figure_1.pdf").write_bytes(b"%PDF-1.4 stub\n")

        reporter = ObsidianReporter(vault_path=tmp_path)
        ctx = _make_ctx()
        await reporter.emit([_make_recommendation()], ctx)

        body = (tmp_path / "Daily" / "2026-04-25-paper-digest.md").read_text(encoding="utf-8")
        # Embed uses Obsidian wikilink-with-width syntax pointing at the
        # cached figure.
        assert "![[arxiv_2506.13063/images/Figure_1.pdf" in body

    async def test_no_inline_figure_when_images_dir_missing(self, tmp_path: Path) -> None:
        """No clutter: if there are no extracted figures, no embed."""
        reporter = ObsidianReporter(vault_path=tmp_path)
        await reporter.emit([_make_recommendation()], _make_ctx())

        body = (tmp_path / "Daily" / "2026-04-25-paper-digest.md").read_text(encoding="utf-8")
        assert "![[arxiv_2506.13063/images" not in body

    async def test_wiki_backend_true_writes_one_file_per_recommendation(
        self, tmp_path: Path
    ) -> None:
        reporter = ObsidianReporter(vault_path=tmp_path, wiki_backend=True)
        recs = [
            _make_recommendation(canonical_id="arxiv:1111.1111", title="Alpha"),
            _make_recommendation(canonical_id="arxiv:2222.2222", title="Beta"),
            _make_recommendation(canonical_id="arxiv:3333.3333", title="Gamma"),
        ]
        ctx = _make_ctx()
        await reporter.emit(recs, ctx)

        sources_dir = tmp_path / "Wiki" / "sources"
        files = sorted(p.name for p in sources_dir.glob("*.md"))
        assert files == [
            "arxiv_1111.1111.md",
            "arxiv_2222.2222.md",
            "arxiv_3333.3333.md",
        ]
        assert ctx.counters["reporter.obsidian.wiki_backend.written"] == 3
