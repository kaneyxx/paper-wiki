"""Unit tests for --auto-bootstrap mode in paperwiki.runners.wiki_ingest_plan."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from paperwiki.core.models import (
    Author,
    Paper,
    Recommendation,
    ScoreBreakdown,
)
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.runners import wiki_ingest_plan as ingest_runner
from paperwiki.runners._stub_constants import (
    AUTO_CREATED_FRONTMATTER_FIELDS,
    AUTO_CREATED_SENTINEL_BODY,
)


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


# ---------------------------------------------------------------------------
# Sentinel-constants module
# ---------------------------------------------------------------------------


class TestStubConstantsModule:
    def test_stub_constants_module_exposes_sentinel_body(self) -> None:
        assert AUTO_CREATED_SENTINEL_BODY == (
            "_Auto-created during digest auto-ingest. "
            "Lint with /paper-wiki:wiki-lint to flag for review._"
        )

    def test_stub_constants_module_exposes_frontmatter_fields(self) -> None:
        assert AUTO_CREATED_FRONTMATTER_FIELDS["auto_created"] is True
        assert "auto-created" in AUTO_CREATED_FRONTMATTER_FIELDS["tags"]  # type: ignore[operator]
        assert AUTO_CREATED_FRONTMATTER_FIELDS["status"] == "draft"
        assert AUTO_CREATED_FRONTMATTER_FIELDS["confidence"] == 0.3


# ---------------------------------------------------------------------------
# auto-bootstrap creates stubs for missing concepts
# ---------------------------------------------------------------------------


class TestAutoBootstrapCreateStubs:
    async def test_creates_stubs_for_missing_concepts(self, tmp_path: Path) -> None:
        """With empty Wiki/concepts/, --auto-bootstrap creates stub files."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec(
                "arxiv:0001.0001",
                "Foundation",
                matched_topics=["vision-multimodal", "diffusion-models"],
            )
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        # Stubs reported
        assert set(plan.created_stubs) == {"vision-multimodal", "diffusion-models"}

        # Files on disk
        concepts_dir = tmp_path / "Wiki" / "concepts"
        assert concepts_dir.is_dir()
        files = {f.stem for f in concepts_dir.glob("*.md")}
        assert "vision-multimodal" in files
        assert "diffusion-models" in files

    async def test_stubs_have_sentinel_body(self, tmp_path: Path) -> None:
        """Each stub file contains the sentinel body."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["vision-multimodal"])
        )

        await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        stub_path = tmp_path / "Wiki" / "concepts" / "vision-multimodal.md"
        assert stub_path.is_file()
        content = stub_path.read_text(encoding="utf-8")
        assert AUTO_CREATED_SENTINEL_BODY in content

    async def test_stubs_have_auto_created_frontmatter(self, tmp_path: Path) -> None:
        """Each stub file has auto_created: true in frontmatter."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["diffusion-models"])
        )

        await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        stub_path = tmp_path / "Wiki" / "concepts" / "diffusion-models.md"
        content = stub_path.read_text(encoding="utf-8")
        assert "auto_created: true" in content


# ---------------------------------------------------------------------------
# auto-bootstrap then updates concepts (source folded in)
# ---------------------------------------------------------------------------


