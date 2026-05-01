"""Unit tests for paperwiki.plugins.reporters.markdown.MarkdownReporter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)
from paperwiki.plugins.reporters.markdown import MarkdownReporter, render_markdown_digest


def _make_recommendation(
    *,
    canonical_id: str = "arxiv:2506.13063",
    title: str = "PRISM2: Unlocking Multi-Modal AI",
    authors: list[str] | None = None,
    abstract: str = "A vision-language foundation model.",
    landing_url: str | None = "https://arxiv.org/abs/2506.13063",
    pdf_url: str | None = "https://arxiv.org/pdf/2506.13063",
    citation_count: int | None = 42,
    composite: float = 0.87,
    relevance: float = 0.95,
    novelty: float = 0.50,
    momentum: float = 0.84,
    rigor: float = 0.88,
    matched_topics: list[str] | None = None,
) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name=n) for n in (authors or ["Jane Doe", "John Roe"])],
            abstract=abstract,
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=["cs.CV", "cs.LG"],
            landing_url=landing_url,
            pdf_url=pdf_url,
            citation_count=citation_count,
        ),
        score=ScoreBreakdown(
            relevance=relevance,
            novelty=novelty,
            momentum=momentum,
            rigor=rigor,
            composite=composite,
        ),
        matched_topics=matched_topics or ["vlm", "foundation-model"],
    )


def _make_ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})


# ---------------------------------------------------------------------------
# render_markdown_digest
# ---------------------------------------------------------------------------


class TestRenderMarkdownDigest:
    def test_includes_frontmatter(self) -> None:
        import yaml

        body = render_markdown_digest([_make_recommendation()], _make_ctx())
        assert body.startswith("---\n")
        end = body.index("\n---\n", 4)
        fm = yaml.safe_load(body[4:end])
        assert isinstance(fm, dict)
        assert fm["date"] == "2026-04-25"
        assert "paper-wiki/" in str(fm["generated_by"])
        assert fm["recommendations"] == 1

    def test_includes_top_level_heading_with_target_date(self) -> None:
        body = render_markdown_digest([_make_recommendation()], _make_ctx())
        assert "# Paper Digest — 2026-04-25" in body

    def test_renders_each_recommendation(self) -> None:
        recs = [
            _make_recommendation(canonical_id="arxiv:0001.0001", title="First Paper"),
            _make_recommendation(canonical_id="arxiv:0002.0002", title="Second Paper"),
        ]
        body = render_markdown_digest(recs, _make_ctx())
        assert "## 1. First Paper" in body
        assert "## 2. Second Paper" in body
        assert "recommendations: 2" in body

    def test_includes_authors(self) -> None:
        body = render_markdown_digest([_make_recommendation()], _make_ctx())
        assert "Jane Doe" in body
        assert "John Roe" in body

    def test_includes_canonical_id_and_url(self) -> None:
        body = render_markdown_digest([_make_recommendation()], _make_ctx())
        assert "arxiv:2506.13063" in body
        assert "https://arxiv.org/abs/2506.13063" in body

    def test_includes_score_breakdown(self) -> None:
        body = render_markdown_digest([_make_recommendation()], _make_ctx())
        assert "0.87" in body  # composite
        assert "relevance" in body
        assert "novelty" in body

    def test_includes_matched_topics(self) -> None:
        body = render_markdown_digest([_make_recommendation()], _make_ctx())
        assert "vlm" in body
        assert "foundation-model" in body

    def test_includes_abstract(self) -> None:
        body = render_markdown_digest([_make_recommendation()], _make_ctx())
        assert "A vision-language foundation model." in body

    def test_empty_recommendations(self) -> None:
        body = render_markdown_digest([], _make_ctx())
        assert "recommendations: 0" in body
        assert "_No recommendations" in body

    def test_paper_without_landing_url_falls_back_to_canonical_id(self) -> None:
        rec = _make_recommendation(landing_url=None, pdf_url=None)
        body = render_markdown_digest([rec], _make_ctx())
        # Source line should still mention the canonical id even without a URL.
        assert "arxiv:2506.13063" in body

    def test_recommendation_without_citation_count(self) -> None:
        rec = _make_recommendation(citation_count=None)
        body = render_markdown_digest([rec], _make_ctx())
        assert "Citations" not in body or "—" in body  # gracefully degrade


class TestMarkdownDigestObsidianProperties:
    """Task 9.161 / **D-D**: digest frontmatter must carry the canonical
    six-field Obsidian Properties block alongside the existing
    ``date`` / ``generated_by`` / ``recommendations`` keys.
    """

    def _frontmatter(self, body: str) -> dict[str, object]:
        import yaml

        assert body.startswith("---\n")
        end = body.index("\n---\n", 4)
        parsed = yaml.safe_load(body[4:end])
        assert isinstance(parsed, dict)
        return parsed

    def test_frontmatter_includes_all_six_properties_fields(self) -> None:
        body = render_markdown_digest(
            [_make_recommendation()],
            _make_ctx(),
            now=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        )
        fm = self._frontmatter(body)
        assert "tags" in fm
        assert "aliases" in fm
        assert "status" in fm
        assert "cssclasses" in fm
        assert "created" in fm
        assert "updated" in fm

    def test_property_field_yaml_types(self) -> None:
        body = render_markdown_digest(
            [_make_recommendation()],
            _make_ctx(),
            now=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        )
        fm = self._frontmatter(body)
        assert isinstance(fm["tags"], list)
        assert isinstance(fm["aliases"], list)
        assert isinstance(fm["status"], str)
        assert isinstance(fm["cssclasses"], list)
        assert isinstance(fm["created"], str)
        assert isinstance(fm["updated"], str)

    def test_created_and_updated_are_iso8601_with_timezone(self) -> None:
        body = render_markdown_digest(
            [_make_recommendation()],
            _make_ctx(),
            now=datetime(2026, 5, 1, 12, 30, 45, tzinfo=UTC),
        )
        fm = self._frontmatter(body)
        assert fm["created"] == "2026-05-01T12:30:45+00:00"
        assert fm["updated"] == "2026-05-01T12:30:45+00:00"

    def test_existing_legacy_keys_preserved(self) -> None:
        """No regression on ``date`` / ``generated_by`` / ``recommendations``."""
        body = render_markdown_digest(
            [_make_recommendation()],
            _make_ctx(),
            now=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        )
        fm = self._frontmatter(body)
        assert fm["date"] == "2026-04-25"
        assert "paper-wiki/" in str(fm["generated_by"])
        assert fm["recommendations"] == 1


# ---------------------------------------------------------------------------
# MarkdownReporter (file output)
# ---------------------------------------------------------------------------


class TestMarkdownReporter:
    async def test_emit_writes_file_to_output_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "digests"
        reporter = MarkdownReporter(output_dir=out)

        ctx = _make_ctx()
        await reporter.emit([_make_recommendation()], ctx)

        expected = out / "2026-04-25-paper-digest.md"
        assert expected.exists()
        text = expected.read_text(encoding="utf-8")
        assert "# Paper Digest — 2026-04-25" in text
        assert ctx.counters["reporter.markdown.written"] == 1

    async def test_emit_creates_parent_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "deeply" / "nested" / "out"
        reporter = MarkdownReporter(output_dir=out)
        await reporter.emit([_make_recommendation()], _make_ctx())
        assert out.is_dir()

    async def test_filename_template_substitutes_date(self, tmp_path: Path) -> None:
        reporter = MarkdownReporter(
            output_dir=tmp_path,
            filename_template="digest_{date}.md",
        )
        await reporter.emit([_make_recommendation()], _make_ctx())
        assert (tmp_path / "digest_2026-04-25.md").exists()

    async def test_emit_overwrites_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "2026-04-25-paper-digest.md"
        path.write_text("old content", encoding="utf-8")

        reporter = MarkdownReporter(output_dir=tmp_path)
        await reporter.emit([_make_recommendation()], _make_ctx())

        assert "old content" not in path.read_text(encoding="utf-8")

    async def test_invalid_filename_template_raises_user_error(self, tmp_path: Path) -> None:
        from paperwiki.core.errors import UserError

        reporter = MarkdownReporter(
            output_dir=tmp_path,
            filename_template="digest_{notakey}.md",
        )
        with pytest.raises(UserError, match="filename_template"):
            await reporter.emit([_make_recommendation()], _make_ctx())

    async def test_reporter_satisfies_protocol(self, tmp_path: Path) -> None:
        from paperwiki.core.protocols import Reporter

        reporter = MarkdownReporter(output_dir=tmp_path)
        assert isinstance(reporter, Reporter)


class TestArchiveRetentionDays:
    """Task 9.30 / v0.3.28: ``archive_retention_days`` accepted as recipe
    metadata. The field is documentation-only at v0.3.28; the runner
    ``paperwiki gc-archive`` reads it from the recipe in a future
    revision. Reporter emit-time behavior is unchanged."""

    def test_default_is_none(self, tmp_path: Path) -> None:
        reporter = MarkdownReporter(output_dir=tmp_path)
        assert reporter.archive_retention_days is None

    def test_accepts_explicit_value(self, tmp_path: Path) -> None:
        reporter = MarkdownReporter(output_dir=tmp_path, archive_retention_days=365)
        assert reporter.archive_retention_days == 365

    async def test_emit_does_not_gc_at_write_time(self, tmp_path: Path) -> None:
        """Emit-time behavior is unchanged regardless of retention setting:
        the reporter never deletes files when writing. GC is a separate
        explicit user action via paperwiki gc-archive."""
        old = tmp_path / "2020-01-01-paper-digest.md"
        old.write_text("# old\n", encoding="utf-8")

        reporter = MarkdownReporter(output_dir=tmp_path, archive_retention_days=1)
        await reporter.emit([_make_recommendation()], _make_ctx())

        assert old.is_file()
