"""Unit tests for paperwiki.runners.wiki_ingest_plan."""

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
from paperwiki.runners import wiki_ingest_plan as ingest_runner


def _rec(
    canonical_id: str, title: str, *, matched_topics: list[str] | None = None
) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name="A")],
            abstract="abc",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
        ),
        score=ScoreBreakdown(composite=0.5),
        matched_topics=matched_topics or [],
    )


# ---------------------------------------------------------------------------
# plan_ingest (async core)
# ---------------------------------------------------------------------------


class TestSourceMissing:
    async def test_source_not_in_vault(self, tmp_path: Path) -> None:
        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:9999.9999")
        assert plan.source_exists is False
        assert plan.affected_concepts == []
        assert plan.suggested_concepts == []


class TestSourcePresent:
    async def test_source_exists_no_concepts_yet(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["vision-language"])
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001")

        assert plan.source_exists is True
        assert plan.affected_concepts == []
        # Source's related_concepts (matched_topics) become suggestions when
        # no concept of that name exists yet.
        assert "vision-language" in plan.suggested_concepts

    async def test_source_referenced_by_concept_listed_as_affected(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_rec("arxiv:0001.0001", "Foundation"))
        await backend.upsert_concept(
            name="Foundation Models",
            body="Synthesis.",
            sources=["arxiv:0001.0001"],
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001")

        assert plan.affected_concepts == ["Foundation Models"]

    async def test_existing_concept_not_suggested_again(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec(
                "arxiv:0001.0001",
                "Foundation",
                matched_topics=["vision-language"],
            )
        )
        # The matched_topic-derived concept already exists.
        await backend.upsert_concept(
            name="vision-language",
            body="Already there.",
            sources=["arxiv:0001.0001"],
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001")

        # Already a concept; it shouldn't be in suggestions.
        assert "vision-language" not in plan.suggested_concepts
        # And it already references the source so should be in affected.
        assert "vision-language" in plan.affected_concepts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_emits_json(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(ingest_runner.app, [str(tmp_path), "arxiv:9999.9999"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["source_id"] == "arxiv:9999.9999"
        assert payload["source_exists"] is False
        assert payload["affected_concepts"] == []
