"""``paperwiki.runners.gc_digest_archive`` — clean up old ``.digest-archive/`` files.

The Markdown reporter writes one ``<YYYY-MM-DD>-paper-digest.md`` per
day to ``<vault>/.digest-archive/`` (per the setup wizard's recipe
template). Same-day re-runs idempotently overwrite, different days
accumulate. Sizing: ~30-50 KB per file, ~11-18 MB per year, ~55-90 MB
per 5 years. Not urgent but power users hate hidden-directory growth
they didn't opt into.

Task 9.30 / D-9.30.* deliverables (v0.3.28):

* Default ``--max-age-days = 365`` (D-9.30.3).  CLI users can pass an
  explicit number; common values listed in ``--help``.
* Auto-discover the vault from the user's default recipe at
  ``~/.config/paper-wiki/recipes/daily.yaml`` when ``--vault`` is
  omitted (D-9.30.1).  Explicit ``--vault <path>`` always overrides.
* Scope locked to ``<vault>/.digest-archive/`` only (D-9.30.2).  A
  filename-pattern guard skips anything that doesn't match the
  reporter's output naming so user-added files in the directory are
  preserved.  The runner never touches ``<vault>/Wiki/.cache/`` or any
  other paperwiki state — that's a 9.32 candidate.
* ``--dry-run`` reports what would happen without mutating disk.
* ``--gzip`` compresses files older than the threshold (reversible via
  ``gunzip``) instead of deleting them.

Usage
-----
::

    # Auto-discover vault, dry-run, default 365-day retention:
    paperwiki gc-archive --dry-run

    # Compress everything older than 90 days:
    paperwiki gc-archive --max-age-days 90 --gzip

    # Hard delete files older than 1 year, explicit vault:
    paperwiki gc-archive --vault ~/Documents/Paper-Wiki --max-age-days 365

JSON output (stdout)
--------------------
::

    {
      "vault": "/abs/path/to/vault",
      "archive_dir": "/abs/path/to/vault/.digest-archive",
      "max_age_days": 365,
      "mode": "delete",
      "dry_run": false,
      "removed": ["2024-01-05-paper-digest.md"],
      "gzipped": [],
      "kept": ["2026-04-28-paper-digest.md"],
      "skipped_unrecognized": ["notes.md"],
      "errors": []
    }

The runner is **LLM-free** per SPEC §6: it inspects file mtimes, applies
a regex guard, and either ``unlink`` or ``gzip``. No external network.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
import yaml
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging

app = typer.Typer(
    add_completion=False,
    help="Garbage-collect old <vault>/.digest-archive/<date>-paper-digest.md files.",
    no_args_is_help=False,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARCHIVE_DIRNAME = ".digest-archive"
DEFAULT_MAX_AGE_DAYS = 365  # D-9.30.3

# D-9.30.2: filename pattern guard.  Only files matching this exact regex
# are eligible for GC.  Anything else (user notes, .icloud sync stubs,
# accidentally dropped pdfs) is reported as ``skipped_unrecognized`` and
# left untouched.
ARCHIVE_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-paper-digest\.md(\.gz)?$")

# D-9.30.1: where to look up the vault when --vault is omitted.
DEFAULT_RECIPE_PATH = Path.home() / ".config" / "paper-wiki" / "recipes" / "daily.yaml"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GcReport:
    """Machine-readable summary returned by :func:`gc_archive`."""

    vault: str
    archive_dir: str
    max_age_days: int
    mode: str  # "delete" or "gzip"
    dry_run: bool
    removed: list[str] = field(default_factory=list)
    gzipped: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    skipped_unrecognized: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Vault auto-discovery
# ---------------------------------------------------------------------------


def discover_vault_from_recipe(recipe_path: Path = DEFAULT_RECIPE_PATH) -> Path | None:
    """Return the vault path declared in the user's default recipe.

    The setup wizard generates a recipe whose obsidian reporter has
    ``vault_path: <abs-path>`` and whose markdown reporter has
    ``output_dir: <vault>/.digest-archive``.  We prefer the obsidian
    reporter's ``vault_path`` (canonical) and fall back to deriving the
    vault from the markdown reporter's ``output_dir`` ending in
    ``/.digest-archive``.

    Returns ``None`` if the recipe doesn't exist, is malformed, or
    doesn't carry a vault hint we recognize.  Caller decides what to
    do (CLI exits 2 with a clear message; library callers may want a
    different fallback).
    """
    if not recipe_path.is_file():
        return None
    try:
        data = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    reporters = data.get("reporters")
    if not isinstance(reporters, list):
        return None

    obsidian_vault: str | None = None
    markdown_archive: str | None = None
    for entry in reporters:
        if not isinstance(entry, dict):
            continue
        config = entry.get("config")
        if not isinstance(config, dict):
            continue
        name = entry.get("name")
        if name == "obsidian":
            value = config.get("vault_path")
            if isinstance(value, str):
                obsidian_vault = value
        elif name == "markdown":
            value = config.get("output_dir")
            if isinstance(value, str):
                markdown_archive = value

    if obsidian_vault:
        return Path(obsidian_vault).expanduser()
    if markdown_archive and markdown_archive.endswith("/" + ARCHIVE_DIRNAME):
        return Path(markdown_archive[: -(len(ARCHIVE_DIRNAME) + 1)]).expanduser()
    return None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _is_eligible_archive_file(path: Path) -> bool:
    """Filename pattern guard: only ``<YYYY-MM-DD>-paper-digest.md(.gz)?``."""
    return bool(ARCHIVE_FILENAME_RE.match(path.name))


def _file_age_days(path: Path, *, now: datetime) -> float:
    """Return age of ``path`` in days based on filesystem mtime.

    The runner uses mtime rather than parsing the date out of the
    filename so users who manually rename or copy files still get
    sensible behavior (and we don't have to handle timezone edge
    cases in YYYY-MM-DD).
    """
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return (now - mtime).total_seconds() / 86400


def gc_archive(
    vault: Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
    use_gzip: bool = False,
    now: datetime | None = None,
) -> GcReport:
    """Garbage-collect old digest-archive files under ``<vault>/.digest-archive/``.

    Parameters
    ----------
    vault:
        Path to the user's vault.  ``<vault>/.digest-archive/`` is
        searched.  A missing archive directory is treated as a no-op.
    max_age_days:
        Files whose mtime is older than ``now - max_age_days`` are
        eligible for GC.  Defaults to ``DEFAULT_MAX_AGE_DAYS`` (365).
    dry_run:
        When ``True``, report what would happen without mutating
        disk.  Filenames still appear in the appropriate ``removed``
        / ``gzipped`` lists for user audit.
    use_gzip:
        When ``True``, eligible files are gzip-compressed in place
        (``<file>.md`` -> ``<file>.md.gz``) and the original is
        removed.  Reversible: ``gunzip <file>.md.gz`` restores the
        plaintext.  When ``False`` the eligible file is unlinked.
    now:
        Override "current time" for deterministic testing.  Defaults
        to ``datetime.now(UTC)``.

    Returns
    -------
    :class:`GcReport`
        Machine-readable summary.  ``errors`` is empty on success.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    archive_dir = vault / ARCHIVE_DIRNAME
    report = GcReport(
        vault=str(vault),
        archive_dir=str(archive_dir),
        max_age_days=max_age_days,
        mode="gzip" if use_gzip else "delete",
        dry_run=dry_run,
    )

    if not archive_dir.is_dir():
        logger.debug("gc_archive.no_archive_dir", path=str(archive_dir))
        return report

    threshold = timedelta(days=max_age_days)

    for entry in sorted(archive_dir.iterdir()):
        if not entry.is_file():
            continue
        if not _is_eligible_archive_file(entry):
            report.skipped_unrecognized.append(entry.name)
            continue

        try:
            age_days = _file_age_days(entry, now=now)
        except OSError as exc:
            report.errors.append(f"{entry.name}: stat failed: {exc}")
            continue

        if age_days <= threshold.total_seconds() / 86400:
            report.kept.append(entry.name)
            continue

        # Eligible for GC.
        if use_gzip:
            if entry.name.endswith(".gz"):
                # Already compressed — count as kept; double-gzip is silly.
                report.kept.append(entry.name)
                continue
            target = entry.with_suffix(entry.suffix + ".gz")
            if not dry_run:
                try:
                    with entry.open("rb") as src, gzip.open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    entry.unlink()
                except OSError as exc:
                    report.errors.append(f"{entry.name}: gzip failed: {exc}")
                    continue
            report.gzipped.append(entry.name)
        else:
            if not dry_run:
                try:
                    entry.unlink()
                except OSError as exc:
                    report.errors.append(f"{entry.name}: unlink failed: {exc}")
                    continue
            report.removed.append(entry.name)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command(name="gc-archive")
