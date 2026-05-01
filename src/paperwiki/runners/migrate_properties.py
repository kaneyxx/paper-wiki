"""``paperwiki.runners.migrate_properties`` — Phase-1 → Phase-2 frontmatter rewrite.

Task 9.161 increment 5 of the v0.4.x consensus plan. Walks the typed
subdirs (``Wiki/{papers,concepts,topics,people}/``) and rewrites each
entry's frontmatter so it carries the canonical six-field Obsidian
Properties block (``tags`` / ``aliases`` / ``status`` / ``cssclasses``
/ ``created`` / ``updated``) per **D-D**.

This is the v0.4.0-Phase-1 → v0.4.0-Phase-2 sibling of
:mod:`paperwiki.runners.migrate_v04` (which moved the legacy
``Wiki/sources/`` flat layout into typed subdirs in 9.160). The two
runners share the same safety pattern — copy-first / overwrite-after
with a SHA-256 manifest backup — so a botched migration can always be
reversed via :func:`restore` (R3 release-gate).

Per consensus plan iter-2 R12:

* migration is **idempotent** — a second run is a no-op.
* opt-out via ``PAPERWIKI_NO_PROPERTIES_MIGRATE=1`` env flag.
* new entries written by reporters / backends / templates already get
  the Phase-2 shape directly; this runner only catches files that
  pre-date the Phase-2 templates.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError
from paperwiki.core.properties import build_properties_block, normalize_tags

ENV_NO_PROPERTIES_MIGRATE = "PAPERWIKI_NO_PROPERTIES_MIGRATE"
PAPERWIKI_DIR = ".paperwiki"
PROPERTIES_BACKUP_SUBDIR = "properties-migration-backup"
MANIFEST_FILENAME = "manifest.json"
TYPED_SUBDIRS = ("papers", "concepts", "topics", "people")
PROPERTIES_KEYS = ("tags", "aliases", "status", "cssclasses", "created", "updated")


@dataclass(frozen=True, slots=True)
class _PlannedRewrite:
    src: Path  # absolute path inside the vault
    sha256: str  # of the pre-migration file


@dataclass(frozen=True, slots=True)
class PropertiesMigrationPlan:
    """Result of :func:`dry_run`: planned rewrites without filesystem touch."""

    planned_rewrites: list[_PlannedRewrite]


@dataclass(frozen=True, slots=True)
class PropertiesMigrationResult:
    """Result of :func:`migrate`."""

    rewritten_count: int
    backup_timestamp: str
    backup_dir: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Return ``(frontmatter_dict, body_after_close)``; ``None`` if absent.

    Bytes round-trip via ``yaml.safe_load``; we pre-validate the
    boundary so a file with mid-document ``---`` doesn't get misread.
    """
    if not text.startswith("---\n"):
        return None, text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return None, text
    block = text[4:end]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None, text
    if not isinstance(data, dict):
        return None, text
    body = text[end + len("\n---\n") :]
    return data, body


def _has_full_properties_block(fm: dict[str, Any]) -> bool:
    return all(k in fm for k in PROPERTIES_KEYS)


def _enumerate_typed_files(vault_path: Path, wiki_subdir: str) -> list[Path]:
    out: list[Path] = []
    for typed in TYPED_SUBDIRS:
        directory = vault_path / wiki_subdir / typed
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name.startswith("."):
                continue
            out.append(path)
    return out


