"""Unit tests for ``paperwiki.runners.migrate_v04`` (task 9.160).

The migration helper moves the legacy v0.3.x ``Wiki/sources/`` layout
into the v0.4.x ``Wiki/papers/`` typed subdir, with a SHA-256 manifest
backup written to ``<vault>/.paperwiki/migration-backup/<ts>/`` so the
move can be reversed via ``--restore-migration <ts>`` (R3).

Per consensus plan iter-2 R14, the backup uses ``shutil.copy2`` (not
``shutil.move``) to preserve the original files until the typed-subdir
move succeeds. Per Scenario 5, this is the only release-gate criterion
*added* to the migration scope — rollback must be guaranteed-working
before tag.

Per **D-J**, migration is default-on with a ``PAPERWIKI_NO_AUTO_MIGRATE=1``
escape hatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _seed_legacy_vault(root: Path, n_sources: int = 3) -> Path:
    """Create a v0.3.x flat-layout vault under ``root``."""
    wiki = root / "Wiki"
    sources = wiki / "sources"
    sources.mkdir(parents=True)
    for i in range(n_sources):
        (sources / f"arxiv-2401-{i:05d}.md").write_text(
            f"---\n"
            f"type: paper\n"
            f"canonical_id: arxiv:2401.{i:05d}\n"
            f"---\n\n"
            f"# Paper {i}\n\nLegacy paper {i} body content.\n"
        )
    return root


class TestNeedsMigration:
    def test_legacy_sources_present(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import needs_migration

        _seed_legacy_vault(tmp_path)
        assert needs_migration(tmp_path) is True

    def test_no_sources_dir(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import needs_migration

        (tmp_path / "Wiki").mkdir()
        assert needs_migration(tmp_path) is False

    def test_already_migrated(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import needs_migration

        # papers/ already exists → migration was done.
        (tmp_path / "Wiki" / "papers").mkdir(parents=True)
        (tmp_path / "Wiki" / "papers" / "p1.md").write_text("---\ntype: paper\n---\n\n# p1\n")
        assert needs_migration(tmp_path) is False

    def test_empty_sources_treated_as_no_migration(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import needs_migration

        # Empty sources/ → nothing to migrate.
        (tmp_path / "Wiki" / "sources").mkdir(parents=True)
        assert needs_migration(tmp_path) is False


class TestMigrate:
    def test_files_moved_to_papers(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import migrate

        _seed_legacy_vault(tmp_path, n_sources=3)
        result = migrate(tmp_path)
        papers_dir = tmp_path / "Wiki" / "papers"
        assert papers_dir.is_dir()
        moved = sorted(papers_dir.glob("*.md"))
        assert len(moved) == 3
        # Legacy sources/ is now empty (or removed).
        sources = tmp_path / "Wiki" / "sources"
        assert not sources.exists() or not list(sources.glob("*.md"))
        assert result.moved_count == 3

    def test_backup_with_sha256_manifest(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import migrate

        _seed_legacy_vault(tmp_path, n_sources=2)
        result = migrate(tmp_path)
        backup_root = tmp_path / ".paperwiki" / "migration-backup"
        assert backup_root.is_dir()
        # Exactly one timestamped backup directory.
        backups = sorted(backup_root.iterdir())
        assert len(backups) == 1
        backup_dir = backups[0]
        manifest_path = backup_dir / "manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())
        assert "files" in manifest
        assert len(manifest["files"]) == 2
        for entry in manifest["files"]:
            assert "src" in entry
            assert "dst" in entry
            assert "sha256" in entry
        # Returned timestamp matches backup directory name.
        assert result.backup_timestamp == backup_dir.name

    def test_files_preserved_under_backup(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import migrate

        _seed_legacy_vault(tmp_path, n_sources=2)
        result = migrate(tmp_path)
        backup_dir = tmp_path / ".paperwiki" / "migration-backup" / result.backup_timestamp
        # Backup carries copies, not moves — the files must exist there.
        backup_files = sorted(backup_dir.glob("Wiki/sources/*.md"))
        assert len(backup_files) == 2

    def test_idempotent_second_run_noop(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import migrate, needs_migration

        _seed_legacy_vault(tmp_path, n_sources=2)
        migrate(tmp_path)
        assert needs_migration(tmp_path) is False
        result = migrate(tmp_path)
        assert result.moved_count == 0


class TestEscapeHatch:
    def test_env_var_disables_migration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.runners.migrate_v04 import migrate_if_needed

        _seed_legacy_vault(tmp_path)
        monkeypatch.setenv("PAPERWIKI_NO_AUTO_MIGRATE", "1")
        result = migrate_if_needed(tmp_path)
        assert result is None  # skipped per env flag
        # Files stay where they were.
        assert (tmp_path / "Wiki" / "sources").is_dir()
        assert not (tmp_path / "Wiki" / "papers").exists()

    def test_unset_env_var_runs_migration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.runners.migrate_v04 import migrate_if_needed

        _seed_legacy_vault(tmp_path)
        monkeypatch.delenv("PAPERWIKI_NO_AUTO_MIGRATE", raising=False)
        result = migrate_if_needed(tmp_path)
        assert result is not None
        assert result.moved_count == 3


class TestDryRun:
    def test_dry_run_prints_plan_without_executing(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import dry_run

        _seed_legacy_vault(tmp_path, n_sources=2)
        plan = dry_run(tmp_path)
        # Plan reports moves but doesn't touch the filesystem.
        assert len(plan.planned_moves) == 2
        assert (tmp_path / "Wiki" / "sources").is_dir()
        assert not (tmp_path / "Wiki" / "papers").exists()
        # Plan items have src/dst pairs.
        for move in plan.planned_moves:
            assert move.src.exists()
            assert move.dst.parent.name == "papers"


class TestRestore:
    def test_restore_undoes_migration(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_v04 import migrate, restore

        _seed_legacy_vault(tmp_path, n_sources=2)
        result = migrate(tmp_path)
        # Pre-restore: papers/ has the files; sources/ is gone.
        assert (tmp_path / "Wiki" / "papers").is_dir()
        # Restore.
        restore(tmp_path, timestamp=result.backup_timestamp)
        # Post-restore: sources/ has the originals back; papers/ is empty/gone.
        sources = tmp_path / "Wiki" / "sources"
        assert sources.is_dir()
        assert len(sorted(sources.glob("*.md"))) == 2
        papers = tmp_path / "Wiki" / "papers"
        assert not papers.exists() or not list(papers.glob("*.md"))

    def test_restore_round_trip_preserves_content(self, tmp_path: Path) -> None:
        """Per Scenario 5 acceptance gate: migrate → restore → identical bytes."""
        from paperwiki.runners.migrate_v04 import migrate, restore

        _seed_legacy_vault(tmp_path, n_sources=3)
        # Snapshot pre-migration content keyed by relative path.
        before: dict[str, bytes] = {}
        for md in (tmp_path / "Wiki" / "sources").glob("*.md"):
            before[md.name] = md.read_bytes()

        result = migrate(tmp_path)
        restore(tmp_path, timestamp=result.backup_timestamp)

        after: dict[str, bytes] = {}
        for md in (tmp_path / "Wiki" / "sources").glob("*.md"):
            after[md.name] = md.read_bytes()
        assert before == after

    def test_restore_fails_on_sha_mismatch(self, tmp_path: Path) -> None:
        from paperwiki.core.errors import PaperWikiError
        from paperwiki.runners.migrate_v04 import migrate, restore

        _seed_legacy_vault(tmp_path, n_sources=1)
        result = migrate(tmp_path)
        # Tamper with the backup file.
        backup_dir = tmp_path / ".paperwiki" / "migration-backup" / result.backup_timestamp
        backup_md = next(backup_dir.glob("Wiki/sources/*.md"))
        backup_md.write_text("CORRUPTED\n")
        with pytest.raises(PaperWikiError):
            restore(tmp_path, timestamp=result.backup_timestamp)
