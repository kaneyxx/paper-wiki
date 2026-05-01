"""Unit tests for ``paperwiki.runners.wiki_graph_query`` (task 9.159).

The runner answers structured queries against the v0.4.x wiki graph:

* ``--papers-citing <paper>``: which entities have wikilinked to a paper
* ``--concepts-in-topic <topic>``: concepts directly referenced by a topic
* ``--collaborators-of <person>``: people the target person is linked to

Per consensus plan iter-2 D-Q, both ``--json`` (default) and
``--pretty`` (Markdown table) output formats are supported.

Per R13 + Scenario 6, the runner auto-rebuilds the ``.graph/`` cache
when the cache is stale relative to source Markdown.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner


def _seed_graph_vault(root: Path) -> Path:
    """Build a small typed-subdir vault and pre-build the graph cache."""
    from paperwiki.runners.wiki_compile_graph import compile_graph

    for sub in ("papers", "concepts", "topics", "people"):
        (root / sub).mkdir(parents=True)

    # Two papers; the second cites the first.
    (root / "papers" / "p1.md").write_text(
        "---\ntype: paper\n---\n\n# p1\n\nFoundational [[transformer]] work.\n"
    )
    (root / "papers" / "p2.md").write_text(
        "---\ntype: paper\n---\n\n# p2\n\nBuilds on [[p1]] using [[transformer]].\n"
    )
    # One concept referenced by both papers.
    (root / "concepts" / "transformer.md").write_text(
        "---\ntype: concept\nname: Transformer\n---\n\n# Transformer\n"
    )
    # One topic referencing the concept + papers.
    (root / "topics" / "vlm.md").write_text(
        "---\ntype: topic\nname: VLM\n---\n\n# VLM\n\nUses [[transformer]] in [[p1]] and [[p2]].\n"
    )
    # Two people, one collaborator each.
    (root / "people" / "alice.md").write_text(
        "---\ntype: person\nname: Alice\n---\n\n# Alice\n\nWith [[bob]] on [[p1]].\n"
    )
    (root / "people" / "bob.md").write_text(
        "---\ntype: person\nname: Bob\n---\n\n# Bob\n\nWith [[alice]] on [[p2]].\n"
    )

    asyncio.run(compile_graph(root, wiki_subdir="."))
    return root


class TestPapersCiting:
    def test_returns_entities_that_link_to_paper(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import query

        vault = _seed_graph_vault(tmp_path)
        result = query(
            vault,
            wiki_subdir=".",
            papers_citing="p1",
        )
        # p2 cites p1 directly via wikilink; topic vlm also references p1.
        ids = {item["src"] for item in result}
        assert "papers/p2" in ids
        assert "topics/vlm" in ids

    def test_unknown_paper_returns_empty(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import query

        vault = _seed_graph_vault(tmp_path)
        result = query(vault, wiki_subdir=".", papers_citing="does-not-exist")
        assert result == []


class TestConceptsInTopic:
    def test_returns_concepts_referenced_by_topic(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import query

        vault = _seed_graph_vault(tmp_path)
        result = query(vault, wiki_subdir=".", concepts_in_topic="vlm")
        ids = {item["dst"] for item in result}
        assert "concepts/transformer" in ids


class TestCollaboratorsOf:
    def test_returns_linked_people(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import query

        vault = _seed_graph_vault(tmp_path)
        result = query(vault, wiki_subdir=".", collaborators_of="alice")
        ids = {item["dst"] for item in result}
        assert "people/bob" in ids


class TestStalenessAutoRebuild:
    def test_query_auto_rebuilds_when_md_newer(self, tmp_path: Path) -> None:
        """Per R13: if the graph cache is older than the newest *.md file,
        the query runner should auto-rebuild before answering.
        """
        from paperwiki.runners.wiki_graph_query import query

        vault = _seed_graph_vault(tmp_path)
        # Add a new wikilink to p1 — this should appear in the next query
        # only if the auto-rebuild fires.
        import os
        import time

        new_paper = vault / "papers" / "p3.md"
        new_paper.write_text("---\ntype: paper\n---\n\n# p3\n\nAlso cites [[p1]].\n")
        # Force mtime forward so staleness logic detects it on filesystems
        # with low-resolution mtime (some macOS configurations).
        future = time.time() + 5
        os.utime(new_paper, (future, future))

        result = query(vault, wiki_subdir=".", papers_citing="p1")
        srcs = {item["src"] for item in result}
        assert "papers/p3" in srcs


class TestOutputFormats:
    def test_json_output_is_valid_json_array(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import format_pretty, query

        vault = _seed_graph_vault(tmp_path)
        result = query(vault, wiki_subdir=".", papers_citing="p1")
        # JSON-serialisable.
        json.dumps(result)
        # Markdown rendering is non-empty for non-empty input.
        rendered = format_pretty(result, header="papers citing p1")
        assert "papers citing p1" in rendered
        assert "|" in rendered  # markdown table delimiter

    def test_pretty_output_handles_empty_result(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import format_pretty

        rendered = format_pretty([], header="papers citing nothing")
        assert "no edges matched" in rendered.lower()


class TestCli:
    def test_papers_citing_via_json(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import app

        vault = _seed_graph_vault(tmp_path)
        cli = CliRunner()
        result = cli.invoke(
            app,
            [
                str(vault),
                "--wiki-subdir",
                ".",
                "--papers-citing",
                "p1",
                "--json",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert isinstance(payload, list)
        assert any("p2" in item["src"] for item in payload)

    def test_pretty_output_renders_markdown(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import app

        vault = _seed_graph_vault(tmp_path)
        cli = CliRunner()
        result = cli.invoke(
            app,
            [
                str(vault),
                "--wiki-subdir",
                ".",
                "--collaborators-of",
                "alice",
                "--pretty",
            ],
        )
        assert result.exit_code == 0
        assert "|" in result.output

    def test_at_least_one_query_required(self, tmp_path: Path) -> None:
        from paperwiki.runners.wiki_graph_query import app

        vault = _seed_graph_vault(tmp_path)
        cli = CliRunner()
        result = cli.invoke(app, [str(vault), "--wiki-subdir", "."])
        assert result.exit_code != 0
