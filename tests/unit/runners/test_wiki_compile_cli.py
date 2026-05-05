"""CLI tests for ``paperwiki wiki-compile`` vault optionality (Task 9.216).

v0.4.5 Phase D wired the D-V resolver into 5 of 7 vault-needing
runners. ``wiki-compile`` was a Phase D oversight — it still required
``paperwiki wiki-compile <vault>`` even when
``~/.config/paper-wiki/config.toml::default_vault`` was set. v0.4.8
Task 9.216 closes the gap by mirroring the
``wiki_graph_query.py:294-309`` resolver wiring pattern.

These tests pin both forms:

* ``wiki-compile <vault>`` — back-compat (explicit positional wins).
* ``wiki-compile`` — new form, vault resolved from the D-V chain
  (``$PAPERWIKI_DEFAULT_VAULT`` →
  ``$PAPERWIKI_HOME/config.toml::default_vault``).

The tests stub out ``compile_wiki`` so they exercise CLI argument
parsing + resolver wiring without touching real vault state. The
short-circuit migrate flags (``--migrate-dry-run``,
``--restore-migration``, ``--properties-dry-run``,
``--restore-properties``, ``--no-auto-migrate``) all retain their
existing behavior because they fire AFTER resolver wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from paperwiki.runners.wiki_compile import CompileResult

if TYPE_CHECKING:
    from datetime import datetime


@pytest.fixture
def capture_compile_call(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the async ``compile_wiki`` with a recorder that returns a stub result."""
    captured: dict[str, Any] = {}

    async def _fake_compile(
        vault_path: Path,
        *,
        wiki_subdir: str = "Wiki",
        now: datetime | None = None,
        allow_auto_migrate: bool = True,
    ) -> CompileResult:
        captured["vault_path"] = vault_path
        captured["wiki_subdir"] = wiki_subdir
        captured["allow_auto_migrate"] = allow_auto_migrate
        return CompileResult(
            index_path=vault_path / wiki_subdir / "index.md",
            concepts=0,
            sources=0,
        )

    from paperwiki.runners import wiki_compile as runner

    monkeypatch.setattr(runner, "compile_wiki", _fake_compile)
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


def test_wiki_compile_with_explicit_vault_works(
    tmp_path: Path,
    capture_compile_call: dict[str, Any],
) -> None:
    """``wiki-compile <vault>`` is the historical form."""
    from paperwiki.runners import wiki_compile as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert capture_compile_call["vault_path"] == tmp_path


# ---------------------------------------------------------------------------
# New form: vault from resolver
# ---------------------------------------------------------------------------


def test_wiki_compile_resolves_vault_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_compile_call: dict[str, Any],
) -> None:
    """No vault arg → ``$PAPERWIKI_DEFAULT_VAULT`` wins."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import wiki_compile as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code == 0, result.output
    assert capture_compile_call["vault_path"] == tmp_path


def test_wiki_compile_resolves_vault_from_config_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_compile_call: dict[str, Any],
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

    from paperwiki.runners import wiki_compile as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code == 0, result.output
    assert capture_compile_call["vault_path"] == fake_vault


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_wiki_compile_no_vault_anywhere_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_compile_call: dict[str, Any],
) -> None:
    """No vault + no resolver source → actionable error message."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))  # empty home

    from paperwiki.runners import wiki_compile as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--vault" in combined or "PAPERWIKI_DEFAULT_VAULT" in combined


# ---------------------------------------------------------------------------
# Migration short-circuits unaffected by resolver wiring
# ---------------------------------------------------------------------------


def test_wiki_compile_migrate_dry_run_still_requires_explicit_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_compile_call: dict[str, Any],
) -> None:
    """``--migrate-dry-run`` short-circuits but still uses the resolved vault."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import wiki_compile as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--migrate-dry-run"])

    # The short-circuit returns 0 with a JSON list — verifies the
    # resolver fires before the short-circuit kicks in.
    assert result.exit_code == 0, result.output
    assert "planned_moves" in result.output