def main(
    vault: Annotated[
        Path | None,
        typer.Option(
            "--vault",
            help=(
                "Path to the vault (auto-discovers from "
                "~/.config/paper-wiki/recipes/daily.yaml when omitted)."
            ),
        ),
    ] = None,
    max_age_days: Annotated[
        int,
        typer.Option(
            "--max-age-days",
            help=(
                "Files older than this many days are eligible for GC. "
                f"Default {DEFAULT_MAX_AGE_DAYS}. Common values: 90 (3 months), "
                "365 (1 year), 730 (2 years)."
            ),
        ),
    ] = DEFAULT_MAX_AGE_DAYS,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would happen without modifying disk."),
    ] = False,
    use_gzip: Annotated[
        bool,
        typer.Option(
            "--gzip",
            help="Compress old files instead of deleting (reversible via gunzip).",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Clean up old <vault>/.digest-archive/<date>-paper-digest.md files."""
    configure_runner_logging(verbose=verbose)

    resolved_vault: Path | None = vault.expanduser() if vault is not None else None
    if resolved_vault is None:
        # Use the module-level DEFAULT_RECIPE_PATH (not the function's default
        # arg) so test monkeypatching reaches this code path.
        resolved_vault = discover_vault_from_recipe(DEFAULT_RECIPE_PATH)
        if resolved_vault is None:
            typer.echo(
                "paperwiki gc-archive: --vault not provided and could not auto-discover\n"
                f"Looked at: {DEFAULT_RECIPE_PATH}\n"
                "Recipe must declare an obsidian reporter with `vault_path:` or a "
                "markdown reporter with `output_dir:` ending in `/.digest-archive`.\n"
                "Pass --vault <path> explicitly, or run /paper-wiki:setup to create a recipe.",
                err=True,
            )
            raise typer.Exit(2)

    if max_age_days < 0:
        typer.echo("paperwiki gc-archive: --max-age-days must be >= 0", err=True)
        raise typer.Exit(2)

    report = gc_archive(
        resolved_vault,
        max_age_days=max_age_days,
        dry_run=dry_run,
        use_gzip=use_gzip,
    )
    typer.echo(json.dumps(asdict(report), indent=2))

    if report.errors:
        # Surface errors but keep the JSON output clean.
        for err in report.errors:
            typer.echo(f"warning: {err}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()
    sys.exit(0)


__all__ = [
    "DEFAULT_MAX_AGE_DAYS",
    "GcReport",
    "app",
    "discover_vault_from_recipe",
    "gc_archive",
]
