"""Run-status ledger tests (task 9.167 / decision **D-O**).

The run-status ledger is a vault-bound JSONL file that records every
digest run's outcome — papers fetched, filter drops, final count,
elapsed time, plus an error class/message when the run failed. The
ledger lives under ``<vault>/.paperwiki/run-status.jsonl`` so the
``.paperwiki/`` namespace stays out of Obsidian's note index (leading
dot is honored by Obsidian as a vault-ignore convention).

Per **D-O**, vault-bound storage means:

* Cross-machine vault sync (Obsidian Sync, Syncthing, Git) carries
  the ledger with the vault — the user's history follows them.
* The ``.paperwiki/`` namespace is paper-wiki's private scratch
  space; all of v0.4.x's persistent state (run-status, dedup
  ledger, migration backups) shares this prefix.

This module exercises only the storage primitive. Wiring into the
digest runner is covered in tests/integration/test_digest.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from paperwiki._internal.run_status import (
    LEDGER_DIR,
    LEDGER_FILE,
    RunStatusEntry,
    append_run_status,
    read_recent_run_status,
)


def _entry(
    *,
    recipe: str = "daily-arxiv",
    final_count: int = 5,
    error_class: str | None = None,
    error_message: str | None = None,
) -> RunStatusEntry:
    return RunStatusEntry(
        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        recipe=recipe,
        target_date=datetime(2026, 5, 1, tzinfo=UTC),
        source_counts={"arxiv": 50, "semantic_scholar": 20},
        source_errors={},
        filter_drops={"recency": 10, "relevance": 30, "dedup": 5},
        final_count=final_count,
        elapsed_ms=1234,
        error_class=error_class,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# Schema invariants
# ---------------------------------------------------------------------------


class TestRunStatusEntry:
    def test_entry_serialises_to_round_trippable_json(self) -> None:
        entry = _entry()
        # Pydantic emits an ISO-8601 string with offset for tz-aware datetimes.
        payload = entry.model_dump_json()
        decoded = json.loads(payload)
        assert decoded["recipe"] == "daily-arxiv"
        assert decoded["final_count"] == 5
        # Preserve nested per-stage dicts as JSON objects.
        assert decoded["source_counts"] == {"arxiv": 50, "semantic_scholar": 20}
        assert decoded["filter_drops"] == {"recency": 10, "relevance": 30, "dedup": 5}
        # Round-trip through model_validate_json.
        restored = RunStatusEntry.model_validate_json(payload)
        assert restored == entry

    def test_naive_datetime_rejected(self) -> None:
        """Naive datetimes drift between machines; we want UTC-aware only."""
        with pytest.raises(ValidationError, match="timezone-aware"):
            RunStatusEntry(
                timestamp=datetime(2026, 5, 1, 12, 0, 0),  # noqa: DTZ001 - intentional
                recipe="r",
                target_date=datetime(2026, 5, 1, tzinfo=UTC),
                source_counts={},
                source_errors={},
                filter_drops={},
                final_count=0,
                elapsed_ms=0,
            )

    def test_error_fields_optional(self) -> None:
        """Successful runs carry no error class/message."""
        entry = _entry()
        assert entry.error_class is None
        assert entry.error_message is None


# ---------------------------------------------------------------------------
# Append / read primitives
# ---------------------------------------------------------------------------


class TestAppendAndRead:
    def test_append_creates_dotpaperwiki_dir_with_one_line(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        ledger_path = append_run_status(vault, _entry())

        # Path contract: <vault>/.paperwiki/run-status.jsonl
        assert ledger_path == vault / LEDGER_DIR / LEDGER_FILE
        assert ledger_path.exists()
        assert ledger_path.parent.name == ".paperwiki"

        # Exactly one line (terminated).
        text = ledger_path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert text.count("\n") == 1

        # The single line round-trips back into a RunStatusEntry.
        decoded = RunStatusEntry.model_validate_json(text.strip())
        assert decoded.recipe == "daily-arxiv"

    def test_append_is_idempotent_under_concurrent_runs(self, tmp_path: Path) -> None:
        """Two appends should produce two distinct lines, not overwrite."""
        vault = tmp_path / "vault"
        vault.mkdir()
        append_run_status(vault, _entry(recipe="first"))
        append_run_status(vault, _entry(recipe="second"))
        text = (vault / LEDGER_DIR / LEDGER_FILE).read_text(encoding="utf-8")
        lines = text.strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["recipe"] == "first"
        assert json.loads(lines[1])["recipe"] == "second"

    def test_read_recent_returns_last_n_newest_first(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        for i in range(7):
            append_run_status(vault, _entry(recipe=f"run-{i}"))
        recent = read_recent_run_status(vault, limit=5)
        # Newest first: the 5 most-recent recipe names in reverse insert order.
        assert [e.recipe for e in recent] == [
            "run-6",
            "run-5",
            "run-4",
            "run-3",
            "run-2",
        ]

    def test_read_recent_on_missing_ledger_returns_empty(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        # No append yet — ledger file does not exist.
        assert read_recent_run_status(vault, limit=5) == []

    def test_read_recent_skips_corrupt_lines(self, tmp_path: Path) -> None:
        """A bad line shouldn't take down the whole reader.

        The ledger is append-only and carries history we don't want to
        lose to one bad write — readers (e.g. ``paperwiki status``) skip
        the bad line and keep going.
        """
        vault = tmp_path / "vault"
        vault.mkdir()
        ledger_dir = vault / LEDGER_DIR
        ledger_dir.mkdir()
        ledger = ledger_dir / LEDGER_FILE
        # Mix one valid + one corrupt + another valid line.
        valid_a = _entry(recipe="a").model_dump_json()
        valid_b = _entry(recipe="b").model_dump_json()
        ledger.write_text(f"{valid_a}\nthis is not json\n{valid_b}\n", encoding="utf-8")
        recent = read_recent_run_status(vault, limit=5)
        assert [e.recipe for e in recent] == ["b", "a"]

    def test_records_error_class_and_message(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        entry = _entry(
            final_count=0,
            error_class="UserError",
            error_message="recipe missing required field 'sources'",
        )
        append_run_status(vault, entry)
        recent = read_recent_run_status(vault, limit=1)
        assert recent[0].error_class == "UserError"
        assert recent[0].error_message == "recipe missing required field 'sources'"
