"""Unit tests for paperwiki.runners.wiki_query."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    ScoreBreakdown,
)
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.runners import wiki_query as wiki_query_runner


def _rec(canonical_id: str, title: str, *, tags: list[str] | None = None) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name="A")],
            abstract="Stub abstract.",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=tags or [],
        ),
        score=ScoreBreakdown(composite=0.5),
        matched_topics=[],
    )


async def _seed(tmp_path: Path) -> MarkdownWikiBackend:
    backend = MarkdownWikiBackend(vault_path=tmp_path)
    await backend.upsert_paper(_rec("arxiv:0001.0001", "Foundation Models for Vision"))
    await backend.upsert_paper(_rec("arxiv:0002.0002", "Pure Math Combinatorics", tags=["math.CO"]))
    await backend.upsert_paper(_rec("arxiv:0003.0003", "Vision-Language Reasoning", tags=["cs.CV"]))
    await backend.upsert_concept(
        name="Vision-Language Foundation Models",
        body="A synthesis of vision-language work.",
        sources=["arxiv:0001.0001", "arxiv:0003.0003"],
    )
    return backend


# ---------------------------------------------------------------------------
# query_wiki (async core)
# ---------------------------------------------------------------------------


class TestQueryWiki:
    async def test_returns_empty_list_for_empty_vault(self, tmp_path: Path) -> None:
        hits = await wiki_query_runner.query_wiki(tmp_path, "anything")
        assert hits == []

    async def test_returns_empty_list_for_empty_query(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        hits = await wiki_query_runner.query_wiki(tmp_path, "   ")
        assert hits == []

    async def test_finds_source_by_title_keyword(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        hits = await wiki_query_runner.query_wiki(tmp_path, "foundation")
        assert any(h.type == "source" for h in hits)
        assert any("Foundation" in h.title for h in hits)

    async def test_finds_concept_by_title_keyword(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        hits = await wiki_query_runner.query_wiki(tmp_path, "foundation")
        assert any(h.type == "concept" for h in hits)

    async def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        hits = await wiki_query_runner.query_wiki(tmp_path, "biology")
        assert hits == []

    async def test_title_match_weighted_higher_than_tag_match(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        # "vision" is in tag of B, in title of A
        await backend.upsert_paper(_rec("arxiv:A", "Vision Models", tags=["cs.LG"]))
        await backend.upsert_paper(_rec("arxiv:B", "Pure Math", tags=["vision"]))

        hits = await wiki_query_runner.query_wiki(tmp_path, "vision")

        # A's title-hit should rank above B's tag-hit.
        assert hits[0].title == "Vision Models"

    async def test_top_k_caps_results(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        for i in range(15):
            await backend.upsert_paper(_rec(f"arxiv:00{i:02d}", "Foundation Paper"))

        hits = await wiki_query_runner.query_wiki(tmp_path, "foundation", top_k=5)
        assert len(hits) == 5

    async def test_concept_snippet_picks_first_body_paragraph(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        hits = await wiki_query_runner.query_wiki(tmp_path, "foundation")
        concept_hits = [h for h in hits if h.type == "concept"]
        assert concept_hits
        # Snippet should reference some prose from the body.
        assert "synthesis" in concept_hits[0].snippet.lower()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_emits_json_array(self, tmp_path: Path) -> None:
        # Seed synchronously by calling the async helper through asyncio.run.
        import asyncio

        asyncio.run(_seed(tmp_path))

        runner = CliRunner()
        result = runner.invoke(
            wiki_query_runner.app,
            [str(tmp_path), "foundation"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert isinstance(payload, list)
        assert payload  # non-empty
        for hit in payload:
            assert {"type", "path", "title", "snippet", "score"}.issubset(hit.keys())

    def test_no_match_emits_empty_list(self, tmp_path: Path) -> None:
        import asyncio

        asyncio.run(_seed(tmp_path))

        runner = CliRunner()
        result = runner.invoke(
            wiki_query_runner.app,
            [str(tmp_path), "biology"],
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == []
