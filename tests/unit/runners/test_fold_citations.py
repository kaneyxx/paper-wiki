"""Unit tests for Task 9.13 — _fold_citations in wiki_ingest_plan.

Seven tests pin the citation-folding contract:
  1. appends to existing sources list
  2. idempotent (no-op if already present)
  3. preserves user body byte-exact
  4. preserves arbitrary frontmatter keys
  5. bumps last_synthesized to today
  6. empty when no pre-existing concepts
  7. combined with created_stubs
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from paperwiki.core.models import Author, Paper, Recommendation, ScoreBreakdown
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.runners import wiki_ingest_plan as ingest_runner


def _rec(
    canonical_id: str,
    title: str,
    *,
    matched_topics: list[str] | None = None,
) -> Recommendation:
    return Recommendation(
        paper=Paper(
            canonical_id=canonical_id,
            title=title,
            authors=[Author(name="A")],
            abstract="abc",
            published_at=datetime(2026, 4, 27, tzinfo=UTC),
        ),
        score=ScoreBreakdown(composite=0.5),
        matched_topics=matched_topics or [],
    )


def _parse_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter from a concept file."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"No frontmatter in {path}"
    end_idx = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end_idx]) or {}


def _parse_body(path: Path) -> str:
    """Parse body (after frontmatter) from a concept file."""
    text = path.read_text(encoding="utf-8")
    end_idx = text.index("\n---\n", 4)
    return text[end_idx + 5 :]  # skip past "\n---\n"


# ---------------------------------------------------------------------------
# Test 1: fold_citations appends to existing sources list
# ---------------------------------------------------------------------------


class TestFoldCitationsAppendsToSources:
    async def test_fold_citations_appends_to_existing_concept_sources_list(
        self, tmp_path: Path
    ) -> None:
        """Pre-existing concept with sources:[arxiv:111]; run --auto-bootstrap for
        arxiv:222; assert sources is now [arxiv:111, arxiv:222] and concept name
        in folded_citations."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        # Create pre-existing concept with a different source
        await backend.upsert_concept(
            name="vision-multimodal",
            body="Existing prose.",
            sources=["arxiv:111"],
        )

        # Ingest arxiv:222 which mentions vision-multimodal
        await backend.upsert_paper(
            _rec("arxiv:222", "New Paper", matched_topics=["vision-multimodal"])
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:222", auto_bootstrap=True)

        # folded_citations must contain the pre-existing concept name
        assert "vision-multimodal" in plan.folded_citations

        # concept's sources list now has both
        concept_path = tmp_path / "Wiki" / "concepts" / "vision-multimodal.md"
        fm = _parse_frontmatter(concept_path)
        assert "arxiv:111" in fm["sources"]
        assert "arxiv:222" in fm["sources"]


# ---------------------------------------------------------------------------
# Test 2: fold_citations is idempotent
# ---------------------------------------------------------------------------


class TestFoldCitationsIdempotent:
    async def test_fold_citations_is_idempotent(self, tmp_path: Path) -> None:
        """Pre-existing concept with sources:[arxiv:222]; run --auto-bootstrap for
        arxiv:222; sources stays [arxiv:222] (not duplicated) and concept NOT in
        folded_citations (nothing was actually folded)."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        # Pre-existing concept already cites the source we're ingesting
        await backend.upsert_concept(
            name="vision-multimodal",
            body="Existing prose.",
            sources=["arxiv:222"],
        )

        await backend.upsert_paper(_rec("arxiv:222", "Paper", matched_topics=["vision-multimodal"]))

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:222", auto_bootstrap=True)

        # concept NOT in folded_citations — nothing was actually appended
        assert "vision-multimodal" not in plan.folded_citations

        # sources list is exactly [arxiv:222], not duplicated
        concept_path = tmp_path / "Wiki" / "concepts" / "vision-multimodal.md"
        fm = _parse_frontmatter(concept_path)
        assert fm["sources"].count("arxiv:222") == 1


# ---------------------------------------------------------------------------
# Test 3: fold_citations preserves user body byte-exact
# ---------------------------------------------------------------------------


class TestFoldCitationsPreservesBody:
    async def test_fold_citations_preserves_user_body(self, tmp_path: Path) -> None:
        """Pre-existing concept with a custom body; run --auto-bootstrap; assert
        body is byte-exact preserved (only frontmatter changed)."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        custom_body = "# My Notes\n\nKey insight: transformers scale well.\n"

        # Write concept with custom body and no sources
        concept_path = tmp_path / "Wiki" / "concepts"
        concept_path.mkdir(parents=True, exist_ok=True)
        concept_file = concept_path / "vision-multimodal.md"
        frontmatter: dict = {
            "title": "vision-multimodal",
            "status": "draft",
            "confidence": 0.5,
            "sources": [],
            "related_concepts": [],
            "last_synthesized": "2024-01-01",
        }
        concept_file.write_text(
            "---\n"
            + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
            + "---\n"
            + custom_body,
            encoding="utf-8",
        )

        await backend.upsert_paper(_rec("arxiv:222", "Paper", matched_topics=["vision-multimodal"]))

        await ingest_runner.plan_ingest(tmp_path, "arxiv:222", auto_bootstrap=True)

        # Body must be byte-exact preserved
        body_after = _parse_body(concept_file)
        assert body_after == custom_body


# ---------------------------------------------------------------------------
# Test 4: fold_citations preserves arbitrary frontmatter keys
# ---------------------------------------------------------------------------


class TestFoldCitationsPreservesFrontmatterKeys:
    async def test_fold_citations_preserves_arbitrary_frontmatter_keys(
        self, tmp_path: Path
    ) -> None:
        """Pre-existing concept with extra YAML keys; run --auto-bootstrap;
        assert those keys round-trip unchanged."""
        concept_dir = tmp_path / "Wiki" / "concepts"
        concept_dir.mkdir(parents=True, exist_ok=True)
        concept_file = concept_dir / "vision-multimodal.md"

        frontmatter: dict = {
            "title": "vision-multimodal",
            "status": "draft",
            "confidence": 0.5,
            "sources": [],
            "related_concepts": [],
            "last_synthesized": "2024-01-01",
            "notes": ["todo: review later"],
            "priority": "high",
        }
        concept_file.write_text(
            "---\n"
            + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
            + "---\nSome body.\n",
            encoding="utf-8",
        )

        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_rec("arxiv:222", "Paper", matched_topics=["vision-multimodal"]))

        await ingest_runner.plan_ingest(tmp_path, "arxiv:222", auto_bootstrap=True)

        fm = _parse_frontmatter(concept_file)
        assert fm.get("notes") == ["todo: review later"]
        assert fm.get("priority") == "high"
        assert "arxiv:222" in fm["sources"]


# ---------------------------------------------------------------------------
# Test 5: fold_citations bumps last_synthesized
# ---------------------------------------------------------------------------


class TestFoldCitationsBumpsLastSynthesized:
    async def test_fold_citations_bumps_last_synthesized(self, tmp_path: Path) -> None:
        """Pre-existing concept with last_synthesized: '2024-01-01'; run
        --auto-bootstrap; assert last_synthesized bumps to today's UTC date."""
        concept_dir = tmp_path / "Wiki" / "concepts"
        concept_dir.mkdir(parents=True, exist_ok=True)
        concept_file = concept_dir / "vision-multimodal.md"

        frontmatter: dict = {
            "title": "vision-multimodal",
            "status": "draft",
            "confidence": 0.5,
            "sources": [],
            "related_concepts": [],
            "last_synthesized": "2024-01-01",
        }
        concept_file.write_text(
            "---\n"
            + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
            + "---\nBody.\n",
            encoding="utf-8",
        )

        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_rec("arxiv:222", "Paper", matched_topics=["vision-multimodal"]))

        await ingest_runner.plan_ingest(tmp_path, "arxiv:222", auto_bootstrap=True)

        fm = _parse_frontmatter(concept_file)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert fm.get("last_synthesized") == today


# ---------------------------------------------------------------------------
# Test 6: empty when no pre-existing concepts
# ---------------------------------------------------------------------------


class TestFoldCitationsEmptyWhenNoPreExisting:
    async def test_fold_citations_empty_when_no_pre_existing_concepts(self, tmp_path: Path) -> None:
        """Fresh vault with no Wiki/concepts/; run --auto-bootstrap; assert
        folded_citations: [] (only created_stubs populated)."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(_rec("arxiv:222", "Paper", matched_topics=["brand-new-concept"]))

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:222", auto_bootstrap=True)

        # No pre-existing concepts — nothing to fold
        assert plan.folded_citations == []
        # But the new concept was stubbed
        assert "brand-new-concept" in plan.created_stubs


# ---------------------------------------------------------------------------
# Test 7: combined with created_stubs
# ---------------------------------------------------------------------------


class TestFoldCitationsCombinedWithCreatedStubs:
    async def test_fold_citations_combined_with_created_stubs(self, tmp_path: Path) -> None:
        """Vault has 1 pre-existing concept; runner suggests it + 1 new;
        assert created_stubs: [<new>] and folded_citations: [<existing>]."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)

        # Pre-existing concept, no sources yet
        await backend.upsert_concept(
            name="existing-concept",
            body="Existing prose.",
            sources=[],
        )

        # Paper hints at both existing-concept and brand-new-concept
        await backend.upsert_paper(
            _rec(
                "arxiv:222",
                "Paper",
                matched_topics=["existing-concept", "brand-new-concept"],
            )
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:222", auto_bootstrap=True)

        # brand-new-concept was stubbed (it didn't exist)
        assert "brand-new-concept" in plan.created_stubs
        assert "existing-concept" not in plan.created_stubs

        # existing-concept got citation folded in
        assert "existing-concept" in plan.folded_citations
        assert "brand-new-concept" not in plan.folded_citations
