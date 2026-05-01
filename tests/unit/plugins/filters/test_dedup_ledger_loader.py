"""``DedupLedgerKeyLoader`` plugin tests (task 9.168).

The dedup filter consumes :class:`DedupKeys` from any number of
``KeyLoader`` instances. Task 9.168 introduces a new loader,
:class:`DedupLedgerKeyLoader`, that reads from
``<vault>/.paperwiki/dedup-ledger.jsonl`` so dismissed/surfaced
papers persist across runs.

Per **D-M** (vault-global scope), one ``DedupLedgerKeyLoader`` is
enough for the entire vault — recipes don't get per-recipe ledgers.
This module tests only the loader (KeyLoader contract); wiring into
the recipe schema lives in tests/unit/config/test_recipe.py and the
end-to-end persist-across-runs guarantee in
tests/integration/test_dedup_ledger_round_trip.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from paperwiki._internal.dedup_ledger import (
    DedupLedgerEntry,
    append_dedup_entry,
)
from paperwiki.core.models import RunContext
from paperwiki.plugins.filters.dedup import (
    DedupLedgerKeyLoader,
)


def _ctx() -> RunContext:
    return RunContext(target_date=datetime(2026, 5, 1, tzinfo=UTC), config_snapshot={})


async def test_returns_empty_keys_for_fresh_vault(tmp_path: Path) -> None:
    """No ledger file → empty keys; the loader must not raise."""
    vault = tmp_path / "vault"
    vault.mkdir()
    loader = DedupLedgerKeyLoader(vault_path=vault)
    keys = await loader.load(_ctx())
    assert keys.arxiv_ids == frozenset()
    assert keys.title_keys == frozenset()


async def test_loads_arxiv_ids_from_surfaced_entries(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    append_dedup_entry(
        vault,
        DedupLedgerEntry(
            timestamp=datetime(2026, 5, 1, tzinfo=UTC),
            canonical_id="arxiv:2401.12345",
            title="Foo Bar",
            recipe="daily-arxiv",
            action="surfaced",
        ),
    )
    keys = await DedupLedgerKeyLoader(vault_path=vault).load(_ctx())
    assert "2401.12345" in keys.arxiv_ids


async def test_loads_dismissed_entries_too(tmp_path: Path) -> None:
    """Dismissed papers must keep dropping silently — that's the point of the ledger."""
    vault = tmp_path / "vault"
    vault.mkdir()
    append_dedup_entry(
        vault,
        DedupLedgerEntry(
            timestamp=datetime(2026, 5, 1, tzinfo=UTC),
            canonical_id="arxiv:9999.99999",
            title="Rejected paper",
            recipe="daily-arxiv",
            action="dismissed",
            reason="not in scope",
        ),
    )
    keys = await DedupLedgerKeyLoader(vault_path=vault).load(_ctx())
    assert "9999.99999" in keys.arxiv_ids


async def test_loader_name_includes_vault_basename(tmp_path: Path) -> None:
    """The KeyLoader.name surface drives counter keys; must distinguish loaders."""
    vault = tmp_path / "MyVault"
    vault.mkdir()
    loader = DedupLedgerKeyLoader(vault_path=vault)
    assert "MyVault" in loader.name
    assert "dedup-ledger" in loader.name
