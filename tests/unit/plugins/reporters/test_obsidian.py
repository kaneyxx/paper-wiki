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
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        # target sanitized from "PRISM2: Unlocking Multi-Modal AI"
        target = "PRISM2_ Unlocking Multi-Modal AI"
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
