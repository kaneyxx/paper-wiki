"""Unit tests for paperwiki.runners.wiki_compile."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    ScoreBreakdown,
)
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.runners import wiki_compile as wiki_compile_runner

_NOW = datetime(2026, 4, 25, tzinfo=UTC)


def _rec(canonical_id: str, title: str) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name="A")],
            abstract="abc",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
        ),
        score=ScoreBreakdown(composite=0.5),
    )


async def _seed(tmp_path: Path) -> None:
    backend = MarkdownWikiBackend(vault_path=tmp_path)
    await backend.upsert_paper(_rec("arxiv:0001.0001", "First Paper"))
    await backend.upsert_paper(_rec("arxiv:0002.0002", "Second Paper"))
    await backend.upsert_concept(
        name="Vision-Language",
        body="Synthesis.",
        sources=["arxiv:0001.0001", "arxiv:0002.0002"],
        confidence=0.7,
    )


# ---------------------------------------------------------------------------
# compile_wiki (async core)
# ---------------------------------------------------------------------------


class TestCompileEmptyWiki:
    async def test_empty_wiki_writes_stub_index(self, tmp_path: Path) -> None:
        result = await wiki_compile_runner.compile_wiki(tmp_path, now=_NOW)

        assert result.concepts == 0
        assert result.sources == 0
        index_path = tmp_path / "Wiki" / "index.md"
        assert index_path.is_file()
        text = index_path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "concepts: 0" in text
        assert "sources: 0" in text


class TestCompilePopulatedWiki:
    async def test_writes_concept_section(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        await wiki_compile_runner.compile_wiki(tmp_path, now=_NOW)
        text = (tmp_path / "Wiki" / "index.md").read_text(encoding="utf-8")
        assert "## Concepts" in text
        assert "[[Vision-Language]]" in text

    async def test_writes_sources_section(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        await wiki_compile_runner.compile_wiki(tmp_path, now=_NOW)
        text = (tmp_path / "Wiki" / "index.md").read_text(encoding="utf-8")
        assert "## Sources" in text
        assert "[[arxiv_0001.0001]]" in text
        assert "[[arxiv_0002.0002]]" in text

    async def test_frontmatter_counts_correct(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        result = await wiki_compile_runner.compile_wiki(tmp_path, now=_NOW)
        assert result.concepts == 1
        assert result.sources == 2
        text = (tmp_path / "Wiki" / "index.md").read_text(encoding="utf-8")
        assert "concepts: 1" in text
        assert "sources: 2" in text

    async def test_warning_banner_present(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        await wiki_compile_runner.compile_wiki(tmp_path, now=_NOW)
        text = (tmp_path / "Wiki" / "index.md").read_text(encoding="utf-8")
        # Must warn user not to hand-edit.
        assert "Auto-generated" in text or "auto-generated" in text


class TestDeterministicOutput:
    async def test_same_input_same_bytes(self, tmp_path: Path) -> None:
        await _seed(tmp_path)
        await wiki_compile_runner.compile_wiki(tmp_path, now=_NOW)
        first = (tmp_path / "Wiki" / "index.md").read_bytes()

        await wiki_compile_runner.compile_wiki(tmp_path, now=_NOW)
        second = (tmp_path / "Wiki" / "index.md").read_bytes()

        assert first == second


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    @pytest.fixture
    def seeded_vault(self, tmp_path: Path) -> Path:
        import asyncio

        asyncio.run(_seed(tmp_path))
        return tmp_path

    def test_emits_summary(self, seeded_vault: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(wiki_compile_runner.app, [str(seeded_vault)])
        assert result.exit_code == 0
        # Output should mention concept/source counts.
        assert "concepts" in result.output.lower()
