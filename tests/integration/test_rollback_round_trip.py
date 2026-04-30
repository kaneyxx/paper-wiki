"""Pre-tag integration test: migrate → restore → identical bytes.

Per consensus plan iter-2 R3 + Scenario 5 acceptance gate, this test
runs the full migrate/restore round-trip against a *copy* of the
synthetic 100-note fixture (task 9.156a) and asserts the post-restore
state is byte-identical to the pre-migration snapshot.

This is the only release-gate criterion *added* to the migration
scope: rollback must be guaranteed-working before v0.4.0 tags. The
test exercises the public API (``migrate`` + ``restore``) plus the
CLI surface (``paperwiki wiki-compile --migrate-dry-run`` and
``--restore-migration <ts>``) so both invocation paths stay in sync.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from typer.testing import CliRunner

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "synthetic_vault_100"


def _stage_legacy_vault(tmp_path: Path) -> Path:
    """Copy the synthetic fixture but flatten ``papers/`` → ``sources/``.

    The fixture is built in v0.4.x typed-subdir layout. To exercise
    migration, we rename ``papers/`` to the v0.3.x ``sources/`` form
    so :func:`paperwiki.runners.migrate_v04.migrate` has work to do.
    """
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, vault / "Wiki")
    # Flatten v0.4.x papers/ to v0.3.x sources/ so the migration runner
    # has legacy data to rewrite. Concepts/Topics/People stay where they
    # are — they're already in their typed subdirs.
    (vault / "Wiki" / "papers").rename(vault / "Wiki" / "sources")
    return vault


def _snapshot_bytes(root: Path) -> dict[str, str]:
    """Map relative path → SHA-256 for every ``*.md`` under ``root``."""
    out: dict[str, str] = {}
    for md in sorted(root.rglob("*.md")):
        rel = md.relative_to(root).as_posix()
        out[rel] = hashlib.sha256(md.read_bytes()).hexdigest()
    return out


def test_rollback_round_trip_preserves_legacy_snapshot(tmp_path: Path) -> None:
    """End-to-end migrate → restore → byte-identical to pre-migration."""
    from paperwiki.runners.migrate_v04 import migrate, restore

    vault = _stage_legacy_vault(tmp_path)
    before = _snapshot_bytes(vault / "Wiki" / "sources")
    assert len(before) == 40, "synthetic fixture must seed 40 papers"

    result = migrate(vault)
    assert result.moved_count == 40

    # After migrate: papers/ has the files; sources/ is empty/gone.
    papers_dir = vault / "Wiki" / "papers"
    assert papers_dir.is_dir()
    assert len(list(papers_dir.glob("*.md"))) == 40

    restore(vault, timestamp=result.backup_timestamp)

    after = _snapshot_bytes(vault / "Wiki" / "sources")
    assert after == before, (
        "rollback round-trip must produce byte-identical originals; "
        "any drift is a release-gate failure per Scenario 5"
    )


def test_cli_dry_run_does_not_touch_filesystem(tmp_path: Path) -> None:
    """``paperwiki wiki-compile --migrate-dry-run`` is a pure preview."""
    from paperwiki.runners.wiki_compile import app

    vault = _stage_legacy_vault(tmp_path)
    snapshot = _snapshot_bytes(vault / "Wiki")

    runner = CliRunner()
    result = runner.invoke(app, [str(vault), "--migrate-dry-run"])
    assert result.exit_code == 0
    # Output is JSON with planned_moves[].
    assert "planned_moves" in result.output

    # Filesystem unchanged.
    assert _snapshot_bytes(vault / "Wiki") == snapshot
    # papers/ never created in dry-run mode.
    assert not (vault / "Wiki" / "papers").exists()


def test_cli_restore_migration_round_trip(tmp_path: Path) -> None:
    """``paperwiki wiki-compile --restore-migration <ts>`` reverses migrate()."""
    from paperwiki.runners.migrate_v04 import migrate
    from paperwiki.runners.wiki_compile import app

    vault = _stage_legacy_vault(tmp_path)
    before = _snapshot_bytes(vault / "Wiki" / "sources")

    result = migrate(vault)
    assert result.moved_count == 40

    runner = CliRunner()
    cli_result = runner.invoke(
        app,
        [
            str(vault),
            "--restore-migration",
            result.backup_timestamp,
        ],
    )
    assert cli_result.exit_code == 0
    assert "restored migration" in cli_result.output

    after = _snapshot_bytes(vault / "Wiki" / "sources")
    assert after == before
