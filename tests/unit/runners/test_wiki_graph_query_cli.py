"""CLI tests for ``paperwiki wiki-graph`` vault optionality (Task 9.194).

Phase D 9.194 makes the ``vault`` positional optional so
``wiki-graph --papers-citing <slug>`` works from any directory once a
default vault is configured. These tests pin both forms:

* ``wiki-graph <vault> --papers-citing <slug>`` — back-compat.
* ``wiki-graph --papers-citing <slug>`` — new form, vault resolved from
  the D-V chain (``$PAPERWIKI_DEFAULT_VAULT`` →
  ``$PAPERWIKI_HOME/config.toml``).

The tests stub out the ``query`` function so they exercise CLI
argument parsing + resolver wiring without touching real graph state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner


@pytest.fixture
def capture_query_call(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the synchronous ``query`` function with a recorder."""
    captured: dict[str, Any] = {}

    def _fake_query(
        vault: Path,
        *,
        wiki_subdir: str,
        papers_citing: str | None = None,
        concepts_in_topic: str | None = None,
        collaborators_of: str | None = None,
        force_rebuild: bool = False,
    ) -> list[dict[str, Any]]:
        captured["vault"] = vault
        captured["wiki_subdir"] = wiki_subdir
        captured["papers_citing"] = papers_citing
        captured["concepts_in_topic"] = concepts_in_topic
        captured["collaborators_of"] = collaborators_of
        captured["force_rebuild"] = force_rebuild
        return []

    from paperwiki.runners import wiki_graph_query as runner

    monkeypatch.setattr(runner, "query", _fake_query)
    return captured


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear paper-wiki env vars so the resolver state is clean per test."""
    for var in (
        "PAPERWIKI_DEFAULT_VAULT",
        "PAPERWIKI_HOME",
        "PAPERWIKI_CONFIG_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Back-compat: explicit vault still works
# ---------------------------------------------------------------------------


def test_wiki_graph_with_explicit_vault_works(
    tmp_path: Path,
    capture_query_call: dict[str, Any],
) -> None:
    """``wiki-graph <vault> --papers-citing <slug>`` is the historical form."""
    from paperwiki.runners import wiki_graph_query as runner

    cli = CliRunner()
    result = cli.invoke(
        runner.app,
        [str(tmp_path), "--papers-citing", "vision-multimodal"],
    )

    assert result.exit_code == 0, result.output
    assert capture_query_call["vault"] == tmp_path
    assert capture_query_call["papers_citing"] == "vision-multimodal"


# ---------------------------------------------------------------------------
# New form: vault from resolver
# ---------------------------------------------------------------------------


def test_wiki_graph_resolves_vault_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_query_call: dict[str, Any],
) -> None:
    """No vault arg → ``$PAPERWIKI_DEFAULT_VAULT`` wins."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import wiki_graph_query as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--papers-citing", "vision-multimodal"])

    assert result.exit_code == 0, result.output
    assert capture_query_call["vault"] == tmp_path
    assert capture_query_call["papers_citing"] == "vision-multimodal"


def test_wiki_graph_resolves_vault_from_config_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_query_call: dict[str, Any],
) -> None:
    """No vault arg, no env var → config.toml ``default_vault`` wins."""
    fake_home = tmp_path / "paperwiki-home"
    fake_home.mkdir()
    fake_vault = tmp_path / "vault"
    fake_vault.mkdir()  # vault dir must exist — main() validates `is_dir()`
    (fake_home / "config.toml").write_text(
        f'default_vault = "{fake_vault}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPERWIKI_HOME", str(fake_home))

    from paperwiki.runners import wiki_graph_query as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--concepts-in-topic", "vision-multimodal"])

    assert result.exit_code == 0, result.output
    assert capture_query_call["vault"] == fake_vault
    assert capture_query_call["concepts_in_topic"] == "vision-multimodal"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_wiki_graph_no_vault_anywhere_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_query_call: dict[str, Any],
) -> None:
    """No vault + no resolver source → actionable error message."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))  # empty home

    from paperwiki.runners import wiki_graph_query as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--papers-citing", "vision-multimodal"])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--vault" in combined or "PAPERWIKI_DEFAULT_VAULT" in combined


def test_wiki_graph_requires_one_query_flag_back_compat(
    tmp_path: Path,
    capture_query_call: dict[str, Any],
) -> None:
    """Existing rule preserved: missing all 3 query flags → exit 2."""
    from paperwiki.runners import wiki_graph_query as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [str(tmp_path)])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--papers-citing" in combined or "--concepts-in-topic" in combined


# ---------------------------------------------------------------------------
# JSON shape unchanged
# ---------------------------------------------------------------------------


def test_wiki_graph_emits_json_in_new_form(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_query_call: dict[str, Any],
) -> None:
    """The new no-vault form still emits the same JSON-array shape on stdout."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import wiki_graph_query as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--papers-citing", "vision-multimodal"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)  # query stub returns []
