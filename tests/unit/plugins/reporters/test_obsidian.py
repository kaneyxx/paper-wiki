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

    def test_per_paper_has_detailed_report_subheading(self) -> None:
        """Each entry has a ``### Detailed report`` subheading."""
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "### Detailed report" in body

    def test_obsidian_reporter_emits_overview_slot_marker(self) -> None:
        """Digest output contains the machine-targetable overview slot marker."""
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "<!-- paper-wiki:overview-slot -->" in body

    def test_obsidian_reporter_emits_per_paper_slot_markers(self) -> None:
        """Each paper section contains a per-paper slot marker with canonical_id."""
        rec = _make_recommendation(canonical_id="arxiv:2506.13063")
        body = render_obsidian_digest([rec], _make_ctx())
        assert "<!-- paper-wiki:per-paper-slot:arxiv:2506.13063 -->" in body

    def test_obsidian_reporter_does_not_emit_legacy_placeholder_prose(self) -> None:
        """Digest must NOT contain prose stubs that mislead users into thinking
        a SKILL hasn't run yet."""
        body = render_obsidian_digest([_make_recommendation()], _make_ctx())
        assert "Run /paper-wiki:" not in body, (
            "digest must not emit 'Run /paper-wiki:' prose; use slot markers instead"
        )
        assert "fill in the cross-paper synthesis here" not in body, (
            "digest must not emit old cross-paper synthesis prose stub"
        )


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


# ---------------------------------------------------------------------------
# Task 9.28 — matched_topics filtering in the digest callout (v0.3.26)
# ---------------------------------------------------------------------------


def _make_recommendation_with_strengths(
    *,
    matched_topics: list[str],
    topic_strengths: dict[str, float],
    canonical_id: str = "arxiv:2506.13063",
    title: str = "Test Paper",
) -> Recommendation:
    """Recommendation whose ScoreBreakdown.notes carries per-topic strengths,
    matching what CompositeScorer emits in production."""
    import json

    rec = _make_recommendation(
        canonical_id=canonical_id, title=title, matched_topics=matched_topics
    )
    rec.score.notes = {"topic_strengths": json.dumps(topic_strengths)}
    return rec


class TestCalloutTopicFiltering:
    """Per Task 9.28 / D-9.28.1: the obsidian reporter must apply the same
    topic_strength_threshold to the digest callout that the wiki backend
    applies to related_concepts frontmatter — so users don't see
    [[biomedical-pathology]] in the callout while the wiki-backend filter
    correctly keeps that source out of the concept's sources list."""

    def test_topic_below_threshold_dropped_from_callout(self) -> None:
        rec = _make_recommendation_with_strengths(
            matched_topics=["strong", "weak"],
            topic_strengths={"strong": 0.8, "weak": 0.1},
        )
        body = render_obsidian_digest([rec], _make_ctx(), topic_strength_threshold=0.5)
        assert "[[strong]]" in body
        assert "[[weak]]" not in body

    def test_default_threshold_keeps_strong_single_keyword_match(self) -> None:
        """D-9.28.1: default threshold = 0.3 keeps single-keyword strength=0.5
        matches (parity with wiki backend default)."""
        rec = _make_recommendation_with_strengths(
            matched_topics=["topic-a"],
            topic_strengths={"topic-a": 0.5},
        )
        body = render_obsidian_digest([rec], _make_ctx())
        assert "[[topic-a]]" in body

    def test_conservative_threshold_drops_single_keyword_leakage(self) -> None:
        """2026-04-28 smoke reproducer: Omni-o3 audio paper trips ONE generic
        biomedical-pathology keyword at strength 0.5; threshold=0.6 drops it,
        validating the conservative knob users opt into."""
        rec = _make_recommendation_with_strengths(
            canonical_id="arxiv:2510.99999",
            title="Omni-o3: Audio-Visual Reasoning",
            matched_topics=[
                "vision-multimodal",
                "biomedical-pathology",
                "agents-reasoning",
            ],
            topic_strengths={
                "vision-multimodal": 0.875,  # 3 hits
                "biomedical-pathology": 0.5,  # 1 generic-keyword hit (the leak)
                "agents-reasoning": 0.75,  # 2 hits
            },
        )
        body = render_obsidian_digest([rec], _make_ctx(), topic_strength_threshold=0.6)
        assert "[[vision-multimodal]]" in body
        assert "[[agents-reasoning]]" in body
        assert "[[biomedical-pathology]]" not in body, (
            "single-keyword leak must be filtered when threshold=0.6"
        )

    def test_legacy_no_topic_strengths_keeps_all(self) -> None:
        """Backward compat: a Recommendation with no notes still renders all
        matched_topics (hand-built fixtures + non-composite scorers preserved)."""
        body = render_obsidian_digest(
            [_make_recommendation()],
            _make_ctx(),
            topic_strength_threshold=0.9,
        )
        assert "[[vlm]]" in body
        assert "[[foundation-model]]" in body

    def test_zero_threshold_disables_filter(self) -> None:
        rec = _make_recommendation_with_strengths(
            matched_topics=["a", "b"],
            topic_strengths={"a": 0.05, "b": 0.5},
        )
        body = render_obsidian_digest([rec], _make_ctx(), topic_strength_threshold=0.0)
        assert "[[a]]" in body
        assert "[[b]]" in body


class TestObsidianReporterTopicStrengthThreshold:
    """ObsidianReporter.__init__ must accept topic_strength_threshold and
    plumb it through emit() -> render_obsidian_digest()."""

    def test_init_accepts_topic_strength_threshold(self) -> None:
        reporter = ObsidianReporter(
            vault_path=Path("/nonexistent/never-written"),
            topic_strength_threshold=0.6,
        )
        assert reporter.topic_strength_threshold == 0.6

    def test_init_default_is_zero_three(self) -> None:
        """D-9.28.1: default = 0.3 (parity with wiki backend)."""
        reporter = ObsidianReporter(vault_path=Path("/nonexistent/never-written"))
        assert reporter.topic_strength_threshold == 0.3

    async def test_emit_propagates_threshold_to_callout(self, tmp_path: Path) -> None:
        """End-to-end: configure threshold via __init__, observe filter on disk."""
        reporter = ObsidianReporter(
            vault_path=tmp_path,
            topic_strength_threshold=0.6,
        )
        rec = _make_recommendation_with_strengths(
            matched_topics=["strong", "weak"],
            topic_strengths={"strong": 0.8, "weak": 0.4},
        )
        await reporter.emit([rec], _make_ctx())

        body = (tmp_path / "Daily" / "2026-04-25-paper-digest.md").read_text(encoding="utf-8")
        assert "[[strong]]" in body
        assert "[[weak]]" not in body
