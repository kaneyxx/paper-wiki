"""CLI tests: ``dedup-list`` / ``dedup-dismiss`` / ``gc-dedup-ledger`` resolver
wiring (Task 9.195 / D-V).

Phase D 9.195 keeps the existing ``--vault`` flag accepted for
back-compat but routes the absence-of-flag case through the D-V
resolver. The user can now run::

    paperwiki dedup-list             # vault from $PAPERWIKI_DEFAULT_VAULT
    paperwiki dedup-dismiss arxiv:.. # ditto
    paperwiki gc-dedup-ledger        # ditto

These tests pin the back-compat (explicit ``--vault`` works) and the
new no-flag resolver path (env / config.toml fallback) for all three
commands.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear paper-wiki env vars so each test's resolver state is clean."""
    for var in (
        "PAPERWIKI_DEFAULT_VAULT",
        "PAPERWIKI_HOME",
        "PAPERWIKI_CONFIG_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


# ===========================================================================
# dedup-list
# ===========================================================================


def test_dedup_list_with_explicit_vault_works(tmp_path: Path) -> None:
    """Back-compat: ``dedup-list --vault <path>`` continues to function."""
    from paperwiki.runners import dedup_list as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--vault", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "no dismissed papers" in result.output


def test_dedup_list_resolves_vault_when_flag_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``--vault`` → resolver picks ``$PAPERWIKI_DEFAULT_VAULT``."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import dedup_list as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code == 0, result.output
    assert "no dismissed papers" in result.output


def test_dedup_list_no_vault_anywhere_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``--vault``, no env, no config → actionable error."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))  # empty home

    from paperwiki.runners import dedup_list as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--vault" in combined or "PAPERWIKI_DEFAULT_VAULT" in combined


# ===========================================================================
# dedup-dismiss
# ===========================================================================


def test_dedup_dismiss_with_explicit_vault_works(tmp_path: Path) -> None:
    """Back-compat: ``dedup-dismiss <id> --title ... --vault <path>`` works."""
    from paperwiki.runners import dedup_dismiss as runner

    cli = CliRunner()
    result = cli.invoke(
        runner.app,
        [
            "arxiv:2401.12345",
            "--title",
            "Test paper",
            "--vault",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "dismissed arxiv:2401.12345" in result.output

    ledger_path = tmp_path / ".paperwiki" / "dedup-ledger.jsonl"
    assert ledger_path.is_file(), "ledger file must be written"


def test_dedup_dismiss_resolves_vault_when_flag_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``--vault`` → resolver picks env var, ledger lands there."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import dedup_dismiss as runner

    cli = CliRunner()
    result = cli.invoke(
        runner.app,
        [
            "arxiv:2401.12345",
            "--title",
            "Test paper",
        ],
    )

    assert result.exit_code == 0, result.output
    ledger_path = tmp_path / ".paperwiki" / "dedup-ledger.jsonl"
    assert ledger_path.is_file()


def test_dedup_dismiss_no_vault_anywhere_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``--vault``, no env, no config → actionable error."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))

    from paperwiki.runners import dedup_dismiss as runner

    cli = CliRunner()
    result = cli.invoke(
        runner.app,
        ["arxiv:2401.12345", "--title", "Test paper"],
    )

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--vault" in combined or "PAPERWIKI_DEFAULT_VAULT" in combined


# ===========================================================================
# gc-dedup-ledger
# ===========================================================================


def test_gc_dedup_ledger_with_explicit_vault_works(tmp_path: Path) -> None:
    """Back-compat: ``gc-dedup-ledger --vault <path>`` continues to function."""
    from paperwiki.runners import gc_dedup_ledger as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["--vault", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "deleted" in result.output


def test_gc_dedup_ledger_resolves_vault_when_flag_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``--vault`` → resolver picks env var."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import gc_dedup_ledger as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code == 0, result.output
    assert "deleted" in result.output


def test_gc_dedup_ledger_no_vault_anywhere_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``--vault``, no env, no config → actionable error."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))

    from paperwiki.runners import gc_dedup_ledger as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--vault" in combined or "PAPERWIKI_DEFAULT_VAULT" in combined
