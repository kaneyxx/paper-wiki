"""``paperwiki.runners.gc_bak`` — clean up old ``<ver>.bak.<ts>/`` cache directories.

Each ``paperwiki update`` renames the previous cache version to
``<ver>.bak.<UTC-timestamp>/`` so the user has a rollback target.
These accumulate forever without cleanup. v0.3.29 (Task 9.33 /
D-9.33.*) ships this runner so power users can prune the history
explicitly, and ``paperwiki update`` calls it post-success with the
``PAPERWIKI_BAK_KEEP`` retention default (``3`` per D-9.33.1).

CLI
---
::

    paperwiki gc-bak [--cache-root <path>]
                     [--keep-recent N]
                     [--max-age-days N]
                     [--dry-run]
                     [-v]

When neither ``--keep-recent`` nor ``--max-age-days`` is supplied, the
runner resolves ``--keep-recent`` from ``$PAPERWIKI_BAK_KEEP`` (default
``3``). Setting ``PAPERWIKI_BAK_KEEP=0`` is the escape hatch: with no
explicit flag, the runner skips cleanup entirely (preserves all .bak).

Combined modes (intersection): when both ``--keep-recent`` and
``--max-age-days`` are supplied, a .bak is removed only if it falls
OUTSIDE the recent-N window AND is older than the age threshold.
That way "I rolled back two versions, please don't prune them yet"
remains safe.

Filename guard (D-9.33.2): only directories matching
``^\\d+\\.\\d+\\.\\d+\\.bak\\.\\d{8}T\\d{6}Z$`` are eligible. Anything
else (active cache version, user-added directories, recovery copies)
is preserved and surfaced under ``skipped_unrecognized``.

JSON output to stdout::

    {
      "cache_root": "/abs/path/to/cache/paper-wiki/paper-wiki",
      "keep_recent": 3,
      "max_age_days": null,
      "dry_run": false,
      "removed": ["0.3.25.bak.20260201T000000Z"],
      "kept": ["0.3.28.bak.20260428T150731Z", "0.3.27.bak.20260301T000000Z",
               "0.3.26.bak.20260101T000000Z"],
      "skipped_unrecognized": ["0.3.29", "user-notes"],
      "errors": []
    }
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging

app = typer.Typer(
    add_completion=False,
    help="Garbage-collect old <ver>.bak.<ts>/ cache directories.",
    no_args_is_help=False,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BAK_KEEP = 3  # D-9.33.1
DEFAULT_CACHE_ROOT = Path.home() / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"

# D-9.33.2 — filename pattern guard. Only directories matching this
# exact regex are eligible for GC. Active cache versions
# ("0.3.28") are intentionally NOT eligible — only `.bak.<ts>` ones.
BAK_FILENAME_RE = re.compile(r"^\d+\.\d+\.\d+\.bak\.\d{8}T\d{6}Z$")

# Pattern used inside `<ver>.bak.<YYYYMMDDTHHMMSSZ>` to recover the
# timestamp for ordering (sort the matched group as a string — UTC
# timestamps in this format sort lexicographically).
_BAK_TIMESTAMP_RE = re.compile(r"\.bak\.(\d{8}T\d{6}Z)$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GcBakReport:
    """Machine-readable summary returned by :func:`gc_bak`."""

    cache_root: str
    keep_recent: int | None
    max_age_days: int | None
    dry_run: bool
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    skipped_unrecognized: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _is_eligible_bak(path: Path) -> bool:
    return path.is_dir() and bool(BAK_FILENAME_RE.match(path.name))


def _bak_age_days(path: Path, *, now: datetime) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return (now - mtime).total_seconds() / 86400


def _sort_key(name: str) -> str:
    """Sort key for .bak names — extract the UTC timestamp suffix.

    UTC timestamps in ``YYYYMMDDTHHMMSSZ`` format sort
    lexicographically, so newest is the last element after sorting.
    """
    match = _BAK_TIMESTAMP_RE.search(name)
    return match.group(1) if match else ""


def gc_bak(
    cache_root: Path,
    *,
    keep_recent: int | None = None,
    max_age_days: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> GcBakReport:
    """Garbage-collect ``<ver>.bak.<ts>`` directories under ``cache_root``.

    Parameters
    ----------
    cache_root:
        ``~/.claude/plugins/cache/paper-wiki/paper-wiki/`` typically.
        Missing directories are treated as a no-op.
    keep_recent:
        Number of newest .bak directories to preserve. ``None`` =
        retention by age only (use ``max_age_days``). ``0`` = remove
        all .bak.
    max_age_days:
        Remove .bak directories whose mtime is older than this many
        days. ``None`` = no age check (use ``keep_recent``).
    dry_run:
        Report what would happen without modifying disk.
    now:
        Override "current time" for deterministic testing.

    Returns
    -------
    :class:`GcBakReport`
        Lists of removed / kept / skipped names + any errors.

    Notes
    -----
    When BOTH ``keep_recent`` and ``max_age_days`` are supplied, a
    .bak is removed only if it satisfies BOTH conditions
    (outside the recent-N window AND older than threshold). When
    only one is supplied, the other check is short-circuited as
    "always keep" / "always eligible by age".

    When BOTH are ``None``, the runner removes nothing — caller is
    expected to populate at least one of them. (The CLI defaults
    ``keep_recent`` to 3 unless the user explicitly opts out.)
    """
    if now is None:
        now = datetime.now(tz=UTC)

    report = GcBakReport(
        cache_root=str(cache_root),
        keep_recent=keep_recent,
        max_age_days=max_age_days,
        dry_run=dry_run,
    )

    if not cache_root.is_dir():
        logger.debug("gc_bak.no_cache_root", path=str(cache_root))
        return report

    # Partition entries into eligible (matches BAK_FILENAME_RE) and
    # unrecognized (everything else, including active cache versions).
    eligible: list[Path] = []
    for entry in sorted(cache_root.iterdir()):
        if _is_eligible_bak(entry):
            eligible.append(entry)
        else:
            report.skipped_unrecognized.append(entry.name)

    # Sort eligible by timestamp (newest last after asc sort).
    eligible.sort(key=lambda p: _sort_key(p.name))

    # "keep_by_recent": newest N when keep_recent is set, otherwise empty
    # (no opinion from this knob).
    keep_by_recent: set[str] = set()
    if keep_recent is not None and keep_recent > 0:
        keep_by_recent = {p.name for p in eligible[-keep_recent:]}

    # "remove_by_age": anything older than max_age_days when set.
    remove_by_age: set[str] = set()
    if max_age_days is not None:
        threshold_days = float(max_age_days)
        for entry in eligible:
            try:
                age = _bak_age_days(entry, now=now)
            except OSError as exc:
                report.errors.append(f"{entry.name}: stat failed: {exc}")
                continue
            if age > threshold_days:
                remove_by_age.add(entry.name)

    # Remove decision: when both knobs supplied, intersection (must
    # satisfy both). When only one supplied, that one decides. When
    # neither, nothing removed.
    for entry in eligible:
        recent_says_remove = (keep_recent is not None) and (entry.name not in keep_by_recent)
        age_says_remove = (max_age_days is not None) and (entry.name in remove_by_age)

        if keep_recent is not None and max_age_days is not None:
            should_remove = recent_says_remove and age_says_remove
        elif keep_recent is not None:
            should_remove = recent_says_remove
        elif max_age_days is not None:
            should_remove = age_says_remove
        else:
            should_remove = False  # neither knob supplied → no-op

        if should_remove:
            if not dry_run:
                try:
                    shutil.rmtree(entry)
                except OSError as exc:
                    report.errors.append(f"{entry.name}: rmtree failed: {exc}")
                    continue
            report.removed.append(entry.name)
        else:
            report.kept.append(entry.name)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_default_keep_recent() -> int:
    """Read ``PAPERWIKI_BAK_KEEP`` env var; fall back to ``DEFAULT_BAK_KEEP``.

    Returns the int retention count. ``"0"`` is preserved as ``0``
    (escape hatch). Malformed values fall back to ``DEFAULT_BAK_KEEP``
    after a one-line warning.
    """
    raw = os.environ.get("PAPERWIKI_BAK_KEEP")
    if raw is None or raw == "":
        return DEFAULT_BAK_KEEP
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "gc_bak.invalid_paperwiki_bak_keep",
            value=raw,
            fallback=DEFAULT_BAK_KEEP,
        )
        return DEFAULT_BAK_KEEP


@app.command(name="gc-bak")
def main(
    cache_root: Annotated[
        Path,
        typer.Option(
            "--cache-root",
            help=(
                "Path to the paper-wiki plugin cache root. Defaults to "
                "~/.claude/plugins/cache/paper-wiki/paper-wiki."
            ),
        ),
    ] = DEFAULT_CACHE_ROOT,
    keep_recent: Annotated[
        int | None,
        typer.Option(
            "--keep-recent",
            help=(
                "Keep this many newest .bak directories; remove the rest. "
                f"Default: $PAPERWIKI_BAK_KEEP env var, fallback {DEFAULT_BAK_KEEP}. "
                "Set 0 to remove all .bak (or to disable auto-cleanup when no other flag is set)."
            ),
        ),
    ] = None,
    max_age_days: Annotated[
        int | None,
        typer.Option(
            "--max-age-days",
            help=(
                "Remove .bak directories older than this many days. "
                "Combine with --keep-recent for an intersection (remove only "
                "if BOTH agree). Default: not applied."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would happen without modifying disk."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Clean up old <ver>.bak.<ts>/ directories under the plugin cache root."""
    configure_runner_logging(verbose=verbose)

    # Default keep-recent comes from PAPERWIKI_BAK_KEEP env var when the
    # user didn't pass an explicit flag and no --max-age-days either.
    # PAPERWIKI_BAK_KEEP=0 + no other flag = escape hatch (skip cleanup).
    if keep_recent is None and max_age_days is None:
        env_keep = _resolve_default_keep_recent()
        if env_keep == 0:
            # Escape hatch — preserve everything.
            report = GcBakReport(
                cache_root=str(cache_root),
                keep_recent=0,
                max_age_days=None,
                dry_run=dry_run,
            )
            # Still surface the existing state for visibility.
            if cache_root.is_dir():
                for entry in sorted(cache_root.iterdir()):
                    if _is_eligible_bak(entry):
                        report.kept.append(entry.name)
                    else:
                        report.skipped_unrecognized.append(entry.name)
            typer.echo(json.dumps(asdict(report), indent=2))
            return
        keep_recent = env_keep

    if keep_recent is not None and keep_recent < 0:
        typer.echo("paperwiki gc-bak: --keep-recent must be >= 0", err=True)
        raise typer.Exit(2)
    if max_age_days is not None and max_age_days < 0:
        typer.echo("paperwiki gc-bak: --max-age-days must be >= 0", err=True)
        raise typer.Exit(2)

    report = gc_bak(
        cache_root,
        keep_recent=keep_recent,
        max_age_days=max_age_days,
        dry_run=dry_run,
    )
    typer.echo(json.dumps(asdict(report), indent=2))

    if report.errors:
        for err in report.errors:
            typer.echo(f"warning: {err}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()
    sys.exit(0)


__all__ = [
    "BAK_FILENAME_RE",
    "DEFAULT_BAK_KEEP",
    "DEFAULT_CACHE_ROOT",
    "GcBakReport",
    "app",
    "gc_bak",
]
