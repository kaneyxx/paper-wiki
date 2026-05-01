"""Anti-repetition dedup ledger (task 9.168 / decisions **D-F** + **D-M**).

Per **D-F**, the dedup ledger is a JSONL file the digest pipeline
consults across runs to avoid re-recommending papers the user has
already seen — silent-drop default, ``--include-dismissed`` audit.
Per **D-M**, the scope is vault-global: rejecting a paper out of one
recipe also drops it from every other recipe's output that touches
the same vault.

Storage path: ``<vault>/.paperwiki/dedup-ledger.jsonl``. Two action
classes:

* ``surfaced`` — paper appeared in a digest output. Written by the
  digest runner after every successful emit.
* ``dismissed`` — user explicitly rejected the paper (e.g. via
  ``paperwiki dedup-dismiss <id>``). Carries an optional ``reason``
  string for audit display.

Retention is bounded — the ``PAPERWIKI_DEDUP_LEDGER_KEEP`` env var
(default 365 days) lets ``gc_old_entries`` drop ancient rows so a
multi-year vault doesn't grow the ledger unbounded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from paperwiki._internal.dedup_ledger import (
    LEDGER_DIR,
    LEDGER_FILE,
    DedupLedgerEntry,
    append_dedup_entry,
    gc_old_entries,
    read_dedup_keys,
    read_dismissed_entries,
)


def _entry(
    *,
    canonical_id: str = "arxiv:2401.12345",
    title: str = "Foundation Models for Vision-Language",
    recipe: str = "daily-arxiv",
    action: str = "surfaced",
    reason: str | None = None,
    timestamp: datetime | None = None,
) -> DedupLedgerEntry:
    return DedupLedgerEntry(
        timestamp=timestamp or datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        canonical_id=canonical_id,
        title=title,
        recipe=recipe,
        action=action,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Schema invariants
# ---------------------------------------------------------------------------


class TestDedupLedgerEntry:
    def test_round_trips_through_json(self) -> None:
        entry = _entry(action="dismissed", reason="too narrow")
        payload = entry.model_dump_json()
        decoded = json.loads(payload)
        assert decoded["action"] == "dismissed"
        assert decoded["reason"] == "too narrow"
        restored = DedupLedgerEntry.model_validate_json(payload)
        assert restored == entry

    def test_action_is_validated_against_known_values(self) -> None:
        with pytest.raises(ValidationError):
            DedupLedgerEntry(
                timestamp=datetime(2026, 5, 1, tzinfo=UTC),
                canonical_id="arxiv:2401.12345",
                title="x",
                recipe="r",
                action="bogus-action",  # type: ignore[arg-type]
            )

    def test_timezone_required(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            DedupLedgerEntry(
                timestamp=datetime(2026, 5, 1, 12, 0, 0),  # noqa: DTZ001 - intentional
                canonical_id="arxiv:2401.12345",
                title="x",
                recipe="r",
                action="surfaced",
            )


# ---------------------------------------------------------------------------
# Append / read primitives
# ---------------------------------------------------------------------------


class TestAppendAndRead:
    def test_append_creates_file_at_documented_path(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        path = append_dedup_entry(vault, _entry())
        assert path == vault / LEDGER_DIR / LEDGER_FILE
        assert path.is_file()

    def test_read_dedup_keys_collects_arxiv_ids_and_title_keys(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        append_dedup_entry(vault, _entry(canonical_id="arxiv:2401.12345", title="Foo Bar"))
        append_dedup_entry(vault, _entry(canonical_id="arxiv:2402.99999", title="Quux"))
        keys = read_dedup_keys(vault)
        assert "2401.12345" in keys.arxiv_ids
        assert "2402.99999" in keys.arxiv_ids
        # Title keys are normalised — lowercased, whitespace-collapsed.
        assert any("foo" in k for k in keys.title_keys)

    def test_read_dedup_keys_includes_dismissed_entries(self, tmp_path: Path) -> None:
        """Dismissed papers must keep dropping silently — that's the whole point."""
        vault = tmp_path / "vault"
        vault.mkdir()
        append_dedup_entry(
            vault,
            _entry(
                canonical_id="arxiv:9999.99999",
                action="dismissed",
                reason="not in scope",
            ),
        )
        keys = read_dedup_keys(vault)
        assert "9999.99999" in keys.arxiv_ids

    def test_read_dismissed_entries_filters_to_dismissed_only(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        append_dedup_entry(vault, _entry(canonical_id="arxiv:0001.0001"))
        append_dedup_entry(
            vault,
            _entry(
                canonical_id="arxiv:0002.0002",
                action="dismissed",
                reason="too narrow",
            ),
        )
        dismissed = read_dismissed_entries(vault)
        assert len(dismissed) == 1
        assert dismissed[0].canonical_id == "arxiv:0002.0002"
        assert dismissed[0].reason == "too narrow"

    def test_read_returns_empty_on_missing_ledger(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        assert read_dedup_keys(vault).arxiv_ids == frozenset()
        assert read_dismissed_entries(vault) == []

    def test_corrupt_lines_skipped_gracefully(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        ledger_dir = vault / LEDGER_DIR
        ledger_dir.mkdir()
        ledger = ledger_dir / LEDGER_FILE
        valid = _entry(canonical_id="arxiv:0001.0001").model_dump_json()
        ledger.write_text(f"{valid}\nGARBAGE LINE\n", encoding="utf-8")
        keys = read_dedup_keys(vault)
        assert "0001.0001" in keys.arxiv_ids


# ---------------------------------------------------------------------------
# Retention / gc
# ---------------------------------------------------------------------------


class TestGcRetention:
    def test_drops_entries_older_than_keep_days(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        now = datetime.now(UTC)
        # One ancient entry (400 days old) + one fresh.
        append_dedup_entry(
            vault,
            _entry(
                canonical_id="arxiv:2401.99001",
                timestamp=now - timedelta(days=400),
            ),
        )
        append_dedup_entry(
            vault,
            _entry(
                canonical_id="arxiv:2401.99002",
                timestamp=now - timedelta(days=10),
            ),
        )
        deleted = gc_old_entries(vault, keep_days=365)
        assert deleted == 1
        keys = read_dedup_keys(vault)
        assert "2401.99001" not in keys.arxiv_ids
        assert "2401.99002" in keys.arxiv_ids

    def test_gc_no_op_when_no_old_entries(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        append_dedup_entry(vault, _entry())
        deleted = gc_old_entries(vault, keep_days=365)
        assert deleted == 0

    def test_gc_no_op_on_missing_ledger(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        assert gc_old_entries(vault, keep_days=365) == 0
