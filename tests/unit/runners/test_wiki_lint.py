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


# ---------------------------------------------------------------------------
# --check-graph rules (v0.4.x task 9.158)
#
# Adds two opt-in rules that consume the typed-subdir layout from D-I and
# the .graph/ sidecar from D-B:
#
# * ORPHAN_SOURCE   — Concept/Topic file with no inbound wikilinks.
# * GRAPH_INCONSISTENT — edges.jsonl claims A→B but B's frontmatter
#   ``references:`` is present and does NOT list A.
#
# Default off; opt-in via ``check_graph=True`` / ``--check-graph`` so
# existing pre-v0.4.x vaults don't surface new findings on upgrade.
# ---------------------------------------------------------------------------


def _seed_typed_vault(root: Path) -> None:
    """Seed a 4-note typed-subdir vault for graph-layer lint tests."""
    for sub in ("papers", "concepts", "topics", "people"):
        (root / sub).mkdir(parents=True)


class TestCheckGraphFlag:
    async def test_default_off_no_new_findings(self, tmp_path: Path) -> None:
        # Seed a typed vault with an obvious orphan concept; without
        # ``check_graph=True`` no ORPHAN_SOURCE finding should fire.
        _seed_typed_vault(tmp_path)
        (tmp_path / "concepts" / "lonely.md").write_text(
            "---\ntype: concept\nname: Lonely\n---\n\n# Lonely\n\nNo papers.\n"
        )
        report = await wiki_lint_runner.lint_wiki(tmp_path, wiki_subdir=".", now=_NOW)
        assert all(f.code != "ORPHAN_SOURCE" for f in report.findings)
        assert all(f.code != "GRAPH_INCONSISTENT" for f in report.findings)


class TestOrphanSource:
    async def test_concept_with_no_inbound_links_flagged(self, tmp_path: Path) -> None:
        _seed_typed_vault(tmp_path)
        (tmp_path / "concepts" / "lonely.md").write_text(
            "---\ntype: concept\nname: Lonely\n---\n\n# Lonely\n"
        )
        # Add a paper that does NOT reference the concept.
        (tmp_path / "papers" / "p1.md").write_text(
            "---\ntype: paper\n---\n\n# p1\n\nNo wikilinks.\n"
        )
        report = await wiki_lint_runner.lint_wiki(
            tmp_path, wiki_subdir=".", check_graph=True, now=_NOW
        )
        codes = {f.code for f in report.findings}
        assert "ORPHAN_SOURCE" in codes

    async def test_concept_with_inbound_link_not_flagged(self, tmp_path: Path) -> None:
        _seed_typed_vault(tmp_path)
        (tmp_path / "concepts" / "popular.md").write_text(
            "---\ntype: concept\nname: Popular\n---\n\n# Popular\n"
        )
        (tmp_path / "papers" / "p1.md").write_text(
            "---\ntype: paper\n---\n\n# p1\n\nUses [[popular]] heavily.\n"
        )
        report = await wiki_lint_runner.lint_wiki(
            tmp_path, wiki_subdir=".", check_graph=True, now=_NOW
        )
        orphan_paths = [f.path for f in report.findings if f.code == "ORPHAN_SOURCE"]
        assert "concepts/popular.md" not in orphan_paths

    async def test_orphan_papers_not_flagged(self, tmp_path: Path) -> None:
        # Papers can be standalone leaves; they shouldn't fire
        # ORPHAN_SOURCE even with no inbound refs.
        _seed_typed_vault(tmp_path)
        (tmp_path / "papers" / "isolated.md").write_text("---\ntype: paper\n---\n\n# isolated\n")
        report = await wiki_lint_runner.lint_wiki(
            tmp_path, wiki_subdir=".", check_graph=True, now=_NOW
        )
        orphan_paths = [f.path for f in report.findings if f.code == "ORPHAN_SOURCE"]
        assert "papers/isolated.md" not in orphan_paths


