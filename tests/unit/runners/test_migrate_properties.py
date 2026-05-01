"""Unit tests for ``paperwiki.runners.migrate_properties`` (task 9.161 incr 5).

The Properties migration is the v0.4.0-Phase-1 → v0.4.0-Phase-2 sibling
of :mod:`paperwiki.runners.migrate_v04` (which moved the legacy
``Wiki/sources/`` layout to typed subdirs in 9.160). Here we walk the
typed subdirs and rewrite each entry's frontmatter so it carries the
canonical six-field Obsidian Properties block (per **D-D**).

Per the consensus plan iter-2 R12:

* migration is **idempotent** — a second run is a no-op.
* a SHA-256 manifest backup is written to
  ``<vault>/.paperwiki/properties-migration-backup/<ts>/`` before any
  file is rewritten (R14 copy-first / overwrite-after pattern).
* opt-out via ``PAPERWIKI_NO_PROPERTIES_MIGRATE=1`` env flag.
* ``restore`` reverses the migration if needed (R3 release-gate).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _seed_phase_1_vault(root: Path) -> Path:
    """Create a v0.4.0-Phase-1 vault that lacks the Properties block.

    Phase-1 typed entries have ``type`` / ``name`` / ``definition`` etc.
    but no ``aliases`` / ``status`` / ``cssclasses`` / ``created`` /
    ``updated`` (only ``tags`` was present, and not normalized).
    """
    wiki = root / "Wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "topics").mkdir(parents=True)
    (wiki / "people").mkdir(parents=True)
    (wiki / "papers").mkdir(parents=True)

    (wiki / "concepts" / "transformer.md").write_text(
        "---\n"
        "type: concept\n"
        "name: Transformer\n"
        "definition: Attention-based architecture.\n"
        "tags: [cs.LG, NLP]\n"
        "---\n\n"
        "# Transformer\n\nAttention-based architecture.\n"
    )
    (wiki / "topics" / "vlm.md").write_text(
        "---\ntype: topic\nname: VLMs\ndescription: x\n---\n\n# VLMs\n\nx\n"
    )
    (wiki / "people" / "lecun.md").write_text(
        "---\ntype: person\nname: Yann LeCun\n---\n\n# Yann LeCun\n"
    )
    (wiki / "papers" / "arxiv-1706.md").write_text(
        "---\n"
        "canonical_id: arxiv:1706.03762\n"
        "title: Attention Is All You Need\n"
        "status: draft\n"
        "tags: [cs.CL]\n"
        "---\n\n"
        "# Attention Is All You Need\n"
    )
    return root


class TestNeedsMigration:
    def test_phase_1_vault_needs_migration(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_properties import needs_migration

        _seed_phase_1_vault(tmp_path)
        assert needs_migration(tmp_path) is True

    def test_already_migrated_vault_is_no_op(self, tmp_path: Path) -> None:
        """Idempotency anchor: if every typed entry already carries the
        six-field Properties block, ``needs_migration`` returns False."""
        from paperwiki.runners.migrate_properties import migrate, needs_migration

        _seed_phase_1_vault(tmp_path)
        migrate(tmp_path)
        # Second invocation: nothing left to do.
        assert needs_migration(tmp_path) is False

    def test_empty_typed_dirs_treated_as_no_migration(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_properties import needs_migration

        (tmp_path / "Wiki" / "concepts").mkdir(parents=True)
        (tmp_path / "Wiki" / "topics").mkdir(parents=True)
        # No files in any typed dir → nothing to migrate.
        assert needs_migration(tmp_path) is False


class TestMigrate:
    def test_files_get_properties_block_added(self, tmp_path: Path) -> None:
        import yaml

        from paperwiki.runners.migrate_properties import migrate

        _seed_phase_1_vault(tmp_path)
        result = migrate(tmp_path)
        assert result.rewritten_count == 4

        # Verify each typed entry now has all six Properties fields.
        for rel in (
            "Wiki/concepts/transformer.md",
            "Wiki/topics/vlm.md",
            "Wiki/people/lecun.md",
            "Wiki/papers/arxiv-1706.md",
        ):
            text = (tmp_path / rel).read_text(encoding="utf-8")
            end = text.index("\n---\n", 4)
            fm = yaml.safe_load(text[4:end])
            for key in ("tags", "aliases", "status", "cssclasses", "created", "updated"):
                assert key in fm, f"{rel} missing {key}"

    def test_tags_get_normalized(self, tmp_path: Path) -> None:
        """Phase-1 ``cs.LG`` becomes Phase-2 ``cs/lg`` via ``normalize_tags``."""
        import yaml

        from paperwiki.runners.migrate_properties import migrate

        _seed_phase_1_vault(tmp_path)
        migrate(tmp_path)

        text = (tmp_path / "Wiki" / "concepts" / "transformer.md").read_text(encoding="utf-8")
        end = text.index("\n---\n", 4)
        fm = yaml.safe_load(text[4:end])
        # ``cs.LG`` → ``cs/lg``; ``NLP`` → ``nlp``.
        assert fm["tags"] == ["cs/lg", "nlp"]

    def test_backup_with_sha256_manifest(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_properties import migrate

        _seed_phase_1_vault(tmp_path)
        result = migrate(tmp_path)

        backup_root = tmp_path / ".paperwiki" / "properties-migration-backup"
        assert backup_root.is_dir()
        backups = sorted(backup_root.iterdir())
        assert len(backups) == 1
        backup_dir = backups[0]
        manifest = json.loads((backup_dir / "manifest.json").read_text())
        assert manifest["timestamp"] == result.backup_timestamp
        # One manifest entry per rewritten file.
        assert len(manifest["files"]) == 4
        for entry in manifest["files"]:
            assert "src" in entry
            assert "sha256" in entry
            # Backup file actually exists at ``backup_dir / entry["src"]``.
            assert (backup_dir / entry["src"]).is_file()

    def test_idempotent_second_run_noop(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_properties import migrate

        _seed_phase_1_vault(tmp_path)
        first = migrate(tmp_path)
        assert first.rewritten_count == 4
        second = migrate(tmp_path)
        assert second.rewritten_count == 0


class TestEscapeHatch:
    def test_env_var_disables_migration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.runners.migrate_properties import migrate_if_needed

        _seed_phase_1_vault(tmp_path)
        monkeypatch.setenv("PAPERWIKI_NO_PROPERTIES_MIGRATE", "1")

        result = migrate_if_needed(tmp_path)
        assert result is None

        text = (tmp_path / "Wiki" / "concepts" / "transformer.md").read_text(encoding="utf-8")
        # File untouched: Phase-1 shape preserved.
        assert "aliases:" not in text
        assert "cssclasses:" not in text


class TestRestore:
    def test_restore_undoes_migration(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_properties import migrate, restore

        _seed_phase_1_vault(tmp_path)
        before = (tmp_path / "Wiki" / "concepts" / "transformer.md").read_bytes()

        result = migrate(tmp_path)
        # Rewrite happened: bytes differ.
        after_migrate = (tmp_path / "Wiki" / "concepts" / "transformer.md").read_bytes()
        assert after_migrate != before

        restore(tmp_path, timestamp=result.backup_timestamp)

        after_restore = (tmp_path / "Wiki" / "concepts" / "transformer.md").read_bytes()
        assert after_restore == before

    def test_restore_fails_on_sha_mismatch(self, tmp_path: Path) -> None:
        from paperwiki.core.errors import PaperWikiError
        from paperwiki.runners.migrate_properties import migrate, restore

        _seed_phase_1_vault(tmp_path)
        result = migrate(tmp_path)
        # Tamper with one of the backup files.
        backup_dir = (
            tmp_path / ".paperwiki" / "properties-migration-backup" / result.backup_timestamp
        )
        any_backup = next(backup_dir.rglob("*.md"))
        any_backup.write_text("CORRUPTED\n", encoding="utf-8")

        with pytest.raises(PaperWikiError):
            restore(tmp_path, timestamp=result.backup_timestamp)