def _file_needs_rewrite(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    fm, _ = _split_frontmatter(text)
    if fm is None:
        # Files without frontmatter are out of scope (defensive: do not
        # touch user-authored notes that don't follow the typed-entity
        # shape).
        return False
    return not _has_full_properties_block(fm)


def needs_migration(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> bool:
    """Return True iff at least one typed entry lacks the Properties block."""
    files = _enumerate_typed_files(vault_path, wiki_subdir)
    if not files:
        return False
    return any(_file_needs_rewrite(path) for path in files)


def dry_run(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> PropertiesMigrationPlan:
    """Build the rewrite plan without touching the filesystem."""
    rewrites: list[_PlannedRewrite] = []
    for path in _enumerate_typed_files(vault_path, wiki_subdir):
        if not _file_needs_rewrite(path):
            continue
        rewrites.append(_PlannedRewrite(src=path, sha256=_sha256_file(path)))
    return PropertiesMigrationPlan(planned_rewrites=rewrites)


def _utc_timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _make_backup(
    vault_path: Path,
    rewrites: list[_PlannedRewrite],
    *,
    timestamp: str | None = None,
) -> tuple[str, Path]:
    """Copy each planned rewrite into ``<vault>/.paperwiki/...<ts>/``."""
    import shutil

    ts = timestamp or _utc_timestamp()
    backup_dir = vault_path / PAPERWIKI_DIR / PROPERTIES_BACKUP_SUBDIR / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, str]] = []
    for rewrite in rewrites:
        rel = rewrite.src.relative_to(vault_path)
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rewrite.src, dst)
        manifest_entries.append({"src": str(rel), "sha256": rewrite.sha256})
    manifest_path = backup_dir / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(
            {"timestamp": ts, "files": manifest_entries},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return ts, backup_dir


def _layer_properties_into_frontmatter(fm: dict[str, Any], *, when: datetime) -> dict[str, Any]:
    """Return a new frontmatter dict with the six Properties fields layered in.

    Pre-existing keys are preserved; the Properties block fills the gap.
    Existing ``tags`` is normalized via ``normalize_tags`` so Phase-1
    arXiv categories (``cs.LG``) become Phase-2 nested tags (``cs/lg``).
    """
    raw_tags_value = fm.get("tags")
    raw_tags: list[str]
    if isinstance(raw_tags_value, list):
        raw_tags = [str(t) for t in raw_tags_value if t is not None]
    else:
        raw_tags = []

    raw_aliases_value = fm.get("aliases")
    raw_aliases: list[str]
    if isinstance(raw_aliases_value, list):
        raw_aliases = [str(a) for a in raw_aliases_value if a is not None]
    else:
        raw_aliases = []

    existing_status_value = fm.get("status")
    status = (
        existing_status_value
        if isinstance(existing_status_value, str) and existing_status_value
        else "draft"
    )

    raw_cssclasses_value = fm.get("cssclasses")
    raw_cssclasses: list[str]
    if isinstance(raw_cssclasses_value, list):
        raw_cssclasses = [str(c) for c in raw_cssclasses_value if c is not None]
    else:
        raw_cssclasses = []

    properties = build_properties_block(
        when=when,
        tags=raw_tags,
        aliases=raw_aliases,
        status=status,
        cssclasses=raw_cssclasses,
    )
    # Merge: preserve existing keys, override the six Properties keys.
    merged: dict[str, Any] = dict(fm)
    merged.update(properties)
    # ``tags`` may have been raw arXiv-style; replace with normalized list.
    merged["tags"] = normalize_tags(raw_tags)
    return merged


def migrate(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> PropertiesMigrationResult:
    """Rewrite Phase-1 typed-subdir frontmatter to Phase-2 Properties shape.

    Idempotent: returns ``rewritten_count == 0`` when every typed entry
    already carries the six-field Properties block. Backup is written
    before any rewrite happens.
    """
    plan = dry_run(vault_path, wiki_subdir=wiki_subdir)
    if not plan.planned_rewrites:
        return PropertiesMigrationResult(
            rewritten_count=0,
            backup_timestamp="",
            backup_dir=vault_path / PAPERWIKI_DIR / PROPERTIES_BACKUP_SUBDIR,
        )
    timestamp, backup_dir = _make_backup(vault_path, plan.planned_rewrites)
    logger.info(
        "migrate_properties.backup.complete",
        backup_dir=str(backup_dir),
        files=len(plan.planned_rewrites),
    )

    when = datetime.now(tz=UTC)
    rewritten = 0
    for rewrite in plan.planned_rewrites:
        text = rewrite.src.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(text)
        if fm is None:
            continue
        merged = _layer_properties_into_frontmatter(fm, when=when)
        new_yaml = yaml.safe_dump(
            merged,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        rewrite.src.write_text(f"---\n{new_yaml}---\n{body}", encoding="utf-8")
        rewritten += 1
    logger.info(
        "migrate_properties.rewrite.complete",
        rewritten=rewritten,
        timestamp=timestamp,
    )
    return PropertiesMigrationResult(
        rewritten_count=rewritten,
        backup_timestamp=timestamp,
        backup_dir=backup_dir,
    )


def migrate_if_needed(
    vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR
) -> PropertiesMigrationResult | None:
    """Run :func:`migrate` unless ``PAPERWIKI_NO_PROPERTIES_MIGRATE=1`` is set."""
    if os.environ.get(ENV_NO_PROPERTIES_MIGRATE) == "1":
        logger.info(
            "migrate_properties.skipped",
            reason="PAPERWIKI_NO_PROPERTIES_MIGRATE=1",
        )
        return None
    return migrate(vault_path, wiki_subdir=wiki_subdir)


def restore(
    vault_path: Path,
    *,
    timestamp: str,
) -> None:
    """Reverse a Properties migration via the SHA-256-verified backup at ``<ts>``.

    Reads the manifest, verifies each backup file's SHA-256, then copies
    each backup file back to its original location. Raises
    :class:`PaperWikiError` on integrity mismatch.
    """
    import shutil

    backup_dir = vault_path / PAPERWIKI_DIR / PROPERTIES_BACKUP_SUBDIR / timestamp
    manifest_path = backup_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        msg = f"properties backup manifest not found: {manifest_path}"
        raise PaperWikiError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files", [])

    # Pre-flight integrity check so we never partially restore.
    for entry in files:
        backup_path = backup_dir / entry["src"]
        if _sha256_file(backup_path) != entry["sha256"]:
            msg = (
                f"properties backup integrity check failed: {entry['src']} "
                f"sha256 does not match manifest"
            )
            raise PaperWikiError(msg)

    for entry in files:
        backup_path = backup_dir / entry["src"]
        original_path = vault_path / entry["src"]
        original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, original_path)
    logger.info(
        "migrate_properties.restore.complete",
        timestamp=timestamp,
        files=len(files),
    )


__all__ = [
    "ENV_NO_PROPERTIES_MIGRATE",
    "MANIFEST_FILENAME",
    "PAPERWIKI_DIR",
    "PROPERTIES_BACKUP_SUBDIR",
    "TYPED_SUBDIRS",
    "PropertiesMigrationPlan",
    "PropertiesMigrationResult",
    "dry_run",
    "migrate",
    "migrate_if_needed",
    "needs_migration",
    "restore",
]