class TestAutoBootstrapThenUpdates:
    async def test_affected_concepts_includes_newly_stubbed(self, tmp_path: Path) -> None:
        """After stubbing, the source's canonical_id appears in each stub's sources."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["vision-multimodal"])
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        # created_stubs AND affected_concepts both list the new concept
        assert "vision-multimodal" in plan.created_stubs
        assert "vision-multimodal" in plan.affected_concepts

    async def test_stub_sources_list_contains_canonical_id(self, tmp_path: Path) -> None:
        """Stub's sources frontmatter includes the ingest source id."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["vision-multimodal"])
        )

        await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        concepts = await backend.list_concepts()
        vision = next((c for c in concepts if "vision-multimodal" in c.title.lower()), None)
        assert vision is not None
        assert "arxiv:0001.0001" in vision.sources

    async def test_output_json_has_both_created_stubs_and_affected_concepts(
        self, tmp_path: Path
    ) -> None:
        """IngestPlan returned from auto-bootstrap has both fields populated."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec(
                "arxiv:0001.0001",
                "Foundation",
                matched_topics=["vision-multimodal", "diffusion-models"],
            )
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        assert len(plan.created_stubs) == 2
        assert len(plan.affected_concepts) >= 2
        assert set(plan.created_stubs).issubset(set(plan.affected_concepts))


# ---------------------------------------------------------------------------
# auto-bootstrap skips existing concepts
# ---------------------------------------------------------------------------


class TestAutoBootstrapSkipsExisting:
    async def test_skips_existing_concept_body(self, tmp_path: Path) -> None:
        """Pre-existing concept is NOT given auto_created: true frontmatter."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["vision-multimodal"])
        )
        # Pre-create concept manually (user content, no auto_created)
        await backend.upsert_concept(
            name="vision-multimodal",
            body="User-written synthesis.",
            sources=[],
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        # Not created as a stub
        assert "vision-multimodal" not in plan.created_stubs

        # File content does NOT have auto_created marker
        stub_path = tmp_path / "Wiki" / "concepts" / "vision-multimodal.md"
        content = stub_path.read_text(encoding="utf-8")
        assert "auto_created:" not in content

    async def test_existing_concept_sources_updated(self, tmp_path: Path) -> None:
        """Pre-existing concept gets its sources list updated (normal update loop)."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["vision-multimodal"])
        )
        await backend.upsert_concept(
            name="vision-multimodal",
            body="User-written synthesis.",
            sources=[],
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001", auto_bootstrap=True)

        # Pre-existing concept appears in affected_concepts (it references source now)
        assert "vision-multimodal" in plan.affected_concepts


# ---------------------------------------------------------------------------
# Without --auto-bootstrap preserves existing safeguard
# ---------------------------------------------------------------------------


class TestWithoutAutoBootstrap:
    async def test_no_flag_no_stubs_no_files(self, tmp_path: Path) -> None:
        """Without --auto-bootstrap, fresh vault → suggested_concepts only, no files."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec("arxiv:0001.0001", "Foundation", matched_topics=["vision-multimodal"])
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001")

        # No stubs created
        assert plan.created_stubs == []
        assert plan.affected_concepts == []
        assert "vision-multimodal" in plan.suggested_concepts

        # No concept files on disk
        concepts_dir = tmp_path / "Wiki" / "concepts"
        if concepts_dir.is_dir():
            assert list(concepts_dir.glob("*.md")) == []

    async def test_no_flag_preserves_suggested_concepts_field(self, tmp_path: Path) -> None:
        """Without --auto-bootstrap the existing suggested_concepts path is intact."""
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_paper(
            _rec(
                "arxiv:0001.0001",
                "Foundation",
                matched_topics=["vision-multimodal", "diffusion"],
            )
        )

        plan = await ingest_runner.plan_ingest(tmp_path, "arxiv:0001.0001")

        assert "vision-multimodal" in plan.suggested_concepts
        assert "diffusion" in plan.suggested_concepts
        assert plan.created_stubs == []


# ---------------------------------------------------------------------------
# CLI surface — --auto-bootstrap flag appears in --help
# ---------------------------------------------------------------------------


class TestCliAutoBootstrapFlag:
    def test_runner_accepts_auto_bootstrap_flag(self) -> None:
        """python -m paperwiki.runners.wiki_ingest_plan --help shows --auto-bootstrap."""
        result = subprocess.run(
            [sys.executable, "-m", "paperwiki.runners.wiki_ingest_plan", "--help"],
            capture_output=True,
            text=True,
            env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
        )
        assert result.returncode == 0, result.stderr
        assert "--auto-bootstrap" in result.stdout, (
            f"--auto-bootstrap not found in help output:\n{result.stdout}"
        )

    @pytest.mark.parametrize("flag_form", ["--auto-bootstrap", "--no-auto-bootstrap"])
    def test_auto_bootstrap_flag_forms_in_help(self, flag_form: str) -> None:
        """Both --auto-bootstrap and --no-auto-bootstrap appear in help (Typer bool)."""
        result = subprocess.run(
            [sys.executable, "-m", "paperwiki.runners.wiki_ingest_plan", "--help"],
            capture_output=True,
            text=True,
            env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
        )
        assert result.returncode == 0, result.stderr
        assert flag_form in result.stdout
