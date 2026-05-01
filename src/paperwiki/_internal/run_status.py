"""Run-status ledger (task 9.167 / decision **D-O**).

Every digest run appends one JSONL line to
``<vault>/.paperwiki/run-status.jsonl`` capturing the outcome — papers
fetched per source, filter drop counts, the final recommendation count,
elapsed time, plus an error class/message when the run failed.

Why this lives in the vault, not in ``~/.config/paperwiki``:

* **Cross-machine portability** (D-O). Obsidian Sync / Syncthing / Git
  carry the vault between devices; the user's run history follows the
  vault rather than getting stranded on whichever machine ran the
  digest.
* **Hidden namespace.** The leading dot on ``.paperwiki/`` keeps the
  directory out of Obsidian's note index, search results, tag pane,
  and graph view — Obsidian skips dotfiles by convention.

Why JSONL, not SQLite or Pydantic + YAML:

* **Append-only is concurrency-safe** at the OS level — a fresh open
  in append mode + single-shot ``write()`` is atomic for sub-page
  writes, which one ledger row always is.
* **Parseable by ``jq``** without a paperwiki binary on hand.
* **Resilient to partial corruption.** A bad line never takes down the
  reader — :func:`read_recent_run_status` skips junk lines so one
  truncated write (e.g. SIGKILL during append) doesn't lose the rest
  of the history.

The schema is locked at v0.4.x; new fields land via additive Pydantic
defaults (Pydantic ``model_validate_json`` ignores unknown keys by
default at v2 — keeps forward-compat through v1.0).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "LEDGER_DIR",
    "LEDGER_FILE",
    "RunStatusEntry",
    "append_run_status",
    "read_recent_run_status",
]


LEDGER_DIR = ".paperwiki"
"""Hidden vault subdirectory paper-wiki uses for its private state.

Obsidian skips leading-dot directories during note indexing, so this
namespace is invisible in the note pane / graph / search. The same
prefix is shared with the v0.4.x dedup ledger (task 9.168) and the
v0.3.43 migration backup (D-9.43.2).
"""

LEDGER_FILE = "run-status.jsonl"
"""One-line-per-run JSONL file under :data:`LEDGER_DIR`."""


class RunStatusEntry(BaseModel):
    """One row in ``<vault>/.paperwiki/run-status.jsonl``.

    Captures both happy-path metrics and a failure reason when the run
    raises. ``source_counts`` and ``filter_drops`` are per-stage so
    downstream consumers (``paperwiki status``, custom Dataview blocks)
    can drill into "which source dried up?" / "did the dedup filter
    suddenly drop everything?" without re-deriving counters.
    """

    model_config = ConfigDict(frozen=False)

    timestamp: datetime
    """Wall-clock time the run completed (timezone-aware UTC by convention)."""

    recipe: str = Field(min_length=1)
    """``recipe.name`` — keys back to the recipe YAML."""

    target_date: datetime
    """The ``RunContext.target_date`` the digest was scoped to."""

    source_counts: dict[str, int] = Field(default_factory=dict)
    """``{source_name: papers_fetched}`` per source."""

    source_errors: dict[str, int] = Field(default_factory=dict)
    """``{source_name: error_count}`` for sources that raised IntegrationError."""

    filter_drops: dict[str, int] = Field(default_factory=dict)
    """``{filter_name: papers_dropped}`` per filter."""

    final_count: int = Field(ge=0)
    """Papers in the final recommendation list (post top_k truncation)."""

    elapsed_ms: int = Field(ge=0)
    """Total elapsed milliseconds for the run."""

    error_class: str | None = None
    """Exception class name if the run failed (e.g. ``"UserError"``)."""

    error_message: str | None = None
    """Exception ``str(exc)`` if the run failed."""

    @field_validator("timestamp", "target_date")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            msg = "timestamp/target_date must be timezone-aware"
            raise ValueError(msg)
        return value


def _ledger_path(vault_path: Path) -> Path:
    return vault_path / LEDGER_DIR / LEDGER_FILE


def append_run_status(vault_path: Path, entry: RunStatusEntry) -> Path:
    """Append a JSONL line to ``<vault>/.paperwiki/run-status.jsonl``.

    Creates ``<vault>/.paperwiki/`` if it does not yet exist. The
    write is single-shot (open in append mode + one ``write()`` call)
    so concurrent digests across recipes interleave at line boundaries
    rather than corrupting each other's payloads.

    Returns the absolute path of the ledger file (mostly for tests).
    """
    ledger = _ledger_path(vault_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = entry.model_dump_json() + "\n"
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return ledger


def read_recent_run_status(vault_path: Path, limit: int = 5) -> list[RunStatusEntry]:
    """Return the most-recent ``limit`` entries (newest first).

    Returns an empty list when the ledger file does not exist —
    fresh-install vaults have no history yet, and that's not an error.

    Corrupt JSONL lines are skipped with a single ``loguru.warning`` per
    bad line so a partial write (e.g. SIGKILL during append) doesn't
    take down the whole reader. The good lines around the bad one are
    still surfaced.
    """
    ledger = _ledger_path(vault_path)
    if not ledger.is_file():
        return []
    try:
        text = ledger.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("run_status.read.failed", path=str(ledger), error=str(exc))
        return []

    entries: list[RunStatusEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entries.append(RunStatusEntry.model_validate_json(line))
        except ValueError as exc:
            logger.warning(
                "run_status.line.skipped",
                path=str(ledger),
                error=str(exc),
                snippet=line[:80],
            )
            continue

    # Newest first; cap at ``limit``.
    entries.reverse()
    return entries[:limit]
