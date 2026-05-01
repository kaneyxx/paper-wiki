"""``paperwiki gc-dedup-ledger`` CLI tests (task 9.168).

Exposes :func:`paperwiki._internal.dedup_ledger.gc_old_entries` to
end-users so they can prune the dedup ledger manually after a
keyword pivot or a vault reorganisation. Default behaviour mirrors
the env-var defaults (``PAPERWIKI_DEDUP_LEDGER_KEEP``, falling back
to 365 days) so calling the runner with no flags has predictable
semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from paperwiki._internal.dedup_ledger import (
    DedupLedgerEntry,
    append_dedup_entry,
    read_dedup_keys,
)
from paperwiki.runners.gc_dedup_ledger import app as gc_dedup_ledger_app


def _seed_ledger(vault: Path) -> None:
    now = datetime.now(UTC)
    append_dedup_entry(
        vault,
        DedupLedgerEntry(
            timestamp=now - timedelta(days=400),
            canonical_id="arxiv:2401.99001",
            title="Ancient",
            recipe="r",
            action="surfaced",
        ),
    )
    append_dedup_entry(
        vault,
        DedupLedgerEntry(
            timestamp=now - timedelta(days=10),
            canonical_id="arxiv:2401.99002",
            title="Fresh",
            recipe="r",
            action="surfaced",
        ),
    )


def test_gc_dedup_ledger_cli_drops_old_entries(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_ledger(vault)

    runner = CliRunner()
    result = runner.invoke(
        gc_dedup_ledger_app,
        ["--vault", str(vault), "--keep-days", "365"],
    )
    assert result.exit_code == 0
    assert "1" in result.output  # one entry deleted

    keys = read_dedup_keys(vault)
    assert "2401.99001" not in keys.arxiv_ids
    assert "2401.99002" in keys.arxiv_ids


def test_gc_dedup_ledger_cli_no_op_on_missing_vault_dir(tmp_path: Path) -> None:
    """A missing ``.paperwiki/`` is an empty ledger, not an error."""
    runner = CliRunner()
    result = runner.invoke(gc_dedup_ledger_app, ["--vault", str(tmp_path / "no-such-vault")])
    assert result.exit_code == 0
    assert "0" in result.output


def test_gc_dedup_ledger_cli_zero_keep_days_clears_ledger(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_ledger(vault)

    runner = CliRunner()
    result = runner.invoke(gc_dedup_ledger_app, ["--vault", str(vault), "--keep-days", "0"])
    assert result.exit_code == 0
    keys = read_dedup_keys(vault)
    assert keys.arxiv_ids == frozenset()