class TestGraphInconsistent:
    async def test_fires_when_frontmatter_refs_incomplete(self, tmp_path: Path) -> None:
        # B declares references: [c] but edges.jsonl will also derive
        # from a body wikilink in A pointing to B → A→B is in the
        # graph, but B's frontmatter doesn't list A. INCONSISTENT.
        from paperwiki.runners.wiki_compile_graph import compile_graph

        _seed_typed_vault(tmp_path)
        (tmp_path / "papers" / "a.md").write_text("---\ntype: paper\n---\n\n# a\n\nLinks [[b]].\n")
        (tmp_path / "papers" / "b.md").write_text("---\ntype: paper\nreferences: [c]\n---\n\n# b\n")
        await compile_graph(tmp_path, wiki_subdir=".")
        report = await wiki_lint_runner.lint_wiki(
            tmp_path, wiki_subdir=".", check_graph=True, now=_NOW
        )
        codes = {f.code for f in report.findings}
        assert "GRAPH_INCONSISTENT" in codes

    async def test_does_not_fire_when_refs_field_missing(self, tmp_path: Path) -> None:
        # If B has NO ``references:`` key in frontmatter, no
        # inconsistency is claimed by the user → no finding.
        from paperwiki.runners.wiki_compile_graph import compile_graph

        _seed_typed_vault(tmp_path)
        (tmp_path / "papers" / "a.md").write_text("---\ntype: paper\n---\n\n# a\n\nLinks [[b]].\n")
        (tmp_path / "papers" / "b.md").write_text("---\ntype: paper\n---\n\n# b\n")
        await compile_graph(tmp_path, wiki_subdir=".")
        report = await wiki_lint_runner.lint_wiki(
            tmp_path, wiki_subdir=".", check_graph=True, now=_NOW
        )
        codes = {f.code for f in report.findings}
        assert "GRAPH_INCONSISTENT" not in codes

    async def test_does_not_fire_when_refs_complete(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        _seed_typed_vault(tmp_path)
        (tmp_path / "papers" / "a.md").write_text("---\ntype: paper\n---\n\n# a\n\nLinks [[b]].\n")
        (tmp_path / "papers" / "b.md").write_text("---\ntype: paper\nreferences: [a]\n---\n\n# b\n")
        await compile_graph(tmp_path, wiki_subdir=".")
        report = await wiki_lint_runner.lint_wiki(
            tmp_path, wiki_subdir=".", check_graph=True, now=_NOW
        )
        codes = {f.code for f in report.findings}
        assert "GRAPH_INCONSISTENT" not in codes


class TestCliCheckGraphFlag:
    def test_check_graph_flag_accepted(self, tmp_path: Path) -> None:
        _seed_typed_vault(tmp_path)
        (tmp_path / "papers" / "p1.md").write_text("---\ntype: paper\n---\n\n# p1\n")
        runner = CliRunner()
        result = runner.invoke(
            wiki_lint_runner.app,
            [str(tmp_path), "--wiki-subdir", ".", "--check-graph"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert "findings" in payload


class TestSyntheticFixturePassesCheckGraph:
    """Per 9.156a acceptance: the synthetic fixture must pass
    ``wiki-lint --check-graph`` with zero ORPHAN_SOURCE /
    GRAPH_INCONSISTENT findings on first build.
    """

    async def test_no_graph_violations_on_synthetic(self) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        fixture = Path(__file__).parent.parent.parent / "fixtures" / "synthetic_vault_100"
        await compile_graph(fixture, wiki_subdir=".", force_rebuild=True)
        report = await wiki_lint_runner.lint_wiki(
            fixture, wiki_subdir=".", check_graph=True, now=_NOW
        )
        graph_codes = {"ORPHAN_SOURCE", "GRAPH_INCONSISTENT"}
        violations = [f for f in report.findings if f.code in graph_codes]
        assert violations == [], (
            f"synthetic fixture should pass --check-graph clean; got "
            f"{[f.code + ' ' + f.path for f in violations]}"
        )
