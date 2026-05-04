"""``paperwiki.runners.migrate_v04`` — legacy ``Wiki/sources/`` → typed-subdir migration.

Phase 1 task 9.160 of the v0.4.x consensus plan. Moves the v0.3.x flat
``<vault>/Wiki/sources/<id>.md`` layout into the v0.4.x typed-subdir
layout (D-I) at ``<vault>/Wiki/papers/<id>.md``, with a SHA-256
manifest backup written to
``<vault>/.paperwiki/migration-backup/<ts>/`` so the move can be
reversed via :func:`restore` (R3).

Per consensus plan iter-2 R14: the backup uses :func:`shutil.copy2`
(not :func:`shutil.move`) to preserve the original files until the
typed-subdir move succeeds. Per Scenario 5, this is the only
release-gate criterion *added* to the migration scope — rollback must
be guaranteed-working before tag.

Per **D-J**, migration is default-on with a
``PAPERWIKI_NO_AUTO_MIGRATE=1`` escape hatch.

Concept / Topic / Person synthesis is intentionally NOT performed
here. Per **D-K**, those entities are auto-extracted by Claude during
``digest`` / ``analyze`` SKILL passes (LLM in SKILL, not in Python).
This runner only relocates existing paper notes — it never generates
new entities.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError

ENV_NO_AUTO_MIGRATE = "PAPERWIKI_NO_AUTO_MIGRATE"
PAPERWIKI_DIR = ".paperwiki"
MIGRATION_BACKUP_SUBDIR = "migration-backup"
LEGACY_SOURCES_SUBDIR = "sources"
TYPED_PAPERS_SUBDIR = "papers"
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class _PlannedMove:
    src: Path
    dst: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class _PlannedDirMove:
    """Phase B.1 hot-fix (Task 9.187 follow-up): per-paper image
    subdirectories under ``Wiki/sources/<id>/`` (typically
    ``extract-images`` output) need to follow the ``.md`` migration
    so the canonical ``Wiki/papers/<id>/`` layout is structurally
    consistent. SHA-256 is intentionally per-FILE on the
    ``_PlannedMove`` side; directory moves get a recursive
    ``shutil.copytree`` backup but no aggregate hash — restore
    integrity comes from the directory tree round-tripping
    byte-identical via ``copytree`` semantics.
    """

    src: Path
    dst: Path


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Result of :func:`dry_run`: planned moves without filesystem touch."""

    planned_moves: list[_PlannedMove]
    planned_dir_moves: list[_PlannedDirMove] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Result of :func:`migrate`: actual moves + backup metadata."""

    moved_count: int
    backup_timestamp: str
    backup_dir: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def needs_migration(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> bool:
    """Return True iff ``Wiki/sources/`` has user data AND ``Wiki/papers/`` is absent.

    Phase B.1 hot-fix (caught on 2026-05-04 maintainer smoke): "user
    data" includes BOTH ``*.md`` paper notes AND per-paper image
    subdirectories (``Wiki/sources/<id>/``). Pre-fix, a vault that
    had been partially migrated by hand (``.md`` files moved but
    image dirs left behind) would report ``needs_migration == False``
    and never auto-recover.

    Idempotency anchor — a second invocation of :func:`migrate` after
    the first run must report no work to do.
    """
    sources = vault_path / wiki_subdir / LEGACY_SOURCES_SUBDIR
    papers = vault_path / wiki_subdir / TYPED_PAPERS_SUBDIR
    if not sources.is_dir():
        return False
    has_md = any(sources.glob("*.md"))
    has_subdirs = any(p.is_dir() for p in sources.iterdir())
    if not has_md and not has_subdirs:
        return False
    return not papers.exists()


def _enumerate_legacy_files(vault_path: Path, wiki_subdir: str) -> list[Path]:
    sources = vault_path / wiki_subdir / LEGACY_SOURCES_SUBDIR
    return sorted(p for p in sources.glob("*.md") if not p.name.startswith("."))


def _enumerate_legacy_subdirs(vault_path: Path, wiki_subdir: str) -> list[Path]:
    """Phase B.1: list per-paper image subdirectories under
    ``Wiki/sources/`` so :func:`migrate` can co-relocate them with
    the matching ``.md`` files.
    """
    sources = vault_path / wiki_subdir / LEGACY_SOURCES_SUBDIR
    if not sources.is_dir():
        return []
    return sorted(p for p in sources.iterdir() if p.is_dir() and not p.name.startswith("."))


def dry_run(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> MigrationPlan:
    """Build the migration plan without touching the filesystem.

    Returns the same ``_PlannedMove`` + ``_PlannedDirMove`` shape
    :func:`migrate` would execute, so the caller can preview moves
    and SHA-256 hashes before committing. Used by
    ``paperwiki wiki-compile --migrate-dry-run``.
    """
    if not needs_migration(vault_path, wiki_subdir=wiki_subdir):
        return MigrationPlan(planned_moves=[], planned_dir_moves=[])
    papers_dir = vault_path / wiki_subdir / TYPED_PAPERS_SUBDIR
    moves: list[_PlannedMove] = [
        _PlannedMove(
            src=legacy,
            dst=papers_dir / legacy.name,
            sha256=_sha256(legacy),
        )
        for legacy in _enumerate_legacy_files(vault_path, wiki_subdir)
    ]
    dir_moves: list[_PlannedDirMove] = [
        _PlannedDirMove(src=legacy, dst=papers_dir / legacy.name)
        for legacy in _enumerate_legacy_subdirs(vault_path, wiki_subdir)
    ]
    return MigrationPlan(planned_moves=moves, planned_dir_moves=dir_moves)


def _utc_timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _make_backup(
    vault_path: Path,
    wiki_subdir: str,
    moves: list[_PlannedMove],
    dir_moves: list[_PlannedDirMove],
    *,
    timestamp: str | None = None,
) -> tuple[str, Path]:
    """Copy legacy files + per-paper subdirs to
    ``<vault>/.paperwiki/migration-backup/<ts>/``.

    Returns ``(timestamp, backup_dir)``. Uses :func:`shutil.copy2`
    for files (preserves metadata) and :func:`shutil.copytree` for
    subdirectories (Phase B.1). The originals stay in place until
    the typed-subdir move runs after this function returns
    successfully — never delete-then-restore semantics.
    """
    ts = timestamp or _utc_timestamp()
    backup_dir = vault_path / PAPERWIKI_DIR / MIGRATION_BACKUP_SUBDIR / ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    # ---- Files (per-paper .md notes, SHA-256 verified) ------------------
    manifest_entries: list[dict[str, str]] = []
    for move in moves:
        rel = move.src.relative_to(vault_path)
        backup_path = backup_dir / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(move.src, backup_path)
        manifest_entries.append(
            {
                "src": str(rel),
                "dst": str(Path(wiki_subdir) / TYPED_PAPERS_SUBDIR / move.src.name),
                "sha256": move.sha256,
            }
        )

    # ---- Directories (per-paper image subdirs, recursive copy) ---------
    dir_entries: list[dict[str, str]] = []
    for dir_move in dir_moves:
        rel = dir_move.src.relative_to(vault_path)
        backup_path = backup_dir / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dir_move.src, backup_path)
        dir_entries.append(
            {
                "src": str(rel),
                "dst": str(Path(wiki_subdir) / TYPED_PAPERS_SUBDIR / dir_move.src.name),
            }
        )

    manifest_path = backup_dir / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "files": manifest_entries,
                "directories": dir_entries,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return ts, backup_dir


def migrate(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> MigrationResult:
    """Run the migration unconditionally (no env gating).

    Idempotent: returns ``moved_count == 0`` when no legacy sources
    remain. Backup is written before any move runs.

    Per consensus plan iter-2 R14, this never deletes the original
    files until the typed-subdir destination receives them via
    :func:`os.replace` (atomic same-fs) with a :func:`shutil.move`
    fallback for cross-fs.
    """
    if not needs_migration(vault_path, wiki_subdir=wiki_subdir):
        return MigrationResult(
            moved_count=0,
            backup_timestamp="",
            backup_dir=vault_path / PAPERWIKI_DIR / MIGRATION_BACKUP_SUBDIR,
        )
    plan = dry_run(vault_path, wiki_subdir=wiki_subdir)
    if not plan.planned_moves and not plan.planned_dir_moves:
        return MigrationResult(
            moved_count=0,
            backup_timestamp="",
            backup_dir=vault_path / PAPERWIKI_DIR / MIGRATION_BACKUP_SUBDIR,
        )
    timestamp, backup_dir = _make_backup(
        vault_path,
        wiki_subdir,
        plan.planned_moves,
        plan.planned_dir_moves,
    )
    logger.info(
        "migrate_v04.backup.complete",
        backup_dir=str(backup_dir),
        files=len(plan.planned_moves),
        directories=len(plan.planned_dir_moves),
    )

    papers_dir = vault_path / wiki_subdir / TYPED_PAPERS_SUBDIR
    papers_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for move in plan.planned_moves:
        try:
            os.replace(move.src, move.dst)
        except OSError:
            # Cross-fs path → fall back to shutil.move.
            shutil.move(str(move.src), str(move.dst))
        moved += 1

    # Phase B.1: relocate per-paper image subdirectories. Always uses
    # ``shutil.move`` (handles cross-fs and recursive trees). The
    # backup above guarantees rollback safety.
    moved_dirs = 0
    for dir_move in plan.planned_dir_moves:
        if dir_move.dst.exists():
            # Defensive: if a same-name subdir already exists under
            # papers/ (mid-migration retry, or user partially hand-
            # migrated), skip rather than clobber. The backup still
            # has the legacy copy for restore.
            logger.warning(
                "migrate_v04.dir.skip_existing",
                src=str(dir_move.src),
                dst=str(dir_move.dst),
            )
            continue
        shutil.move(str(dir_move.src), str(dir_move.dst))
        moved_dirs += 1

    # Remove the empty legacy sources/ directory if it's empty.
    legacy_dir = vault_path / wiki_subdir / LEGACY_SOURCES_SUBDIR
    if legacy_dir.is_dir() and not any(legacy_dir.iterdir()):
        legacy_dir.rmdir()
    logger.info(
        "migrate_v04.move.complete",
        papers_dir=str(papers_dir),
        moved=moved,
        moved_dirs=moved_dirs,
    )
    return MigrationResult(
        moved_count=moved,
        backup_timestamp=timestamp,
        backup_dir=backup_dir,
    )


def migrate_if_needed(
    vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR
) -> MigrationResult | None:
    """Run :func:`migrate` unless ``PAPERWIKI_NO_AUTO_MIGRATE=1`` is set.

    Returns ``None`` when the env-gated escape hatch is active; otherwise
    delegates to :func:`migrate` and returns its result. Hooks expecting
    "migration already happened" can detect this via the return value.
    """
    if os.environ.get(ENV_NO_AUTO_MIGRATE) == "1":
        logger.info(
            "migrate_v04.skipped",
            reason="PAPERWIKI_NO_AUTO_MIGRATE=1",
        )
        return None
    return migrate(vault_path, wiki_subdir=wiki_subdir)


def restore(
    vault_path: Path,
    *,
    timestamp: str,
    wiki_subdir: str = WIKI_SUBDIR,
) -> None:
    """Reverse a migration via the SHA-256-verified backup at ``<ts>``.

    Reads the manifest, copies each file from the backup back to its
    original ``Wiki/sources/`` location, verifies the SHA-256 matches
    the manifest, and prunes the typed-subdir entries created by the
    migration. Phase B.1 (Task 9.187 follow-up): also restores
    per-paper image subdirectories from the ``directories`` manifest
    block, then prunes their typed-subdir copies. Raises
    :class:`PaperWikiError` on any SHA-256 mismatch so the caller
    exits non-zero (per R3).
    """
    backup_dir = vault_path / PAPERWIKI_DIR / MIGRATION_BACKUP_SUBDIR / timestamp
    manifest_path = backup_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        msg = f"backup manifest not found: {manifest_path}"
        raise PaperWikiError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    directories = manifest.get("directories", [])

    for entry in files:
        backup_path = backup_dir / entry["src"]
        if _sha256(backup_path) != entry["sha256"]:
            msg = f"backup integrity check failed: {entry['src']} sha256 does not match manifest"
            raise PaperWikiError(msg)

    legacy_root = vault_path / wiki_subdir / LEGACY_SOURCES_SUBDIR
    legacy_root.mkdir(parents=True, exist_ok=True)
    typed_root = vault_path / wiki_subdir / TYPED_PAPERS_SUBDIR

    # ---- Files (per-paper .md notes) -----------------------------------
    for entry in files:
        backup_path = backup_dir / entry["src"]
        original_path = vault_path / entry["src"]
        original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, original_path)
        # Verify post-copy hash matches manifest (defence in depth).
        if _sha256(original_path) != entry["sha256"]:
            msg = f"post-restore integrity check failed: {entry['src']}"
            raise PaperWikiError(msg)
        # Remove the typed-subdir entry, if present.
        typed_path = vault_path / entry["dst"]
        if typed_path.exists():
            typed_path.unlink()

    # ---- Directories (per-paper image subdirs) -------------------------
    for entry in directories:
        backup_subdir = backup_dir / entry["src"]
        original_subdir = vault_path / entry["src"]
        # Remove a stale partially-restored copy first so copytree
        # doesn't trip on FileExistsError.
        if original_subdir.exists():
            shutil.rmtree(original_subdir)
        original_subdir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(backup_subdir, original_subdir)
        # Remove the typed-subdir copy created by the migration.
        typed_subdir = vault_path / entry["dst"]
        if typed_subdir.exists():
            shutil.rmtree(typed_subdir)

    # Clean up empty typed-subdir.
    if typed_root.is_dir() and not any(typed_root.iterdir()):
        typed_root.rmdir()
    logger.info(
        "migrate_v04.restore.complete",
        timestamp=timestamp,
        files=len(files),
        directories=len(directories),
    )


__all__ = [
    "ENV_NO_AUTO_MIGRATE",
    "MANIFEST_FILENAME",
    "MIGRATION_BACKUP_SUBDIR",
    "PAPERWIKI_DIR",
    "MigrationPlan",
    "MigrationResult",
    "dry_run",
    "migrate",
    "migrate_if_needed",
    "needs_migration",
    "restore",
]
