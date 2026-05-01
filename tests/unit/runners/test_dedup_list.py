"""``paperwiki dedup-list`` CLI tests (task 9.168 / **D-F** audit surface)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from paperwiki._internal.dedup_ledger import DedupLedgerEntry, append_dedup_entry
from paperwiki.runners.dedup_list import app as dedup_list_app


def _seed(vault: Path) -> None:
    append_dedup_entry(
        vault,
        DedupLedgerEntry(
            timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
            canonical_id="arxiv:2401.12345",
            title="Foo",
            recipe="daily-arxiv",
            action="dismissed",
            reason="too narrow",
        ),
    )
    append_dedup_entry(
        vault,
        DedupLedgerEntry(
            timestamp=datetime(2026, 5, 2, 13, 0, 0, tzinfo=UTC),
            canonical_id="arxiv:2401.99999",
            title="Bar",
            recipe="biomedical-weekly",
            action="surfaced",  # Should NOT appear in dedup-list output.
        ),
    )


def test_pretty_format_renders_markdown_table(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed(vault)

    runner = CliRunner()
    result = runner.invoke(dedup_list_app, ["--vault", str(vault)])
    assert result.exit_code == 0
    assert "arxiv:2401.12345" in result.output
    assert "too narrow" in result.output
    # Surfaced entry is filtered out — dedup-list only shows dismissed.
    assert "arxiv:2401.99999" not in result.output
    # Markdown header present.
    assert "| dismissed" in result.output


def test_json_format_emits_jsonl(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed(vault)

    runner = CliRunner()
    result = runner.invoke(dedup_list_app, ["--vault", str(vault), "--format", "json"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1, f"only one dismissed row, got {lines!r}"
    row = json.loads(lines[0])
    assert row["canonical_id"] == "arxiv:2401.12345"
    assert row["action"] == "dismissed"


def test_no_entries_prints_friendly_message(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runner = CliRunner()
    result = runner.invoke(dedup_list_app, ["--vault", str(vault)])
    assert result.exit_code == 0
    assert "no dismissed papers" in result.output


def test_unknown_format_raises_bad_parameter(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runner = CliRunner()
    result = runner.invoke(dedup_list_app, ["--vault", str(vault), "--format", "yaml"])
    assert result.exit_code != 0
