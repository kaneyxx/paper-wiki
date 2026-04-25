"""Unit tests for paperwiki.runners.wiki_lint."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend
from paperwiki.runners import wiki_lint as wiki_lint_runner

_NOW = datetime(2026, 4, 25, tzinfo=UTC)


async def _seed_healthy_concept(tmp_path: Path) -> None:
    backend = MarkdownWikiBackend(vault_path=tmp_path)
    await backend.upsert_concept(
        name="Healthy",
        body="Some prose.",
        sources=["arxiv:1"],
        confidence=0.7,
        status="reviewed",
    )


def _write(path: Path, frontmatter: str, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n\n{body}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# lint_wiki (async core)
# ---------------------------------------------------------------------------


class TestLintEmpty:
    async def test_empty_vault_has_no_findings(self, tmp_path: Path) -> None:
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        assert report.findings == []
        assert report.counts == {"info": 0, "warn": 0, "error": 0}

    async def test_healthy_vault_has_no_findings(self, tmp_path: Path) -> None:
        await _seed_healthy_concept(tmp_path)
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        assert report.findings == []


class TestOrphanConcept:
    async def test_concept_without_sources_is_flagged(self, tmp_path: Path) -> None:
        concept = tmp_path / "Wiki" / "concepts" / "Lonely.md"
        _write(
            concept,
            "title: Lonely\nstatus: draft\nconfidence: 0.5\nsources: []\n",
            "Body",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "ORPHAN_CONCEPT" in codes


class TestStaleConcept:
    async def test_old_last_synthesized_is_flagged(self, tmp_path: Path) -> None:
        concept = tmp_path / "Wiki" / "concepts" / "Stale.md"
        old = (_NOW - timedelta(days=200)).strftime("%Y-%m-%d")
        _write(
            concept,
            (
                "title: Stale\nstatus: reviewed\nconfidence: 0.7\n"
                'sources: ["arxiv:1"]\n'
                f'last_synthesized: "{old}"\n'
            ),
            "Body",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, stale_days=90, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "STALE" in codes

    async def test_recent_is_not_stale(self, tmp_path: Path) -> None:
        concept = tmp_path / "Wiki" / "concepts" / "Fresh.md"
        recent = (_NOW - timedelta(days=10)).strftime("%Y-%m-%d")
        _write(
            concept,
            (
                "title: Fresh\nstatus: reviewed\nconfidence: 0.7\n"
                'sources: ["arxiv:1"]\n'
                f'last_synthesized: "{recent}"\n'
            ),
            "Body",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, stale_days=90, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "STALE" not in codes


class TestOversizedFile:
    async def test_long_file_is_flagged(self, tmp_path: Path) -> None:
        concept = tmp_path / "Wiki" / "concepts" / "Long.md"
        body = "\n".join(f"line {i}" for i in range(700))
        _write(
            concept,
            'title: Long\nstatus: draft\nconfidence: 0.5\nsources: ["arxiv:1"]\n',
            body,
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, max_lines=600, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "OVERSIZED" in codes


class TestBrokenWikilink:
    async def test_wikilink_to_missing_concept_flagged(self, tmp_path: Path) -> None:
        concept = tmp_path / "Wiki" / "concepts" / "Linker.md"
        _write(
            concept,
            'title: Linker\nstatus: draft\nconfidence: 0.5\nsources: ["arxiv:1"]\n',
            "Refers to [[NonExistentConcept]] which is broken.",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "BROKEN_LINK" in codes

    async def test_wikilink_to_existing_concept_not_flagged(self, tmp_path: Path) -> None:
        # Create both concepts; the link should resolve.
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        await backend.upsert_concept(
            name="Target",
            body="Content.",
            sources=["arxiv:1"],
        )
        await backend.upsert_concept(
            name="Linker",
            body="See [[Target]].",
            sources=["arxiv:2"],
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "BROKEN_LINK" not in codes


class TestStatusMismatch:
    async def test_reviewed_with_low_confidence_flagged(self, tmp_path: Path) -> None:
        concept = tmp_path / "Wiki" / "concepts" / "Mismatch.md"
        _write(
            concept,
            'title: Mismatch\nstatus: reviewed\nconfidence: 0.3\nsources: ["arxiv:1"]\n',
            "Body",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "STATUS_MISMATCH" in codes


class TestDanglingSource:
    async def test_source_without_concept_reference_is_flagged(self, tmp_path: Path) -> None:
        # Source file exists but no concept references its canonical_id.
        source = tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md"
        _write(
            source,
            (
                'canonical_id: "arxiv:2506.13063"\n'
                'title: "Lonely Source"\n'
                "status: draft\nconfidence: 0.5\n"
            ),
            "Body",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "DANGLING_SOURCE" in codes

    async def test_source_referenced_by_concept_not_flagged(self, tmp_path: Path) -> None:
        backend = MarkdownWikiBackend(vault_path=tmp_path)
        # Source exists.
        source = tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md"
        _write(
            source,
            (
                'canonical_id: "arxiv:2506.13063"\n'
                'title: "Referenced Source"\n'
                "status: draft\nconfidence: 0.5\n"
            ),
            "Body",
        )
        # And a concept references it.
        await backend.upsert_concept(
            name="Vision-Language",
            body="Body.",
            sources=["arxiv:2506.13063"],
            confidence=0.7,
            status="reviewed",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        codes = {f.code for f in report.findings}
        assert "DANGLING_SOURCE" not in codes


class TestSeverityCounts:
    async def test_counts_aggregate(self, tmp_path: Path) -> None:
        concept = tmp_path / "Wiki" / "concepts" / "Multi.md"
        _write(
            concept,
            "title: Multi\nstatus: reviewed\nconfidence: 0.3\nsources: []\n",
            "Body",
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, now=_NOW)
        # Has at least an ORPHAN and a STATUS_MISMATCH on the same file.
        total = report.counts["info"] + report.counts["warn"] + report.counts["error"]
        assert total >= 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_emits_valid_json(self, tmp_path: Path) -> None:
        import asyncio

        asyncio.run(_seed_healthy_concept(tmp_path))

        runner = CliRunner()
        result = runner.invoke(wiki_lint_runner.app, [str(tmp_path)])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert "findings" in payload
        assert "counts" in payload
