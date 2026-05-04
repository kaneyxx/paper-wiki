"""Unit tests for ``migrate-recipe`` backup + ``--restore`` flow (Task 9.189 / D-W).

Phase C 9.189 introduces a one-shot ``<recipe>.pre-v04.bak`` backup
adjacent to the original recipe, plus a ``--restore`` CLI flag that
swaps the .bak back into place. This file pins the acceptance bullets
from ``tasks/todo.md::Task 9.189``:

* Backup file exists post-migration with original content byte-identical.
* ``--restore`` flag swaps the .bak back in place and removes the .bak.
* Pre-existing ``.pre-v04.bak`` → migrate refuses with an actionable error
  pointing at the existing .bak (avoid double-overwrite).
* Restore on a recipe without a .pre-v04.bak refuses with a clean message.

The tests target the **pure helpers** (``create_pre_v04_backup``,
``restore_pre_v04_backup``) and the CLI flag wiring. The actual
schema-migration mapping that triggers the backup lives in Task 9.190;
its tests are in ``test_migrate_recipe_mapping.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def recipe_path(tmp_path: Path) -> Path:
    """Write a minimal recipe with pre-v0.4 scorer weights, return its path."""
    target = tmp_path / "stale.yaml"
    target.write_text(
        "name: legacy-recipe\n"
        "scorer:\n"
        "  name: composite\n"
        "  config:\n"
        "    weights:\n"
        "      keyword: 0.5\n"
        "      category: 0.3\n"
        "      recency: 0.2\n",
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# Pure backup helpers
# ---------------------------------------------------------------------------


def test_create_pre_v04_backup_writes_byte_identical_copy(recipe_path: Path) -> None:
    """``create_pre_v04_backup`` produces ``<recipe>.pre-v04.bak`` with
    exact byte-for-byte content of the original.
    """
    from paperwiki.runners.migrate_recipe import create_pre_v04_backup

    original_bytes = recipe_path.read_bytes()

    bak = create_pre_v04_backup(recipe_path)

    assert bak.name == recipe_path.name + ".pre-v04.bak"
    assert bak.is_file()
    assert bak.read_bytes() == original_bytes


def test_create_pre_v04_backup_refuses_when_bak_exists(recipe_path: Path) -> None:
    """When ``<recipe>.pre-v04.bak`` already exists, refuse to overwrite —
    the user should ``--restore`` first or remove the .bak manually.
    """
    from paperwiki.core.errors import UserError
    from paperwiki.runners.migrate_recipe import create_pre_v04_backup

    create_pre_v04_backup(recipe_path)  # first call OK
    with pytest.raises(UserError) as exc_info:
        create_pre_v04_backup(recipe_path)

    msg = str(exc_info.value)
    assert "pre-v04.bak" in msg
    assert "--restore" in msg or "delete" in msg.lower()


def test_restore_pre_v04_backup_swaps_bak_back_in(recipe_path: Path) -> None:
    """``restore_pre_v04_backup`` reverts the recipe to .bak content
    AND removes the .bak file (one-shot, no leftovers).
    """
    from paperwiki.runners.migrate_recipe import (
        create_pre_v04_backup,
        restore_pre_v04_backup,
    )

    original_bytes = recipe_path.read_bytes()
    bak = create_pre_v04_backup(recipe_path)

    # Mutate the recipe to simulate a post-migration state.
    recipe_path.write_text("# migrated\n", encoding="utf-8")

    restored = restore_pre_v04_backup(recipe_path)

    assert restored == recipe_path
    assert recipe_path.read_bytes() == original_bytes
    assert not bak.exists(), "the .pre-v04.bak must be removed after restore"


def test_restore_pre_v04_backup_refuses_when_no_bak(recipe_path: Path) -> None:
    """Restore on a recipe without a ``.pre-v04.bak`` raises a clean error."""
    from paperwiki.core.errors import UserError
    from paperwiki.runners.migrate_recipe import restore_pre_v04_backup

    with pytest.raises(UserError) as exc_info:
        restore_pre_v04_backup(recipe_path)

    msg = str(exc_info.value)
    assert "pre-v04.bak" in msg
    assert "nothing to restore" in msg.lower() or "not found" in msg.lower()


# ---------------------------------------------------------------------------
# CLI flag wiring
# ---------------------------------------------------------------------------


def test_cli_restore_flag_swaps_bak_back(recipe_path: Path) -> None:
    """``paperwiki migrate-recipe <path> --restore`` exits 0 and reverts."""
    from paperwiki.runners import migrate_recipe as runner
    from paperwiki.runners.migrate_recipe import create_pre_v04_backup

    original_bytes = recipe_path.read_bytes()
    create_pre_v04_backup(recipe_path)
    recipe_path.write_text("# migrated\n", encoding="utf-8")

    cli = CliRunner()
    result = cli.invoke(runner.app, [str(recipe_path), "--restore"])

    assert result.exit_code == 0, result.output
    assert recipe_path.read_bytes() == original_bytes
    assert not (recipe_path.with_name(recipe_path.name + ".pre-v04.bak")).exists()


def test_cli_restore_flag_errors_when_no_bak(recipe_path: Path) -> None:
    """``--restore`` without a .pre-v04.bak fails with an actionable error."""
    from paperwiki.runners import migrate_recipe as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [str(recipe_path), "--restore"])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "pre-v04.bak" in combined
