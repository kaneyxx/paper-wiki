"""CLI tests for ``paperwiki wiki-lint`` vault optionality (Task 9.216).

v0.4.5 Phase D wired the D-V resolver into 5 of 7 vault-needing
runners. ``wiki-lint`` was a Phase D oversight — it still required
``paperwiki wiki-lint <vault>`` even when
``~/.config/paper-wiki/config.toml::default_vault`` was set. v0.4.8
Task 9.216 closes the gap by mirroring the
``wiki_graph_query.py:294-309`` resolver wiring pattern.

These tests pin both forms:

* ``wiki-lint <vault>`` — back-compat (explicit positional wins).
* ``wiki-lint`` — new form, vault resolved from the D-V chain
  (``$PAPERWIKI_DEFAULT_VAULT`` →
  ``$PAPERWIKI_HOME/config.toml::default_vault``).

The tests stub out ``lint_wiki`` so they exercise CLI argument
parsing + resolver wiring without touching real vault state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from paperwiki.runners.wiki_lint import LintReport


@pytest.fixture
def capture_lint_call(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the async ``lint_wiki`` with a recorder that returns a stub report."""
    captured: dict[str, Any] = {}

    async def _fake_lint(
        vault_path: Path,
        *,
        wiki_subdir: str = "Wiki",
        stale_days: int = 90,
        max_lines: int = 600,
        check_graph: bool = False,
        **_kwargs: Any,
    ) -> LintReport:
        captured["vault_path"] = vault_path
        captured["wiki_subdir"] = wiki_subdir
        captured["stale_days"] = stale_days
        captured["max_lines"] = max_lines
        captured["check_graph"] = check_graph
        return LintReport()

    from paperwiki.runners import wiki_lint as runner

    monkeypatch.setattr(runner, "lint_wiki", _fake_lint)
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


def test_wiki_lint_with_explicit_vault_works(
    tmp_path: Path,
    capture_lint_call: dict[str, Any],
) -> None:
    """``wiki-lint <vault>`` is the historical form."""
    from paperwiki.runners import wiki_lint as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert capture_lint_call["vault_path"] == tmp_path
    # JSON-shaped report still emitted on stdout (back-compat).
    payload = json.loads(result.output)
    assert "findings" in payload
    assert "counts" in payload


# ---------------------------------------------------------------------------
# New form: vault from resolver
# ---------------------------------------------------------------------------


def test_wiki_lint_resolves_vault_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_lint_call: dict[str, Any],
) -> None:
    """No vault arg → ``$PAPERWIKI_DEFAULT_VAULT`` wins."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import wiki_lint as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code == 0, result.output
    assert capture_lint_call["vault_path"] == tmp_path


def test_wiki_lint_resolves_vault_from_config_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_lint_call: dict[str, Any],
) -> None:
    """No vault arg, no env var → config.toml ``default_vault`` wins."""
    fake_home = tmp_path / "paperwiki-home"
    fake_home.mkdir()
    fake_vault = tmp_path / "vault"
    fake_vault.mkdir()
    (fake_home / "config.toml").write_text(
        f'default_vault = "{fake_vault}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPERWIKI_HOME", str(fake_home))

    from paperwiki.runners import wiki_lint as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code == 0, result.output
    assert capture_lint_call["vault_path"] == fake_vault


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_wiki_lint_no_vault_anywhere_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_lint_call: dict[str, Any],
) -> None:
    """No vault + no resolver source → actionable error message."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))  # empty home

    from paperwiki.runners import wiki_lint as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--vault" in combined or "PAPERWIKI_DEFAULT_VAULT" in combined


# ---------------------------------------------------------------------------
# Existing flags unaffected by resolver wiring
# ---------------------------------------------------------------------------


def test_wiki_lint_check_graph_flag_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_lint_call: dict[str, Any],
) -> None:
    """``--check-graph`` flag forwards to ``lint_wiki`` regardless of resolver path."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import wiki_lint as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--check-graph"])

    assert result.exit_code == 0, result.output
    assert capture_lint_call["check_graph"] is True
