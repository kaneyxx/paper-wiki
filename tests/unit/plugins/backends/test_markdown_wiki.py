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
        assert fm["tags"] == ["cs.CV", "cs.LG"]
        # matched_topics flow into related_concepts as starter wikilinks.
        related = fm["related_concepts"]
        assert isinstance(related, list)
        assert any("vision-language" in s for s in related)

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
