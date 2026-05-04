"""Integration tests for the v0.4.2 ``wiki-compile`` auto-migration path.

Task 9.187 (D-T): when a vault is still on the v0.3.x layout
(``Wiki/sources/`` populated, ``Wiki/papers/`` empty/absent), running
``paperwiki wiki-compile`` automatically fires
``migrate_v04.migrate(...)`` BEFORE the index rebuild reads the
backend. This closes the loop opened by Task 9.184 (constants) and
9.185+9.186 (write switch + read fallback): users on existing v0.3.x
vaults don't need to know a migration exists — the first compile run
relocates everything safely behind the D-J SHA-256 backup.

Behavior contract pinned by the tests below:

* Default: auto-migrate runs. Banner printed before index rebuild.
  Backup created at ``<vault>/.paperwiki/migration-backup/<ts>/``
  with manifest + SHA-256-verified copies of every original file.
* Idempotent: a second compile run produces no banner, no second
  backup directory, and the index rebuild reads from
  ``Wiki/papers/``.
* ``--no-auto-migrate`` CLI flag: prints the dry-run plan but does
  NOT mutate the filesystem; the index rebuild still runs against
  the legacy ``Wiki/sources/`` via the read-fallback shim.
* ``PAPERWIKI_NO_AUTO_MIGRATE=1`` env var: same effect as the
  ``--no-auto-migrate`` flag (global escape hatch for power users).
* Backup integrity: ``migrate_v04.restore`` succeeds against the
  backup that the auto-fire path created (D-J round trip).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest  # noqa: TC002 — used at runtime via pytest fixture types
from typer.testing import CliRunner

from paperwiki.runners import migrate_v04, wiki_compile

_NOW = datetime(2026, 5, 4, tzinfo=UTC)


def _seed_legacy_vault(vault: Path, *ids: str) -> dict[str, str]:
    """Write minimal source files under v0.3.x ``Wiki/sources/`` and
    return ``{filename: original_text}`` for SHA-256 round-trip
    verification.
    """
    sources_dir = vault / "Wiki" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    contents: dict[str, str] = {}
    for canonical_id in ids:
        filename = canonical_id.replace(":", "_") + ".md"
        body = (
            "---\n"
            f"canonical_id: {canonical_id}\n"
            f"title: Legacy Paper {canonical_id}\n"
            "status: draft\n"
            "confidence: 0.5\n"
            "related_concepts: []\n"
            "tags: []\n"
            "---\n\n"
            f"# Legacy Body for {canonical_id}\n"
        )
        (sources_dir / filename).write_text(body, encoding="utf-8")
        contents[filename] = body
    return contents


async def test_wiki_compile_auto_migrates_legacy_sources(tmp_path: Path) -> None:
    """A vault with only ``Wiki/sources/<id>.md`` runs the migration
    automatically; the index rebuild reads from ``Wiki/papers/``.
    """
    _seed_legacy_vault(tmp_path, "arxiv:2506.13063", "arxiv:2025.99999")

    result = await wiki_compile.compile_wiki(tmp_path, now=_NOW)

    # Index rebuild succeeded — and read from the migrated layout.
    assert result.sources == 2
    # Files moved to canonical location.
    assert (tmp_path / "Wiki" / "papers" / "arxiv_2506.13063.md").is_file()
    assert (tmp_path / "Wiki" / "papers" / "arxiv_2025.99999.md").is_file()
    # Legacy directory is empty (or removed) post-migration.
    legacy_dir = tmp_path / "Wiki" / "sources"
    assert not legacy_dir.exists() or not any(legacy_dir.glob("*.md"))
    # Backup written under the D-J path.
    backup_root = tmp_path / ".paperwiki" / "migration-backup"
    assert backup_root.is_dir()
    timestamps = list(backup_root.iterdir())
    assert len(timestamps) == 1, f"expected one backup snapshot, got {timestamps}"
    manifest = timestamps[0] / "manifest.json"
    assert manifest.is_file()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(payload["files"]) == 2


async def test_wiki_compile_idempotent_after_migration(tmp_path: Path) -> None:
    """Second compile run produces no new backup and no banner."""
    _seed_legacy_vault(tmp_path, "arxiv:2506.13063")

    await wiki_compile.compile_wiki(tmp_path, now=_NOW)
    # Snapshot the backup directory after the first run.
    backup_root = tmp_path / ".paperwiki" / "migration-backup"
    first_timestamps = sorted(p.name for p in backup_root.iterdir())
    assert len(first_timestamps) == 1

    # Re-run.
    await wiki_compile.compile_wiki(tmp_path, now=_NOW)

    # No new backup directory created.
    second_timestamps = sorted(p.name for p in backup_root.iterdir())
    assert second_timestamps == first_timestamps


async def test_wiki_compile_env_var_skips_auto_migrate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PAPERWIKI_NO_AUTO_MIGRATE=1`` opts the user out of the
    auto-fire path. The index rebuild still runs (via the read-
    fallback shim) but the legacy files stay where they are.
    """
    monkeypatch.setenv(migrate_v04.ENV_NO_AUTO_MIGRATE, "1")
    _seed_legacy_vault(tmp_path, "arxiv:2506.13063")

    result = await wiki_compile.compile_wiki(tmp_path, now=_NOW)

    # Index still saw the source via the read-fallback in
    # MarkdownWikiBackend.list_sources (Task 9.185 contract).
    assert result.sources == 1
    # But the file is still at the legacy location.
    assert (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").is_file()
    assert not (tmp_path / "Wiki" / "papers" / "arxiv_2506.13063.md").exists()
    # And no backup directory was created.
    assert not (tmp_path / ".paperwiki" / "migration-backup").exists()


async def test_wiki_compile_explicit_kwarg_skips_auto_migrate(
    tmp_path: Path,
) -> None:
    """``compile_wiki(allow_auto_migrate=False)`` mirrors the
    ``--no-auto-migrate`` CLI flag for in-process callers.
    """
    _seed_legacy_vault(tmp_path, "arxiv:2506.13063")

    result = await wiki_compile.compile_wiki(tmp_path, allow_auto_migrate=False, now=_NOW)

    assert result.sources == 1
    assert (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").is_file()
    assert not (tmp_path / "Wiki" / "papers" / "arxiv_2506.13063.md").exists()


def test_wiki_compile_cli_banner_appears_before_index(tmp_path: Path) -> None:
    """The CLI command prints the migration banner before the
    standard "compiled: N concepts, M sources -> ..." summary.
    """
    _seed_legacy_vault(tmp_path, "arxiv:2506.13063")

    runner = CliRunner()
    result = runner.invoke(wiki_compile.app, [str(tmp_path)])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "Migrating Wiki/sources/" in out, out
    # Banner appears BEFORE the index summary line.
    banner_idx = out.find("Migrating Wiki/sources/")
    summary_idx = out.find("compiled:")
    assert banner_idx >= 0
    assert summary_idx > banner_idx, (
        f"banner must precede compile summary; got banner@{banner_idx} "
        f"summary@{summary_idx} in output:\n{out}"
    )


def test_wiki_compile_cli_no_auto_migrate_flag(tmp_path: Path) -> None:
    """``--no-auto-migrate`` prints the dry-run plan and skips the
    move; the index rebuild still runs.
    """
    _seed_legacy_vault(tmp_path, "arxiv:2506.13063")

    runner = CliRunner()
    result = runner.invoke(wiki_compile.app, [str(tmp_path), "--no-auto-migrate"])

    assert result.exit_code == 0, result.output
    # Plan was printed in JSON-ish form (mirrors --migrate-dry-run shape).
    assert "planned_moves" in result.output
    # Index rebuild still ran.
    assert "compiled:" in result.output
    # File still on the legacy side.
    assert (tmp_path / "Wiki" / "sources" / "arxiv_2506.13063.md").is_file()


async def test_migration_backup_supports_round_trip_restore(tmp_path: Path) -> None:
    """The auto-fire backup is a valid input for ``migrate_v04.restore``."""
    contents = _seed_legacy_vault(tmp_path, "arxiv:2506.13063", "arxiv:2025.99999")

    await wiki_compile.compile_wiki(tmp_path, now=_NOW)

    backup_root = tmp_path / ".paperwiki" / "migration-backup"
    timestamp = next(p for p in backup_root.iterdir() if p.is_dir()).name
    migrate_v04.restore(tmp_path, timestamp=timestamp)

    # Originals are back in place, byte-identical.
    for filename, original in contents.items():
        legacy = tmp_path / "Wiki" / "sources" / filename
        assert legacy.is_file()
        assert legacy.read_text(encoding="utf-8") == original
    # And the canonical layout is empty again. (``migrate_v04.restore``
    # rmdirs the directory when it ends up empty — see ``migrate_v04.py``
    # line 287 — so an absent directory is the success signal.)
    canonical_dir = tmp_path / "Wiki" / "papers"
    assert not canonical_dir.exists() or not any(canonical_dir.iterdir())


async def test_wiki_compile_no_legacy_no_banner_no_backup(tmp_path: Path) -> None:
    """A vault that's already on the v0.4.2 layout (only
    ``Wiki/papers/``, no legacy ``Wiki/sources/``) compiles
    cleanly and never creates a backup directory."""
    canonical_dir = tmp_path / "Wiki" / "papers"
    canonical_dir.mkdir(parents=True)
    (canonical_dir / "arxiv_2506.13063.md").write_text(
        "---\n"
        "canonical_id: arxiv:2506.13063\n"
        "title: Already Migrated\n"
        "status: draft\n"
        "confidence: 0.5\n"
        "related_concepts: []\n"
        "tags: []\n"
        "---\n\n# Body\n",
        encoding="utf-8",
    )

    result = await wiki_compile.compile_wiki(tmp_path, now=_NOW)

    assert result.sources == 1
    # No backup directory ever created.
    assert not (tmp_path / ".paperwiki").exists()
