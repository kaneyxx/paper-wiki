"""Task 9.210 — ``wiki-graph`` must degrade gracefully on empty vault.

A fresh-installed or freshly-wiped vault has no ``Wiki/`` subdir
yet. Before this fix, ``wiki-graph --concepts-in-topic <slug>`` on
such a vault raised ``PaperWikiError: wiki root missing: <vault>/Wiki``
and exited non-zero — surprising for what should be the user's
first-impression command after install.

The fix: ``_ensure_fresh_graph`` short-circuits when
``(vault_path / wiki_subdir).is_dir()`` is False so ``compile_graph``
isn't asked to walk a non-existent directory. ``query()`` already
handles the case where the cached ``edges.jsonl`` doesn't exist
(returns ``[]``), so the runner naturally falls through to an empty
JSON array.

These tests cover three empty-vault shapes and all three query
branches so the fix doesn't accidentally only cover one path.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from paperwiki.runners import wiki_graph_query

if TYPE_CHECKING:
    from pathlib import Path


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Vault with NO Wiki subdir at all (the reported case)
# ---------------------------------------------------------------------------


def test_concepts_in_topic_returns_empty_when_wiki_subdir_missing(tmp_path: Path) -> None:
    """The reported bug — ``Wiki/`` doesn't exist."""
    # tmp_path exists as a directory but has no ``Wiki/`` subdir.
    result = _runner().invoke(
        wiki_graph_query.app,
        ["--concepts-in-topic", "vision-multimodal", str(tmp_path)],
    )

    assert result.exit_code == 0, (
        f"expected exit 0, got {result.exit_code}; stderr={result.stderr!r}"
    )
    assert json.loads(result.stdout) == []


def test_papers_citing_returns_empty_when_wiki_subdir_missing(tmp_path: Path) -> None:
    result = _runner().invoke(
        wiki_graph_query.app,
        ["--papers-citing", "arxiv:2501.99999", str(tmp_path)],
    )

    assert result.exit_code == 0, (
        f"expected exit 0, got {result.exit_code}; stderr={result.stderr!r}"
    )
    assert json.loads(result.stdout) == []


def test_collaborators_of_returns_empty_when_wiki_subdir_missing(tmp_path: Path) -> None:
    result = _runner().invoke(
        wiki_graph_query.app,
        ["--collaborators-of", "alice", str(tmp_path)],
    )

    assert result.exit_code == 0, (
        f"expected exit 0, got {result.exit_code}; stderr={result.stderr!r}"
    )
    assert json.loads(result.stdout) == []


# ---------------------------------------------------------------------------
# Vault with empty Wiki subdir
# ---------------------------------------------------------------------------


def test_returns_empty_when_wiki_subdir_empty(tmp_path: Path) -> None:
    """``Wiki/`` exists but is empty — no edges to find, no crash."""
    (tmp_path / "Wiki").mkdir()

    result = _runner().invoke(
        wiki_graph_query.app,
        ["--concepts-in-topic", "vision-multimodal", str(tmp_path)],
    )

    assert result.exit_code == 0, (
        f"expected exit 0, got {result.exit_code}; stderr={result.stderr!r}"
    )
    assert json.loads(result.stdout) == []


# ---------------------------------------------------------------------------
# --pretty branch on empty vault
# ---------------------------------------------------------------------------


def test_pretty_form_emits_no_edges_message_on_empty_vault(tmp_path: Path) -> None:
    """``--pretty`` should emit the canonical "No edges matched." line."""
    result = _runner().invoke(
        wiki_graph_query.app,
        [
            "--concepts-in-topic",
            "vision-multimodal",
            "--pretty",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "No edges matched." in result.stdout


# ---------------------------------------------------------------------------
# Direct ``query()`` API — pure unit, no CLI
# ---------------------------------------------------------------------------


def test_query_returns_empty_list_when_wiki_root_missing(tmp_path: Path) -> None:
    """Pure unit test on the function — no CLI in the loop."""
    result = wiki_graph_query.query(
        tmp_path,
        concepts_in_topic="vision-multimodal",
    )
    assert result == []


def test_query_returns_empty_list_when_wiki_root_empty(tmp_path: Path) -> None:
    (tmp_path / "Wiki").mkdir()
    result = wiki_graph_query.query(
        tmp_path,
        concepts_in_topic="vision-multimodal",
    )
    assert result == []
