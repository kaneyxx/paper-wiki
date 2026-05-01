"""Anti-repetition dedup ledger (task 9.168 / decisions **D-F** + **D-M**).

The dedup ledger is a vault-bound JSONL file the digest pipeline
consults across runs to avoid re-recommending papers the user has
already seen — silent-drop default per **D-F**, with audit available
via ``paperwiki dedup-list``. Per **D-M** the scope is **vault-global**:
rejecting a paper out of one recipe also drops it from every other
recipe's output that lands in the same vault.

Storage path: ``<vault>/.paperwiki/dedup-ledger.jsonl``. Two action
classes:

* ``surfaced`` — paper appeared in a digest output. Written by the
  digest runner after every successful emit, regardless of recipe.
* ``dismissed`` — user explicitly rejected the paper. Carries an
  optional ``reason`` string for audit display.

Why merge both classes into one ledger rather than separate files?
At the ``DedupKeys`` boundary they're indistinguishable — a paper
that was either surfaced *or* dismissed should not surface again.
Storing one stream keeps the dedup-time read path a single file scan
and the gc step a single sweep.

Retention is bounded by ``PAPERWIKI_DEDUP_LEDGER_KEEP`` (default 365
days). :func:`gc_old_entries` rewrites the file in place dropping
rows older than the cutoff so a multi-year vault doesn't grow
unbounded.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperwiki._internal.normalize import normalize_arxiv_id, normalize_title_key
from paperwiki.plugins.filters.dedup import DedupKeys

__all__ = [
    "DEFAULT_KEEP_DAYS",
    "ENV_KEEP_DAYS",
    "LEDGER_DIR",
    "LEDGER_FILE",
    "DedupLedgerEntry",
    "append_dedup_entry",
    "gc_old_entries",
    "read_dedup_keys",
    "read_dismissed_entries",
]


LEDGER_DIR = ".paperwiki"
"""Hidden vault subdir shared with the run-status ledger (task 9.167)."""

LEDGER_FILE = "dedup-ledger.jsonl"
"""One-line-per-action JSONL file under :data:`LEDGER_DIR`."""

ENV_KEEP_DAYS = "PAPERWIKI_DEDUP_LEDGER_KEEP"
"""Override for :data:`DEFAULT_KEEP_DAYS` via env var."""

DEFAULT_KEEP_DAYS = 365
"""Default retention window for :func:`gc_old_entries`."""


DedupAction = Literal["surfaced", "dismissed"]


class DedupLedgerEntry(BaseModel):
    """One row in ``<vault>/.paperwiki/dedup-ledger.jsonl``.

    ``action`` distinguishes papers the digest emitted (``surfaced``)
    from papers the user explicitly rejected (``dismissed``). Both
    classes feed the same dedup key set per **D-F** — at filter time
    they're indistinguishable; the action only matters for the audit
    surface.
    """

    model_config = ConfigDict(frozen=False)

    timestamp: datetime
    """When the action happened (timezone-aware UTC by convention)."""

    canonical_id: str = Field(min_length=1)
    """``<source>:<id>`` identifier the dedup filter keys off."""

    title: str = Field(min_length=1)
    """Paper title — used for title-key collisions when canonical ids drift."""

    recipe: str = Field(min_length=1)
    """Recipe of origin — keys back to the run-status ledger for cross-ref."""

    action: DedupAction
    """``surfaced`` (digest emit) or ``dismissed`` (user reject)."""

    reason: str | None = None
    """User-supplied reason when ``action == 'dismissed'``; surfaced rows leave it None."""

    @field_validator("timestamp")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            msg = "timestamp must be timezone-aware"
            raise ValueError(msg)
        return value


def _ledger_path(vault_path: Path) -> Path:
    return vault_path / LEDGER_DIR / LEDGER_FILE


def append_dedup_entry(vault_path: Path, entry: DedupLedgerEntry) -> Path:
    """Append a JSONL line to ``<vault>/.paperwiki/dedup-ledger.jsonl``.

    Creates ``<vault>/.paperwiki/`` if missing. Returns the absolute
    path of the ledger file (mostly for tests).
    """
    ledger = _ledger_path(vault_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = entry.model_dump_json() + "\n"
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return ledger


def _iter_ledger(vault_path: Path) -> list[DedupLedgerEntry]:
    """Read every entry from the ledger, skipping bad lines.

    Returns an empty list when the ledger file does not yet exist —
    fresh-install vaults have no history, and that's not an error.
    """
    ledger = _ledger_path(vault_path)
    if not ledger.is_file():
        return []
    try:
        text = ledger.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("dedup_ledger.read.failed", path=str(ledger), error=str(exc))
        return []

    entries: list[DedupLedgerEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entries.append(DedupLedgerEntry.model_validate_json(line))
        except ValueError as exc:
            logger.warning(
                "dedup_ledger.line.skipped",
                path=str(ledger),
                error=str(exc),
                snippet=line[:80],
            )
    return entries


def read_dedup_keys(vault_path: Path) -> DedupKeys:
    """Return the union of arxiv ids + title keys for every ledger entry.

    Both ``surfaced`` and ``dismissed`` rows feed this set per **D-F**:
    once a paper enters the ledger it stops surfacing, no matter why
    it got there.
    """
    arxiv_ids: set[str] = set()
    title_keys: set[str] = set()
    for entry in _iter_ledger(vault_path):
        if entry.canonical_id.startswith("arxiv:"):
            id_part = entry.canonical_id.split(":", 1)[1]
            normalized = normalize_arxiv_id(id_part)
            if normalized is not None:
                arxiv_ids.add(normalized)
        title_key = normalize_title_key(entry.title)
        if title_key is not None:
            title_keys.add(title_key)
    return DedupKeys(
        arxiv_ids=frozenset(arxiv_ids),
        title_keys=frozenset(title_keys),
    )


def read_dismissed_entries(vault_path: Path) -> list[DedupLedgerEntry]:
    """Return every ledger row with ``action == 'dismissed'``, oldest first.

    Used by ``paperwiki dedup-list`` to render the audit table.
    """
    return [e for e in _iter_ledger(vault_path) if e.action == "dismissed"]


def _resolve_keep_days(override: int | None) -> int:
    if override is not None:
        return override
    raw = os.environ.get(ENV_KEEP_DAYS)
    if not raw:
        return DEFAULT_KEEP_DAYS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "dedup_ledger.keep_days.invalid",
            env=ENV_KEEP_DAYS,
            value=raw,
            fallback=DEFAULT_KEEP_DAYS,
        )
        return DEFAULT_KEEP_DAYS
    return max(value, 0)


def gc_old_entries(vault_path: Path, *, keep_days: int | None = None) -> int:
    """Drop ledger rows older than ``keep_days``.

    Rewrites the ledger atomically (write to temp, rename over) so a
    SIGKILL mid-sweep can never produce a half-written file. Returns
    the number of rows deleted.

    ``keep_days`` resolution order: explicit arg > ``PAPERWIKI_DEDUP_LEDGER_KEEP``
    env > :data:`DEFAULT_KEEP_DAYS` (365). Setting ``keep_days=0`` is
    legal and clears the entire ledger.
    """
    ledger = _ledger_path(vault_path)
    if not ledger.is_file():
        return 0

    days = _resolve_keep_days(keep_days)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    entries = _iter_ledger(vault_path)
    kept = [e for e in entries if e.timestamp >= cutoff]
    deleted = len(entries) - len(kept)

    if deleted == 0:
        return 0

    # Atomic rewrite — temp file in the same dir then os.replace.
    fd, tmp_path = tempfile.mkstemp(prefix=".dedup-ledger.", suffix=".jsonl.tmp", dir=ledger.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for entry in kept:
                fh.write(entry.model_dump_json() + "\n")
        os.replace(tmp_path, ledger)
    except OSError:
        # Best-effort cleanup so we don't leave stray temp files.
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return deleted
