"""Unit tests for paperwiki.plugins.backends.markdown_wiki.MarkdownWikiBackend.

The backend is the file-IO half of the wiki story; SKILLs (driven by
Claude) supply the synthesized prose. Tests exercise file shape,
frontmatter round-trip, idempotence, and discovery — they do not
assert anything about prose content.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    ScoreBreakdown,
)
from paperwiki.plugins.backends.markdown_wiki import (
    ConceptSummary,
    MarkdownWikiBackend,
    SourceSummary,
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
            authors=[Author(name="Jane Doe"), Author(name="John Roe")],
            abstract="A vision-language foundation model for pathology.",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=["cs.CV", "cs.LG"],
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
            matched_topics
            if matched_topics is not None
            else ["vision-language", "foundation-model"]
        ),
    )


def _read_frontmatter(path: Path) -> dict[str, object]:
    """Pull the YAML frontmatter block from a markdown file."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), text[:40]
    end = text.find("\n---\n", 4)
    assert end > 0
    block = text[4:end]
    data = yaml.safe_load(block)
    assert isinstance(data, dict)
    return data


# ---------------------------------------------------------------------------
# upsert_paper / source files
# ---------------------------------------------------------------------------


class TestUpsertSource:
    async def test_writes_file_under_sources_dir(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation()

        await backend.upsert_paper(rec)

        path = tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md"
        assert path.is_file()

    async def test_canonical_id_with_colon_safely_filenamed(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation(canonical_id="s2:abc-def")

        await backend.upsert_paper(rec)

        path = tmp_path / "Wiki" / "sources" / "s2_abc-def.md"
        assert path.is_file()

    async def test_source_frontmatter_round_trip(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation()

        await backend.upsert_paper(rec)

        fm = _read_frontmatter(tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md")
        assert fm["canonical_id"] == "arxiv:2506.13063"
        assert fm["title"] == "PRISM2: Unlocking Multi-Modal AI"
        assert fm["status"] == "draft"
        assert fm["confidence"] == 0.78  # composite as initial confidence
        # Per task 9.161, ``tags`` is normalized to lowercased + nested-tag
        # form so Obsidian's tag pane groups arXiv categories under their
        # area (``cs/cv``, ``cs/lg``).
        assert fm["tags"] == ["cs/cv", "cs/lg"]
        # matched_topics flow into related_concepts as starter wikilinks.
        related = fm["related_concepts"]
        assert isinstance(related, list)
        assert any("vision-language" in s for s in related)

    async def test_source_frontmatter_carries_obsidian_properties_block(
        self, tmp_path: Path
    ) -> None:
        """Per task 9.161 / **D-D**: every per-paper file carries the canonical
        six-field Properties block alongside the legacy ``canonical_id`` /
        ``confidence`` / ``score_breakdown`` keys."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation())

        fm = _read_frontmatter(tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md")
        for key in ("tags", "aliases", "status", "cssclasses", "created", "updated"):
            assert key in fm, f"missing Properties field: {key}"
        # Type assertions per acceptance criteria.
        assert isinstance(fm["tags"], list)
        assert isinstance(fm["aliases"], list)
        assert isinstance(fm["status"], str)
        assert isinstance(fm["cssclasses"], list)
        assert isinstance(fm["created"], str)
        assert isinstance(fm["updated"], str)
        # ISO-8601 with timezone offset (round-trip via ``yaml.safe_load``
        # may also produce a ``datetime`` if the string is unquoted; we
        # assert the string form by re-reading the raw file).
        text = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        assert "+00:00" in text  # UTC offset is preserved verbatim

    async def test_source_frontmatter_includes_publication_metadata(self, tmp_path: Path) -> None:
        """Frontmatter must carry enough metadata for downstream tools (lint,
        compile, search) to surface the paper without re-reading the body."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation())

        fm = _read_frontmatter(tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md")
        assert fm["published_at"] == "2026-04-20"
        assert fm["landing_url"] == "https://arxiv.org/abs/2506.13063"
        assert fm["citation_count"] == 42
        # Domain inferred from arxiv categories.
        assert fm["domain"]  # non-empty heuristic, e.g. "Computer Vision"
        # Score breakdown is present so users can see why the paper ranked.
        score = fm["score_breakdown"]
        assert isinstance(score, dict)
        assert score["composite"] == 0.78
        assert score["relevance"] == 0.9

    async def test_source_body_uses_structured_sections(self, tmp_path: Path) -> None:
        """Body must be section-organized so Obsidian's outline pane is useful
        and downstream tools can target individual sections."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation())

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        # Drop the frontmatter for body assertions.
        _, _, body = body.partition("---\n")
        _, _, body = body.partition("---\n")

        for section in (
            "## Core Information",
            # Per task 9.162 / **D-N**, the Abstract uses an Obsidian
            # ``> [!abstract] Abstract`` callout by default; the title
            # slot acts as the section heading for outline navigation.
            "> [!abstract] Abstract",
            "## Key Takeaways",
            "## Figures",
            "## Notes",
        ):
            assert section in body, f"missing section: {section!r}"

    async def test_source_body_has_takeaways_and_figures_placeholders(self, tmp_path: Path) -> None:
        """Empty sections must point users at the SKILLs that fill them."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation())

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        # Key Takeaways block points at wiki-ingest.
        assert "/paper-wiki:wiki-ingest" in body
        # Figures block points at the (forthcoming) extract-images workflow.
        body_lower = body.lower()
        assert "extract" in body_lower
        assert "image" in body_lower

    async def test_source_core_information_section_lists_links(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation()
        await backend.upsert_paper(rec)

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        # Core Information renders authors, published date, both links, and citations.
        assert "Jane Doe" in body
        assert "2026-04-20" in body
        assert "https://arxiv.org/abs/2506.13063" in body
        assert "42" in body  # citation count

    async def test_topic_strength_threshold_filters_matched_topics(self, tmp_path: Path) -> None:
        """Topics below the threshold must not appear in related_concepts frontmatter."""
        import json

        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation(
            matched_topics=["strong-topic", "weak-topic"],
        )
        # Inject per-topic strengths into notes
        rec.score.notes = {
            "topic_strengths": json.dumps({"strong-topic": 0.8, "weak-topic": 0.1}),
        }

        await backend.upsert_paper(rec, topic_strength_threshold=0.5)

        fm = _read_frontmatter(tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md")
        related = fm["related_concepts"]
        assert isinstance(related, list)
        assert any("strong-topic" in s for s in related)
        assert not any("weak-topic" in s for s in related)

    async def test_zero_threshold_keeps_all_matched_topics(self, tmp_path: Path) -> None:
        """Default threshold of 0.0 must keep all matched topics regardless of strength."""
        import json

        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation(matched_topics=["strong-topic", "weak-topic"])
        rec.score.notes = {
            "topic_strengths": json.dumps({"strong-topic": 0.8, "weak-topic": 0.05}),
        }

        await backend.upsert_paper(rec, topic_strength_threshold=0.0)

        fm = _read_frontmatter(tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md")
        related = fm["related_concepts"]
        assert any("strong-topic" in s for s in related)
        assert any("weak-topic" in s for s in related)

    async def test_missing_topic_strengths_falls_back_to_all_topics(self, tmp_path: Path) -> None:
        """When notes has no topic_strengths key, all matched_topics are kept (backward compat)."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation(matched_topics=["topic-a", "topic-b"])
        # No notes at all — old-style Recommendation without topic_strengths
        rec.score.notes = {}

        await backend.upsert_paper(rec, topic_strength_threshold=0.9)

        fm = _read_frontmatter(tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md")
        related = fm["related_concepts"]
        assert any("topic-a" in s for s in related)
        assert any("topic-b" in s for s in related)

    async def test_upsert_is_idempotent(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        rec = _make_recommendation()

        await backend.upsert_paper(rec)
        first = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text()

        await backend.upsert_paper(rec)
        second = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text()

        # Files should remain valid; both have the same canonical_id.
        assert "arxiv:2506.13063" in first
        assert "arxiv:2506.13063" in second
        # Idempotent in the sense that re-upsert is allowed and content stays
        # well-formed (last_synthesized may change).
        assert first.startswith("---\n")
        assert second.startswith("---\n")


# ---------------------------------------------------------------------------
# filter_topics_by_strength helper (Task 9.28 / D-9.28.1, D-9.28.2)
# ---------------------------------------------------------------------------


class TestFilterTopicsByStrength:
    """Module-level helper extracted from upsert_paper for v0.3.26.

    Reporter needs to import the same gating logic, so it must be a
    module-level function rather than living inside upsert_paper.
    """

    def test_helper_is_importable_at_module_level(self) -> None:
        from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

        assert callable(filter_topics_by_strength)

    def test_below_threshold_dropped(self) -> None:
        import json

        from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

        score = ScoreBreakdown(
            relevance=0.5,
            novelty=0.5,
            momentum=0.5,
            rigor=0.5,
            composite=0.5,
            notes={"topic_strengths": json.dumps({"strong": 0.8, "weak": 0.1})},
        )
        out = filter_topics_by_strength(["strong", "weak"], score, threshold=0.5)
        assert out == ["strong"]

    def test_above_threshold_kept(self) -> None:
        import json

        from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

        score = ScoreBreakdown(
            relevance=0.5,
            novelty=0.5,
            momentum=0.5,
            rigor=0.5,
            composite=0.5,
            notes={"topic_strengths": json.dumps({"a": 0.7, "b": 0.6})},
        )
        out = filter_topics_by_strength(["a", "b"], score, threshold=0.5)
        assert out == ["a", "b"]

    def test_zero_threshold_returns_all(self) -> None:
        import json

        from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

        score = ScoreBreakdown(
            relevance=0.0,
            novelty=0.0,
            momentum=0.0,
            rigor=0.0,
            composite=0.0,
            notes={"topic_strengths": json.dumps({"a": 0.05, "b": 0.5})},
        )
        out = filter_topics_by_strength(["a", "b"], score, threshold=0.0)
        assert out == ["a", "b"]

    def test_missing_topic_strengths_returns_all(self) -> None:
        """Backward compat: legacy Recommendation without notes preserved."""
        from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

        score = ScoreBreakdown(relevance=0.5, novelty=0.5, momentum=0.5, rigor=0.5, composite=0.5)
        out = filter_topics_by_strength(["a", "b"], score, threshold=0.9)
        assert out == ["a", "b"]

    def test_malformed_topic_strengths_returns_all(self) -> None:
        """Defensive: corrupt notes payload doesn't silently drop wikilinks."""
        from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

        score = ScoreBreakdown(
            relevance=0.5,
            novelty=0.5,
            momentum=0.5,
            rigor=0.5,
            composite=0.5,
            notes={"topic_strengths": "not valid json"},
        )
        out = filter_topics_by_strength(["a", "b"], score, threshold=0.9)
        assert out == ["a", "b"]

    def test_topics_missing_from_strengths_dict_treated_as_zero(self) -> None:
        """A topic present in matched_topics but absent from the strengths
        dict is treated as strength 0.0 — so any positive threshold drops it."""
        import json

        from paperwiki.plugins.backends.markdown_wiki import filter_topics_by_strength

        score = ScoreBreakdown(
            relevance=0.5,
            novelty=0.5,
            momentum=0.5,
            rigor=0.5,
            composite=0.5,
            notes={"topic_strengths": json.dumps({"known": 0.8})},
        )
        out = filter_topics_by_strength(["known", "unknown"], score, threshold=0.5)
        assert out == ["known"]


# ---------------------------------------------------------------------------
# upsert_concept / concept files
# ---------------------------------------------------------------------------


class TestUpsertConcept:
    async def test_writes_file_under_concepts_dir(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        await backend.upsert_concept(
            name="Vision-Language Foundation Models",
            body="Synthesis prose here.",
            sources=["arxiv:2506.13063"],
        )

        path = tmp_path / "Wiki" / "concepts" / "Vision-Language_Foundation_Models.md"
        assert path.is_file()

    async def test_concept_frontmatter(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        await backend.upsert_concept(
            name="Multimodal Reasoning",
            body="...",
            sources=["arxiv:2506.13063", "arxiv:0001.0001"],
            related_concepts=["[[Vision-Language Foundation Models]]"],
            confidence=0.7,
            status="reviewed",
        )

        fm = _read_frontmatter(tmp_path / "Wiki" / "concepts" / "Multimodal_Reasoning.md")
        assert fm["title"] == "Multimodal Reasoning"
        assert fm["status"] == "reviewed"
        assert fm["confidence"] == 0.7
        assert fm["sources"] == ["arxiv:2506.13063", "arxiv:0001.0001"]
        assert fm["related_concepts"] == ["[[Vision-Language Foundation Models]]"]

    async def test_concept_body_is_preserved_below_frontmatter(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        await backend.upsert_concept(
            name="Foo",
            body="Line 1\n\nLine 2 with **bold**.",
            sources=["arxiv:0001.0001"],
        )

        text = (tmp_path / "Wiki" / "concepts" / "Foo.md").read_text(encoding="utf-8")
        assert "Line 1\n\nLine 2 with **bold**." in text

    async def test_filename_sanitization(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        await backend.upsert_concept(
            name="Path/With:Bad?Chars",
            body="ok",
            sources=["arxiv:1"],
        )

        # Slashes, colons, question marks all collapse to underscores.
        candidates = list((tmp_path / "Wiki" / "concepts").iterdir())
        assert len(candidates) == 1
        assert "/" not in candidates[0].name
        assert ":" not in candidates[0].name
        assert "?" not in candidates[0].name

    async def test_empty_concept_name_rejected(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        with pytest.raises(ValueError, match="non-empty"):
            await backend.upsert_concept(
                name="",
                body="...",
                sources=["arxiv:1"],
            )

    async def test_confidence_out_of_range_rejected(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        with pytest.raises(ValueError, match="confidence"):
            await backend.upsert_concept(
                name="X",
                body="...",
                sources=["arxiv:1"],
                confidence=1.5,
            )

    async def test_abstract_section_uses_callout_by_default(self, tmp_path: Path) -> None:
        """Per task 9.162 / **D-N**: per-paper source body wraps the abstract
        in an Obsidian ``> [!abstract] Abstract`` callout by default."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation())

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        # Drop frontmatter for body assertions.
        _, _, body = body.partition("---\n")
        _, _, body = body.partition("---\n")
        assert "> [!abstract] Abstract" in body
        # Plain ``## Abstract`` heading must NOT appear when callouts=True.
        assert "## Abstract" not in body

    async def test_callouts_false_uses_plain_heading(self, tmp_path: Path) -> None:
        """Setting ``callouts=False`` falls back to the legacy ``## Abstract``
        heading style for plain-Markdown export."""
        backend = MarkdownWikiBackend(vault_path=tmp_path, callouts=False)
        await backend.upsert_paper(_make_recommendation())

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        _, _, body = body.partition("---\n")
        _, _, body = body.partition("---\n")
        assert "## Abstract" in body
        assert "> [!abstract]" not in body

    async def test_templater_default_off_means_no_templater_syntax(
        self, tmp_path: Path
    ) -> None:
        """Per task 9.164: Templater is opt-in. Default-off output must not
        contain raw ``<%`` or ``<%*`` substrings — non-Templater users would
        see them as literal noise."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation())

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        assert "<%" not in body, "Templater syntax leaked into default output"
        assert "<%*" not in body

    async def test_templater_on_adds_template_block_in_notes(
        self, tmp_path: Path
    ) -> None:
        """Per task 9.164 acceptance: when ``templater=True``, the Notes
        section carries a Templater date/file variable wrapped in
        ``<%* %>`` blocks."""
        backend = MarkdownWikiBackend(vault_path=tmp_path, templater=True)
        await backend.upsert_paper(_make_recommendation())

        body = (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").read_text(encoding="utf-8")
        # Strip frontmatter so we look at the body proper.
        _, _, body = body.partition("---\n")
        _, _, body = body.partition("---\n")
        # Notes section carries a Templater expression — at minimum a date
        # variable so the user gets a live "last edited" stamp.
        assert "## Notes" in body
        assert "<%" in body, "Templater flag must inject at least one <% ... %> block"
        # ``tp.file.last_modified_date`` is the canonical Templater date helper.
        assert "tp.file" in body or "tp.date" in body

    async def test_concept_carries_obsidian_properties_block(self, tmp_path: Path) -> None:
        """Per task 9.161 / **D-D**: synthesized concept articles also carry
        the canonical six-field Properties block."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_concept(
            name="Multimodal Reasoning",
            body="...",
            sources=["arxiv:2506.13063"],
        )

        fm = _read_frontmatter(tmp_path / "Wiki" / "concepts" / "Multimodal_Reasoning.md")
        for key in ("tags", "aliases", "status", "cssclasses", "created", "updated"):
            assert key in fm, f"missing Properties field: {key}"
        assert isinstance(fm["tags"], list)
        assert isinstance(fm["aliases"], list)
        assert isinstance(fm["cssclasses"], list)
        assert isinstance(fm["created"], str)
        assert isinstance(fm["updated"], str)


# ---------------------------------------------------------------------------
# Discovery: list_sources / list_concepts
# ---------------------------------------------------------------------------


class TestDiscovery:
    async def test_list_sources_returns_typed_summaries(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation())

        summaries = await backend.list_sources()

        assert len(summaries) == 1
        s = summaries[0]
        assert isinstance(s, SourceSummary)
        assert s.canonical_id == "arxiv:2506.13063"
        assert s.title == "PRISM2: Unlocking Multi-Modal AI"
        assert s.status == "draft"
        assert s.path.is_file()

    async def test_list_concepts_returns_typed_summaries(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_concept(
            name="Vision-Language",
            body="...",
            sources=["arxiv:1"],
            confidence=0.6,
        )

        summaries = await backend.list_concepts()

        assert len(summaries) == 1
        c = summaries[0]
        assert isinstance(c, ConceptSummary)
        assert c.title == "Vision-Language"
        assert c.sources == ["arxiv:1"]
        assert c.confidence == 0.6
        assert c.path.is_file()

    async def test_empty_vault_returns_empty_lists(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        assert await backend.list_sources() == []
        assert await backend.list_concepts() == []


# ---------------------------------------------------------------------------
# query (protocol method)
# ---------------------------------------------------------------------------


class TestQuery:
    async def test_substring_match_on_source_title(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation(title="Foundation Model X"))
        await backend.upsert_paper(
            _make_recommendation(canonical_id="arxiv:0001.0001", title="Pure Math")
        )

        results = await backend.query("foundation")

        assert len(results) == 1
        assert results[0].paper.title == "Foundation Model X"

    async def test_query_empty_when_no_match(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_make_recommendation(title="Pure Math"))

        results = await backend.query("biology")

        assert results == []


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


class TestProtocolSatisfaction:
    def test_backend_satisfies_wiki_backend_protocol(self, tmp_path: Path) -> None:
        from paperwiki.core.protocols import WikiBackend

        backend = MarkdownWikiBackend(vault_path=tmp_path)
        assert isinstance(backend, WikiBackend)
