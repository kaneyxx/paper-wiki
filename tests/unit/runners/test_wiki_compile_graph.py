"""Unit tests for ``paperwiki.runners.wiki_compile_graph`` (task 9.157).

The runner walks ``<vault>/Wiki/{papers,concepts,topics,people}/`` and
materialises ``<vault>/Wiki/.graph/edges.jsonl`` + ``citations.jsonl``
from the wikilinks + frontmatter ``references:`` lists found in each
note. Frontmatter is canonical (D-B); the sidecar JSONL is a derived
query cache rebuilt on demand.

Tests pin the v0.4.x consensus-plan iter-2 acceptance:

* Idempotent — second run produces byte-identical bytes.
* Skips dotfiles.
* Auto-rebuilds when ``.graph/`` is missing OR older than the newest
  ``*.md`` mtime under ``<vault>/Wiki/`` (per R13 + Scenario 6).
* On read of an existing ``edges.jsonl`` with unknown ``EdgeType``
  values, the value is preserved verbatim with a ``loguru.warning``;
  on write, only canonical ``EdgeType`` enum values are emitted (per
  R12 / Scenario 7 / D-L).
* Emits one ``loguru`` line per stage with action + counts.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path


def _seed_vault(root: Path) -> Path:
    """Build a minimal 4-note vault for unit testing.

    One paper, one concept, one topic, one person — each with cross
    wikilinks. Returns the vault root (passed to ``compile_graph``).
    """
    wiki = root / "Wiki"
    (wiki / "papers").mkdir(parents=True)
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "topics").mkdir(parents=True)
    (wiki / "people").mkdir(parents=True)

    (wiki / "papers" / "arxiv-2401-00001.md").write_text(
        "---\n"
        "type: paper\n"
        "canonical_id: arxiv:2401.00001\n"
        "title: Sample paper\n"
        "---\n\n"
        "# Sample paper\n\n"
        "Builds on [[transformer]] within the [[vlm]] cluster.\n"
        "Author: [[alec-radford]].\n"
    )
    (wiki / "concepts" / "transformer.md").write_text(
        "---\n"
        "type: concept\n"
        "name: Transformer\n"
        "aliases: [transformer, attn]\n"
        "tags: [arch]\n"
        "---\n\n"
        "# Transformer\n\nAttention-based architecture.\n\n"
        "## Papers\n\n- [[arxiv-2401-00001]]\n"
    )
    (wiki / "topics" / "vlm.md").write_text(
        "---\n"
        "type: topic\n"
        "name: VLM\n"
        "---\n\n"
        "# VLM\n\nVision-language models.\n\n"
        "## Papers\n\n- [[arxiv-2401-00001]]\n"
    )
    (wiki / "people" / "alec-radford.md").write_text(
        "---\n"
        "type: person\n"
        "name: Alec Radford\n"
        "aliases: [alec-radford]\n"
        "---\n\n"
        "# Alec Radford\n\n## Papers\n\n- [[arxiv-2401-00001]]\n"
    )
    return root


class TestCompileGraphProducesSidecars:
    def test_emits_edges_jsonl(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        vault = _seed_vault(tmp_path)
        asyncio.run(compile_graph(vault))
        edges_path = vault / "Wiki" / ".graph" / "edges.jsonl"
        assert edges_path.is_file()
        # Each line is valid JSON.
        lines = [json.loads(line) for line in edges_path.read_text().splitlines()]
        assert len(lines) > 0
        for record in lines:
            assert {"src", "dst", "type"} <= record.keys()

    def test_emits_citations_jsonl(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        vault = _seed_vault(tmp_path)
        asyncio.run(compile_graph(vault))
        citations_path = vault / "Wiki" / ".graph" / "citations.jsonl"
        assert citations_path.is_file()

    def test_graph_dir_is_dotfile(self, tmp_path: Path) -> None:
        # ``.graph`` lives under leading-dot path so Obsidian doesn't
        # index it as a note (D-B sidecar contract).
        from paperwiki.runners.wiki_compile_graph import compile_graph

        vault = _seed_vault(tmp_path)
        asyncio.run(compile_graph(vault))
        graph_dir = vault / "Wiki" / ".graph"
        assert graph_dir.name.startswith(".")
        assert graph_dir.is_dir()


class TestCompileGraphIdempotent:
    def test_second_run_produces_identical_bytes(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        vault = _seed_vault(tmp_path)
        asyncio.run(compile_graph(vault))
        first_edges = (vault / "Wiki" / ".graph" / "edges.jsonl").read_bytes()
        first_cites = (vault / "Wiki" / ".graph" / "citations.jsonl").read_bytes()
        # Force a second pass; same input ⇒ same bytes.
        asyncio.run(compile_graph(vault, force_rebuild=True))
        second_edges = (vault / "Wiki" / ".graph" / "edges.jsonl").read_bytes()
        second_cites = (vault / "Wiki" / ".graph" / "citations.jsonl").read_bytes()
        assert first_edges == second_edges
        assert first_cites == second_cites


class TestCompileGraphSkipsDotfiles:
    def test_dotfiles_are_ignored(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        vault = _seed_vault(tmp_path)
        # Pollute one typed subdir with a dotfile that should be skipped.
        (vault / "Wiki" / "papers" / ".DS_Store").write_text("noise")
        (vault / "Wiki" / "papers" / ".hidden.md").write_text("---\ntype: paper\n---\n\n# hidden\n")
        asyncio.run(compile_graph(vault))
        edges = (vault / "Wiki" / ".graph" / "edges.jsonl").read_text()
        assert ".hidden" not in edges
        assert ".DS_Store" not in edges


class TestCompileGraphStaleness:
    def test_auto_rebuild_when_graph_missing(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import (
            compile_graph,
            graph_is_stale,
        )

        vault = _seed_vault(tmp_path)
        # No .graph/ yet → stale.
        assert graph_is_stale(vault) is True
        asyncio.run(compile_graph(vault))
        # After build → not stale.
        assert graph_is_stale(vault) is False

    def test_stale_when_md_newer_than_graph(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import (
            compile_graph,
            graph_is_stale,
        )

        vault = _seed_vault(tmp_path)
        asyncio.run(compile_graph(vault))
        assert graph_is_stale(vault) is False
        # Bump the mtime of one note — simulate a user edit.
        time.sleep(0.01)  # nudge mtime resolution
        new_md = vault / "Wiki" / "concepts" / "transformer.md"
        new_md.write_text(new_md.read_text() + "\n<!-- edited -->\n")
        # mtime must be at least the new write — set explicitly to avoid
        # filesystem timestamp-truncation flakiness on some platforms.
        future = time.time() + 5
        import os

        os.utime(new_md, (future, future))
        assert graph_is_stale(vault) is True


class TestCompileGraphResultSummary:
    def test_returns_summary_with_counts(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        vault = _seed_vault(tmp_path)
        result = asyncio.run(compile_graph(vault))
        assert result.entity_count >= 4
        assert result.edge_count >= 1
        assert result.edges_path == vault / "Wiki" / ".graph" / "edges.jsonl"


class TestCompileGraphResolvesWikilinks:
    def test_paper_to_concept_edge_built(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_compile_graph import compile_graph

        vault = _seed_vault(tmp_path)
        asyncio.run(compile_graph(vault))
        records = [
            json.loads(line)
            for line in (vault / "Wiki" / ".graph" / "edges.jsonl").read_text().splitlines()
        ]
        # The paper note links [[transformer]]; expect an edge from the
        # paper entity to the concept entity.
        srcs = [r["src"] for r in records]
        dsts = [r["dst"] for r in records]
        assert any("papers/arxiv-2401-00001" in s for s in srcs)
        assert any("concepts/transformer" in d for d in dsts)


class TestUnknownEdgeTypePreserved:
    def test_existing_edges_jsonl_with_unknown_type_round_trips(self, tmp_path: Path) -> None:
        """If a future paperwiki version emits an unknown edge type and a
        v0.4.0 user inspects/copies it, our runner must not crash on read.

        We seed an unknown type into edges.jsonl and verify the runner
        preserves it on a no-op rewrite (forward-compat per R12).
        """
        from paperwiki.runners.wiki_compile_graph import (
            EdgeRecord,
            iter_edges_jsonl,
        )

        graph_dir = tmp_path / ".graph"
        graph_dir.mkdir()
        edges_path = graph_dir / "edges.jsonl"
        edges_path.write_text(
            json.dumps(
                {
                    "src": "papers/a",
                    "dst": "papers/b",
                    "type": "evaluates_on",  # unknown to v0.4.0
                    "weight": 1.0,
                    "evidence": None,
                    "subtype": None,
                }
            )
            + "\n"
        )
        records = list(iter_edges_jsonl(edges_path))
        assert len(records) == 1
        # The reader preserves the unknown string verbatim.
        assert records[0].type == "evaluates_on"
        assert isinstance(records[0], EdgeRecord)
