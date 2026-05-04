"""``paperwiki.runners.migrate_recipe`` — upgrade stale personal recipes.

The setup wizard generates a personal ``~/.config/paper-wiki/recipes/daily.yaml``
copy of the bundled template.  When bundled keywords change (e.g. v0.3.17
dropped ``foundation model`` from ``biomedical-pathology`` to stop matching
every ML paper), the personal copy stays stale until the user re-runs the
wizard or runs this runner.

Usage
-----
::

    # Preview what would change (no writes):
    paperwiki migrate-recipe ~/.config/paper-wiki/recipes/daily.yaml --dry-run

    # Apply in-place (creates a timestamped backup first):
    paperwiki migrate-recipe ~/.config/paper-wiki/recipes/daily.yaml

Output (JSON to stdout)
-----------------------
::

    {
      "recipe_path": "/path/to/daily.yaml",
      "target_version": "0.3.17",
      "applied_changes": [
        {
          "topic_name": "biomedical-pathology",
          "removed_keywords": ["foundation model"],
          "added_keywords": []
        }
      ],
      "backup_path": "/path/to/daily.yaml.bak.20260428143012",
      "skipped_migrations": ["0.3.17 (already up to date)"]
    }

Idempotency
-----------
Re-running on an already-migrated recipe emits ``applied_changes: []`` and
exits 0.  The ``backup_path`` is ``null`` when no changes were needed.

The runner is **LLM-free** per SPEC §6: it diffs two keyword lists and
applies the surgical removals/additions.  No external network calls.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from loguru import logger

from paperwiki import __version__
from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.recipe_migrations import RECIPE_MIGRATIONS, TopicMigration
from paperwiki.core.errors import UserError

PRE_V04_BAK_SUFFIX = ".pre-v04.bak"

# D-Y round-trip stamp regex: matches a single stamp line at the very
# top of the file (no leading whitespace). Used to detect-and-replace
# rather than detect-and-stack on repeat invocations.
_STAMP_RE = re.compile(r"^# round-trip stamp \d{4}-\d{2}-\d{2} v\d+\.\d+\.\d+\n")

# Pre-v0.4 scorer-axis names — presence at ``scorer.config.weights`` is
# the trigger for the v0.4 schema migration (Task 9.190).
_PRE_V04_AXES = frozenset({"keyword", "category", "recency"})

app = typer.Typer(
    add_completion=False,
    help="Surgically update a personal recipe to the latest template keywords.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AppliedChange:
    """Per-topic record of what was changed."""

    topic_name: str
    removed_keywords: list[str] = field(default_factory=list)
    added_keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MigrateRecipeReport:
    """Machine-readable summary returned by :func:`migrate_recipe_file`."""

    recipe_path: str
    target_version: str
    applied_changes: list[AppliedChange] = field(default_factory=list)
    backup_path: str | None = None
    skipped_migrations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def migrate_recipe_file(
    recipe_path: Path,
    *,
    dry_run: bool = False,
    target_version: str = "0.3.17",
) -> MigrateRecipeReport:
    """Apply all known migrations up to *target_version* to *recipe_path*.

    Two migration tiers run in order:

    1. **v0.4 schema migration** (Task 9.190): when the recipe still
       carries pre-v0.4 scorer axes (``keyword``/``category``/``recency``),
       create ``<recipe>.pre-v04.bak`` and rewrite ``scorer.config.weights``
       via :func:`map_pre_v04_to_v04_weights`. Refuses when the .bak
       already exists (Task 9.189).
    2. **Keyword migrations** (v0.3.17 and earlier): the existing
       :data:`RECIPE_MIGRATIONS` table is applied to topic-keyword lists.
       This tier preserves the historical behavior — timestamped backups
       written by :func:`_write_with_backup`.

    The D-Y round-trip stamp (``# round-trip stamp YYYY-MM-DD vX.Y.Z``)
    is appended (or replaced) at the top of the file at the very end —
    so even a recipe that's already at the current schema gets a fresh
    stamp confirming the user opted into the current version.

    Parameters
    ----------
    recipe_path:
        Path to the personal recipe YAML to migrate.
    dry_run:
        When ``True``, compute the diff but do not write the file, create
        a backup, or stamp. The returned report reflects what *would*
        have changed.
    target_version:
        The latest migration version to apply. Defaults to ``"0.3.17"``,
        the latest keyword-migration version defined today. Pass a
        specific version to limit the scope (useful in tests). The v0.4
        schema migration is independent of this knob — it always runs
        when pre-v0.4 axes are present.

    Returns
    -------
    :class:`MigrateRecipeReport`
        Structured summary of what changed (or would change).
    """
    text = recipe_path.read_text(encoding="utf-8")
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"migrate-recipe: {recipe_path} is not valid YAML: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(data, dict):
        msg = f"migrate-recipe: {recipe_path} must be a YAML mapping"
        raise ValueError(msg)

    report = MigrateRecipeReport(
        recipe_path=str(recipe_path),
        target_version=target_version,
    )

    # Tier 1: v0.4 schema migration (Task 9.190 / 9.189). Detect first so
    # we can refuse cleanly if a stale .pre-v04.bak is already present
    # before any other state mutation.
    schema_migrated = _has_pre_v04_weights(data)
    if schema_migrated and not dry_run:
        # Refuses with UserError when the bak already exists.
        create_pre_v04_backup(recipe_path)
        _apply_v04_schema_migration(data)
        # Persist the schema-migrated YAML before keyword-tier touches it.
        new_text = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        recipe_path.write_text(new_text, encoding="utf-8")
        # Reload so subsequent steps work on the persisted form.
        data = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
        report.backup_path = str(_pre_v04_bak_path(recipe_path))

    # Tier 2: keyword migrations (legacy v0.3.17 era).
    applicable = {
        version: migrations
        for version, migrations in RECIPE_MIGRATIONS.items()
        if version <= target_version
    }

    for version, migrations in sorted(applicable.items()):
        changes = _apply_migrations(data, migrations)
        if not changes:
            report.skipped_migrations.append(
                f"{version} (no matching topics or already up to date)"
            )
        else:
            report.applied_changes.extend(changes)

    if dry_run:
        return report

    # Write keyword-tier changes when applicable. Keyword tier still uses
    # the legacy timestamped backup so multi-pivot history is preserved.
    if report.applied_changes:
        backup_path = _write_with_backup(recipe_path, data)
        # Keyword-tier backup is **secondary** to schema-tier .pre-v04.bak;
        # only override when no schema migration ran.
        if not schema_migrated:
            report.backup_path = str(backup_path)

    # D-Y stamp — always applied so "did the user opt into the current
    # schema?" is a one-line grep against the recipe.
    stamp_round_trip(recipe_path)

    return report


def _apply_migrations(
    data: dict[str, Any],
    migrations: list[TopicMigration],
) -> list[AppliedChange]:
    """Apply *migrations* to the in-memory recipe dict.

    Mutates ``data`` in-place.  Returns a list of :class:`AppliedChange`
    records for any topic that had at least one keyword removed or added.
    """
    changes: list[AppliedChange] = []

    # Gather all topic blocks from sources/filters/scorer.reporters sections.
    topic_blocks = _collect_topic_blocks(data)

    for migration in migrations:
        for topic_block in topic_blocks:
            name = (topic_block.get("name") or "").strip()
            if name != migration.topic_name:
                continue

            keywords_raw = topic_block.get("keywords")
            if not isinstance(keywords_raw, list):
                continue

            # Normalise existing keywords for comparison.
            existing_lower = {kw.lower().strip(): kw for kw in keywords_raw if isinstance(kw, str)}

            removed: list[str] = []
            for kw in migration.remove:
                key = kw.lower().strip()
                if key in existing_lower:
                    keywords_raw.remove(existing_lower[key])
                    removed.append(existing_lower[key])

            added: list[str] = []
            for kw in migration.add:
                key = kw.lower().strip()
                if key not in existing_lower:
                    keywords_raw.append(kw)
                    added.append(kw)

            if removed or added:
                changes.append(
                    AppliedChange(
                        topic_name=name,
                        removed_keywords=removed,
                        added_keywords=added,
                    )
                )

    return changes


def _collect_topic_blocks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk the recipe structure and return all topic dicts.

    Topics appear nested inside ``filters[].config.topics`` and
    ``scorer.config.topics``.
    """
    blocks: list[dict[str, Any]] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "name" in obj and "keywords" in obj:
                blocks.append(obj)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return blocks


def _write_with_backup(recipe_path: Path, data: dict[str, Any]) -> Path:
    """Write *data* back to *recipe_path*, creating a timestamped backup first.

    Returns the path of the backup file.  Backup names are unique by
    timestamp (second granularity) so repeated runs never overwrite each other.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = recipe_path.with_name(f"{recipe_path.name}.bak.{ts}")

    # Atomic: rename original to backup, then write new content.
    recipe_path.rename(backup_path)

    new_text = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    recipe_path.write_text(new_text, encoding="utf-8")
    logger.debug("migrate_recipe.backup_created", backup=str(backup_path))
    return backup_path


# ---------------------------------------------------------------------------
# v0.4 schema mapping + D-Y round-trip stamp (Task 9.190)
# ---------------------------------------------------------------------------

_RELEVANCE_FLOOR = 0.4
_RELEVANCE_CEILING = 0.85
_NOVELTY_DEFAULT = 0.10
_RIGOR_DEFAULT = 0.05


def map_pre_v04_to_v04_weights(old: dict[str, float]) -> dict[str, float]:
    """Map pre-v0.4 ``keyword/category/recency`` weights → v0.4 axes.

    Rule (locked in plan §3.5.3 Step 2):

    * ``relevance = clip(keyword + 0.5 * category, 0.4, 0.85)``
    * ``novelty = 0.10`` (conservative default for "user never opted in")
    * ``rigor = 0.05`` (same rationale)
    * ``momentum = max(0, 1 - relevance - novelty - rigor)`` — absorbs the
      residual so the four axes sum to 1.0.
    * ``recency`` is silently dropped — recency is now a filter, not a
      scorer axis. The caller preserves the recipe's existing recency
      filter block separately.

    All output values rounded to two decimal places so the resulting
    YAML reads cleanly to humans.
    """
    keyword = float(old.get("keyword", 0.0))
    category = float(old.get("category", 0.0))

    relevance = max(_RELEVANCE_FLOOR, min(_RELEVANCE_CEILING, keyword + 0.5 * category))
    novelty = _NOVELTY_DEFAULT
    rigor = _RIGOR_DEFAULT
    momentum = max(0.0, 1.0 - relevance - novelty - rigor)

    return {
        "relevance": round(relevance, 2),
        "novelty": round(novelty, 2),
        "momentum": round(momentum, 2),
        "rigor": round(rigor, 2),
    }


def _has_pre_v04_weights(data: dict[str, Any]) -> bool:
    """Detect whether a parsed recipe dict carries pre-v0.4 scorer axes.

    Returns ``True`` when ``scorer.config.weights`` contains *any* of
    ``keyword`` / ``category`` / ``recency``.
    """
    scorer = data.get("scorer")
    if not isinstance(scorer, dict):
        return False
    config = scorer.get("config")
    if not isinstance(config, dict):
        return False
    weights = config.get("weights")
    if not isinstance(weights, dict):
        return False
    return any(axis in weights for axis in _PRE_V04_AXES)


def stamp_round_trip(recipe_path: Path) -> None:
    """Append (or replace) the D-Y ``# round-trip stamp`` line at file top.

    The stamp line embeds the current ``paperwiki.__version__`` and today's
    UTC date. Multiple consecutive runs **replace** the existing stamp
    rather than stacking, so a long-lived recipe that gets touched on
    every release still has exactly one stamp.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    stamp_line = f"# round-trip stamp {today} v{__version__}\n"

    text = recipe_path.read_text(encoding="utf-8")
    if _STAMP_RE.match(text):
        new_text = _STAMP_RE.sub(stamp_line, text, count=1)
    else:
        new_text = stamp_line + text
    recipe_path.write_text(new_text, encoding="utf-8")


def _apply_v04_schema_migration(data: dict[str, Any]) -> dict[str, float] | None:
    """Replace pre-v0.4 weights with v0.4 axes in-place.

    Returns the new weights dict so the caller can include it in a
    structured report, or ``None`` when the recipe doesn't carry
    pre-v0.4 axes (no-op).
    """
    if not _has_pre_v04_weights(data):
        return None
    weights: dict[str, Any] = data["scorer"]["config"]["weights"]
    pre = {k: weights[k] for k in _PRE_V04_AXES if k in weights}
    new_weights = map_pre_v04_to_v04_weights(pre)
    # Replace in-place — drop legacy keys, add new keys.
    for k in list(weights.keys()):
        if k in _PRE_V04_AXES:
            del weights[k]
    weights.update(new_weights)
    return new_weights


# ---------------------------------------------------------------------------
# Pre-v0.4 schema migration backup helpers (Task 9.189 / D-W companion)
# ---------------------------------------------------------------------------


def _pre_v04_bak_path(recipe_path: Path) -> Path:
    """Return the canonical ``<recipe>.pre-v04.bak`` path next to *recipe_path*.

    The suffix is one-shot: if the .bak already exists, ``create_pre_v04_backup``
    refuses rather than overwriting. This is intentional — the .bak is the
    "what I had before v0.4" anchor, and the user must consciously remove it
    (or ``--restore``) before re-migrating.
    """
    return recipe_path.with_name(recipe_path.name + PRE_V04_BAK_SUFFIX)


def create_pre_v04_backup(recipe_path: Path) -> Path:
    """Copy *recipe_path* to ``<recipe>.pre-v04.bak`` byte-for-byte.

    Refuses when the .bak already exists so the user gets a clear signal
    that they've already migrated this recipe once. The intended fix is
    either ``--restore`` (revert and try again) or manual deletion of the
    stale .bak (if the user is sure their current recipe is the wanted state).

    Returns the path of the backup that was just written.

    Raises
    ------
    UserError
        When the .bak already exists.
    """
    bak = _pre_v04_bak_path(recipe_path)
    if bak.exists():
        raise UserError(
            f"migrate-recipe: backup already exists at {bak}. "
            f"Run `paperwiki migrate-recipe {recipe_path} --restore` to revert "
            f"to that backup, or delete {bak.name} manually before re-migrating."
        )
    bak.write_bytes(recipe_path.read_bytes())
    logger.debug("migrate_recipe.pre_v04_bak.created", path=str(bak))
    return bak


def restore_pre_v04_backup(recipe_path: Path) -> Path:
    """Replace *recipe_path* contents with ``<recipe>.pre-v04.bak`` bytes,
    then remove the .bak (one-shot).

    Returns *recipe_path* (the file that was just restored). Raises
    ``UserError`` if no .bak exists.
    """
    bak = _pre_v04_bak_path(recipe_path)
    if not bak.exists():
        raise UserError(f"migrate-recipe --restore: no backup found at {bak}. Nothing to restore.")
    recipe_path.write_bytes(bak.read_bytes())
    bak.unlink()
    logger.info("migrate_recipe.pre_v04_bak.restored", recipe=str(recipe_path))
    return recipe_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command(name="migrate-recipe")
def main(
    recipe: Annotated[Path, typer.Argument(help="Path to the personal recipe YAML to migrate.")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show diff without writing (no backup created)."),
    ] = False,
    restore: Annotated[
        bool,
        typer.Option(
            "--restore",
            help=(
                "Revert the recipe to its pre-v0.4 state from "
                "<recipe>.pre-v04.bak (Task 9.189). Mutually exclusive with "
                "the normal migration flow."
            ),
        ),
    ] = False,
    target_version: Annotated[
        str,
        typer.Option(
            "--target-version",
            help="Migrate up to this version (default: 0.3.17).",
        ),
    ] = "0.3.17",
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Apply surgical keyword updates to a personal recipe without re-running setup."""
    configure_runner_logging(verbose=verbose)

    if not recipe.is_file():
        typer.echo(f"migrate-recipe: recipe not found: {recipe}", err=True)
        raise typer.Exit(1)

    if restore:
        try:
            restore_pre_v04_backup(recipe)
        except UserError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(exc.exit_code) from exc
        typer.echo(json.dumps({"recipe_path": str(recipe), "action": "restored"}, indent=2))
        return

    try:
        report = migrate_recipe_file(recipe, dry_run=dry_run, target_version=target_version)
    except (ValueError, OSError) as exc:
        logger.error("migrate_recipe.failed", error=str(exc))
        typer.echo(f"migrate-recipe: {exc}", err=True)
        raise typer.Exit(1) from exc

    # Serialise dataclasses to plain dicts for JSON output.
    output = {
        "recipe_path": report.recipe_path,
        "target_version": report.target_version,
        "applied_changes": [asdict(c) for c in report.applied_changes],
        "backup_path": report.backup_path,
        "skipped_migrations": report.skipped_migrations,
    }
    typer.echo(json.dumps(output, indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = [
    "PRE_V04_BAK_SUFFIX",
    "AppliedChange",
    "MigrateRecipeReport",
    "app",
    "create_pre_v04_backup",
    "main",
    "map_pre_v04_to_v04_weights",
    "migrate_recipe_file",
    "restore_pre_v04_backup",
    "stamp_round_trip",
]
