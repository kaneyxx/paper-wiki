"""Integration: full wiki flow — backend writes, runners observe.

Walks the same path the four wiki SKILLs walk together:

1. ``upsert_paper`` populates ``Wiki/sources/``.
2. ``upsert_concept`` populates ``Wiki/concepts/``.
3. ``wiki_ingest_plan`` resolves which concepts reference a source.
4. ``wiki_compile`` rebuilds ``Wiki/index.md`` deterministically.
5. ``wiki_query`` retrieves the source by keyword.
6. ``wiki_lint`` reports zero findings for the healthy state.

The synthesis half (Claude prose) lives in the SKILLs and is not
covered by integration tests — only the I/O contract is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    ScoreBreakdown,
)
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.runners import wiki_compile, wiki_ingest_plan, wiki_lint, wiki_query

_NOW = datetime(2026, 4, 25, tzinfo=UTC)


def _rec(canonical_id: str, title: str) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name="Jane Doe")],
            abstract="Foundation model abstract.",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=["cs.CV"],
        ),
        score=ScoreBreakdown(composite=0.7),
        matched_topics=["vision-language"],
    )


async def test_full_wiki_flow(tmp_path: Path) -> None:
    backend = MarkdownWikiBackend(vault_path=tmp_path)

    # 1. Seed a source + a concept that references it.
    await backend.upsert_paper(_rec("arxiv:2506.13063", "Foundation Models for Vision"))
    await backend.upsert_concept(
        name="Vision-Language Foundation Models",
        body=(
            "A synthesis of vision-language foundation model work, drawing on "
            "[[arxiv_2506.13063]]."
        ),
        sources=["arxiv:2506.13063"],
        confidence=0.7,
        status="reviewed",
    )

    # 2. Ingest plan: the concept already references the source, so
    # affected_concepts contains its title.
    plan = await wiki_ingest_plan.plan_ingest(tmp_path, "arxiv:2506.13063")
    assert plan.source_exists is True
    assert plan.affected_concepts == ["Vision-Language Foundation Models"]

    # 3. Compile rebuilds the index.
    result = await wiki_compile.compile_wiki(tmp_path, now=_NOW)
    assert result.concepts == 1
    assert result.sources == 1
    index_text = (tmp_path / "Wiki" / "index.md").read_text(encoding="utf-8")
    # Compile uses the file-stem name (sanitized) for wikilink targets.
    assert "[[Vision-Language_Foundation_Models]]" in index_text
    assert "[[arxiv_2506.13063]]" in index_text

    # 4. Query finds the source by keyword.
    hits = await wiki_query.query_wiki(tmp_path, "foundation")
    assert any(h.type == "source" for h in hits)
    assert any(h.type == "concept" for h in hits)

    # 5. Lint reports zero findings for the healthy state.
    report = await wiki_lint.lint_wiki(tmp_path, now=_NOW)
    assert report.findings == []
    assert report.counts == {"info": 0, "warn": 0, "error": 0}


async def test_lint_catches_broken_link_after_concept_deletion(tmp_path: Path) -> None:
    """Deleting a concept that another concept links to triggers BROKEN_LINK."""
    backend = MarkdownWikiBackend(vault_path=tmp_path)
    await backend.upsert_concept(
        name="A",
        body="Refers to [[B]] which we will delete.",
        sources=["arxiv:1"],
    )
    await backend.upsert_concept(
        name="B",
        body="Lonely concept.",
        sources=["arxiv:2"],
    )

    # Delete B by removing the file.
    (tmp_path / "Wiki" / "concepts" / "B.md").unlink()

    report = await wiki_lint.lint_wiki(tmp_path, now=_NOW)
    codes = {f.code for f in report.findings}
    assert "BROKEN_LINK" in codes
