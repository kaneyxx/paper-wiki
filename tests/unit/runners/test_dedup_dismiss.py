"""``paperwiki dedup-dismiss`` CLI tests (task 9.168 / **D-F**)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from paperwiki._internal.dedup_ledger import (
    LEDGER_DIR,
    LEDGER_FILE,
    read_dismissed_entries,
)
from paperwiki.runners.dedup_dismiss import app as dedup_dismiss_app


def test_appends_dismissed_row_to_ledger(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        dedup_dismiss_app,
        [
            "arxiv:2401.12345",
            "--title",
            "Foundation Models",
            "--vault",
            str(vault),
            "--reason",
            "out of scope",
        ],
    )
    assert result.exit_code == 0

    ledger = vault / LEDGER_DIR / LEDGER_FILE
    assert ledger.is_file()
    entries = read_dismissed_entries(vault)
    assert len(entries) == 1
    assert entries[0].canonical_id == "arxiv:2401.12345"
    assert entries[0].reason == "out of scope"
    assert entries[0].action == "dismissed"


def test_default_recipe_is_manual(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        dedup_dismiss_app,
        [
            "arxiv:2401.12345",
            "--title",
            "Foo",
            "--vault",
            str(vault),
        ],
    )
    assert result.exit_code == 0
    entries = read_dismissed_entries(vault)
    assert entries[0].recipe == "manual"


def test_no_reason_is_optional(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        dedup_dismiss_app,
        ["arxiv:2401.12345", "--title", "Foo", "--vault", str(vault)],
    )
    assert result.exit_code == 0
    entries = read_dismissed_entries(vault)
    assert entries[0].reason is None
