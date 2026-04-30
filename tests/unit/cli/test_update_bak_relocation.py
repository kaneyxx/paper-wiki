"""Unit tests for v0.3.43 ``.bak`` relocation (D-9.43.2).

v0.3.42 wrote ``.bak`` directories under the plugin cache subdir
(``~/.claude/plugins/cache/paper-wiki/paper-wiki/<ver>.bak.<ts>/``).
That location is wiped by ``/plugin install``, so the rollback target
disappeared between TWO-restart flow steps. v0.3.43 D-9.43.2 relocates
``.bak`` to ``~/.local/share/paperwiki/bak/<ver>.bak.<ts>/`` (XDG-style)
where ``/plugin install`` never reaches.

Five acceptance cases per plan §20.5 9.151:

1. Fresh upgrade writes ``.bak`` to the new location.
2. ``PAPERWIKI_BAK_DIR`` env var overrides the default.
3. Legacy ``<cache>/<ver>.bak.<ts>`` migrates to new location on update.
4. Migration is idempotent across multiple ``paperwiki update`` runs.
5. Migration skips on collision (target already exists at new location).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki import cli as cli_module
from paperwiki.cli import app

# ---------------------------------------------------------------------------
# Fixture — mirrors test_update_self_heal.py's ``update_env``
# ---------------------------------------------------------------------------


@pytest.fixture
def bak_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stage a fake $HOME and monkeypatch the cli module's path constants.

    Returns a dict with cache_base, marketplace_dir, installed_plugins, and
    the expected default bak_root (``$HOME/.local/share/paperwiki/bak``).
    """
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    cache_base = home / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    marketplace_dir = home / ".claude" / "plugins" / "marketplaces" / "paper-wiki"
    installed_plugins = home / ".claude" / "plugins" / "installed_plugins.json"
    settings_json = home / ".claude" / "settings.json"
    settings_local_json = home / ".claude" / "settings.local.json"
    bak_root_default = home / ".local" / "share" / "paperwiki" / "bak"

    monkeypatch.setattr(cli_module, "_CACHE_BASE", cache_base)
    monkeypatch.setattr(cli_module, "_INSTALLED_PLUGINS_JSON", installed_plugins)
    monkeypatch.setattr(cli_module, "_SETTINGS_JSON", settings_json)
    monkeypatch.setattr(cli_module, "_SETTINGS_LOCAL_JSON", settings_local_json)
    monkeypatch.setattr(cli_module, "_DEFAULT_MARKETPLACE_DIR", marketplace_dir)
    # Stub git_pull — fake marketplace is not a real git repo.
    monkeypatch.setattr(cli_module, "_git_pull", lambda _dir: None)
    # Stub _uninstall_stale_editable_paperwiki — no venv in test environment.
    monkeypatch.setattr(cli_module, "_uninstall_stale_editable_paperwiki", lambda: None)

    # Clear any inherited env vars that could redirect bak resolution.
    monkeypatch.delenv("PAPERWIKI_BAK_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    # Disable .bak retention pruning for these tests — focus on relocation.
    monkeypatch.setenv("PAPERWIKI_BAK_KEEP", "0")

    return {
        "home": home,
        "cache_base": cache_base,
        "marketplace_dir": marketplace_dir,
        "installed_plugins": installed_plugins,
        "bak_root_default": bak_root_default,
    }


def _seed_marketplace(marketplace_dir: Path, version: str) -> None:
    marketplace_dir.mkdir(parents=True, exist_ok=True)
    (marketplace_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (marketplace_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "paper-wiki", "version": version}),
        encoding="utf-8",
    )
    (marketplace_dir / "lib").mkdir(parents=True, exist_ok=True)
    (marketplace_dir / "lib" / "bash-helpers.sh").write_text(
        f"# paperwiki bash-helpers — v{version} (test fixture)\n",
        encoding="utf-8",
    )


def _seed_old_cache(cache_base: Path, version: str, *, sentinel: str = "old") -> Path:
    cache_dir = cache_base / version
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "OLD_SENTINEL").write_text(sentinel, encoding="utf-8")
    return cache_dir


def _seed_installed_plugins_json(path: Path, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "paper-wiki@paper-wiki": [
                        {
                            "scope": "user",
                            "version": version,
                            "installPath": str(
                                path.parent / "cache" / "paper-wiki" / "paper-wiki" / version
                            ),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Case 1: fresh upgrade writes .bak to the new (XDG) location
# ---------------------------------------------------------------------------


def test_bak_writes_to_xdg_data_home_on_fresh_upgrade(bak_env: dict[str, Path]) -> None:
    """Default location: ``$HOME/.local/share/paperwiki/bak/<ver>.bak.<ts>/``."""
    marketplace = bak_env["marketplace_dir"]
    cache_base = bak_env["cache_base"]
    bak_root = bak_env["bak_root_default"]
    _seed_marketplace(marketplace, "0.3.43")
    old_cache = _seed_old_cache(cache_base, "0.3.42")
    _seed_installed_plugins_json(bak_env["installed_plugins"], "0.3.42")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["update", "--marketplace-dir", str(marketplace)],
    )

    assert result.exit_code == 0, result.output

    # Old cache dir is gone (renamed/moved).
    assert not old_cache.is_dir(), "old cache dir should have been moved"

    # NEW location exists with a .bak.<ts> entry; OLD sibling location does NOT.
    bak_at_new = list(bak_root.glob("0.3.42.bak.*")) if bak_root.exists() else []
    bak_at_old = list(cache_base.glob("0.3.42.bak.*")) if cache_base.exists() else []
    assert len(bak_at_new) == 1, f"expected 1 bak at {bak_root}, found {bak_at_new}"
    assert len(bak_at_old) == 0, f".bak must NOT live in cache anymore, found {bak_at_old}"

    # The relocated bak preserves the old cache contents.
    assert (bak_at_new[0] / "OLD_SENTINEL").read_text() == "old"


# ---------------------------------------------------------------------------
# Case 2: PAPERWIKI_BAK_DIR env var overrides default
# ---------------------------------------------------------------------------


def test_bak_respects_paperwiki_bak_dir_env(
    bak_env: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PAPERWIKI_BAK_DIR=/custom`` writes there, ignoring XDG/HOME defaults."""
    custom_bak = tmp_path / "custom-bak"
    monkeypatch.setenv("PAPERWIKI_BAK_DIR", str(custom_bak))

    marketplace = bak_env["marketplace_dir"]
    cache_base = bak_env["cache_base"]
    _seed_marketplace(marketplace, "0.3.43")
    _seed_old_cache(cache_base, "0.3.42")
    _seed_installed_plugins_json(bak_env["installed_plugins"], "0.3.42")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["update", "--marketplace-dir", str(marketplace)],
    )

    assert result.exit_code == 0, result.output
    bak_at_custom = list(custom_bak.glob("0.3.42.bak.*"))
    assert len(bak_at_custom) == 1, (
        f"expected 1 bak under PAPERWIKI_BAK_DIR={custom_bak}, found {bak_at_custom}"
    )
    # Default location should be empty.
    bak_at_default = (
        list(bak_env["bak_root_default"].glob("0.3.42.bak.*"))
        if bak_env["bak_root_default"].exists()
        else []
    )
    assert len(bak_at_default) == 0, "default location should be skipped when env var set"


# ---------------------------------------------------------------------------
# Case 3: legacy <cache>/<ver>.bak.<ts> migrates to new location
# ---------------------------------------------------------------------------


def test_legacy_bak_migrated_on_update(bak_env: dict[str, Path]) -> None:
    """Existing ``<cache>/0.3.40.bak.<ts>/`` from v0.3.42 → moved to new bak root."""
    marketplace = bak_env["marketplace_dir"]
    cache_base = bak_env["cache_base"]
    bak_root = bak_env["bak_root_default"]
    _seed_marketplace(marketplace, "0.3.43")
    # Pre-existing legacy bak from v0.3.42 update flow.
    legacy_bak = cache_base / "0.3.40.bak.20260101T120000Z"
    legacy_bak.mkdir(parents=True)
    (legacy_bak / "LEGACY_SENTINEL").write_text("legacy", encoding="utf-8")
    # Active cache + installed_plugins so update can run.
    _seed_old_cache(cache_base, "0.3.42")
    _seed_installed_plugins_json(bak_env["installed_plugins"], "0.3.42")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["update", "--marketplace-dir", str(marketplace)],
    )

    assert result.exit_code == 0, result.output

    # Legacy bak gone from cache subdir.
    assert not legacy_bak.is_dir(), "legacy .bak should have been migrated out of cache"

    # Migrated to new location with the SAME name.
    migrated = bak_root / "0.3.40.bak.20260101T120000Z"
    assert migrated.is_dir(), f"migrated bak missing at {migrated}"
    assert (migrated / "LEGACY_SENTINEL").read_text() == "legacy"


# ---------------------------------------------------------------------------
# Case 4: migration is idempotent across multiple updates
# ---------------------------------------------------------------------------


def test_legacy_bak_migration_idempotent(bak_env: dict[str, Path]) -> None:
    """Second ``paperwiki update`` finds nothing legacy to migrate; no errors."""
    marketplace = bak_env["marketplace_dir"]
    cache_base = bak_env["cache_base"]
    bak_root = bak_env["bak_root_default"]
    _seed_marketplace(marketplace, "0.3.43")
    _seed_old_cache(cache_base, "0.3.42")
    _seed_installed_plugins_json(bak_env["installed_plugins"], "0.3.42")
    # Pre-populate new bak location so it survives the upgrade.
    pre_existing = bak_root / "0.3.41.bak.20260301T000000Z"
    pre_existing.mkdir(parents=True)
    (pre_existing / "PRE_SENTINEL").write_text("pre", encoding="utf-8")

    runner = CliRunner()
    # First update: 0.3.42 → 0.3.43 (creates one new bak).
    result1 = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])
    assert result1.exit_code == 0, result1.output

    # Active cache is now at v0.3.43 (since marketplace is v0.3.43 and the
    # update moved the old v0.3.42 to bak — but installed_plugins still
    # records the OLD version because no /plugin install ran). The simplest
    # idempotent check: re-run update with the same state. Should be a no-op
    # for migration (no legacy bak in cache).

    # Pre-existing bak still there.
    assert pre_existing.is_dir()
    assert (pre_existing / "PRE_SENTINEL").read_text() == "pre"

    # Run update again.
    result2 = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])
    assert result2.exit_code == 0, result2.output

    # Pre-existing bak STILL there.
    assert pre_existing.is_dir()
    assert (pre_existing / "PRE_SENTINEL").read_text() == "pre"


# ---------------------------------------------------------------------------
# Case 5: migration skips on collision
# ---------------------------------------------------------------------------


def test_legacy_bak_migration_collision_skip(bak_env: dict[str, Path]) -> None:
    """When new bak location already has the same-named entry, skip migration."""
    marketplace = bak_env["marketplace_dir"]
    cache_base = bak_env["cache_base"]
    bak_root = bak_env["bak_root_default"]
    _seed_marketplace(marketplace, "0.3.43")

    # Legacy bak in cache (from old paperwiki).
    legacy_bak = cache_base / "0.3.40.bak.20260101T120000Z"
    legacy_bak.mkdir(parents=True)
    (legacy_bak / "LEGACY").write_text("legacy", encoding="utf-8")

    # Same-named entry already exists at new location (collision).
    bak_root.mkdir(parents=True, exist_ok=True)
    collision_target = bak_root / "0.3.40.bak.20260101T120000Z"
    collision_target.mkdir()
    (collision_target / "ORIGINAL").write_text("original", encoding="utf-8")

    _seed_old_cache(cache_base, "0.3.42")
    _seed_installed_plugins_json(bak_env["installed_plugins"], "0.3.42")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["update", "--marketplace-dir", str(marketplace)],
    )

    assert result.exit_code == 0, result.output

    # Collision target preserved (NOT overwritten).
    assert (collision_target / "ORIGINAL").read_text() == "original"
    # Legacy bak left in place (skip + warn semantics).
    assert legacy_bak.is_dir(), "legacy bak preserved on collision"
    assert (legacy_bak / "LEGACY").read_text() == "legacy"


# ---------------------------------------------------------------------------
# v0.3.44 D-9.44.1 — migration must run on no-op update too
# ---------------------------------------------------------------------------


def test_legacy_bak_migrates_on_no_op_update(bak_env: dict[str, Path]) -> None:
    """v0.3.44 D-9.44.1: legacy in-cache .bak migrates even when no version drift.

    v0.3.43 only ran ``_migrate_legacy_bak`` inside the upgrade branch
    (``if cache_ver != marketplace_ver``). When the user upgraded
    via the v0.3.42 binary (which wrote .bak in-cache), then completed
    the TWO-restart, the v0.3.43 binary saw "already at 0.3.43" and
    exited BEFORE migration. Result: the in-cache .bak stayed there
    forever (or got eaten by the next /plugin install).

    v0.3.44 fix: run the migration unconditionally — even when no
    upgrade is happening, the user gets a one-time housekeeping pass
    that moves any in-cache .bak to the durable XDG location.
    """
    marketplace = bak_env["marketplace_dir"]
    cache_base = bak_env["cache_base"]
    bak_root = bak_env["bak_root_default"]
    # Already at the latest version — no upgrade.
    _seed_marketplace(marketplace, "0.3.43")
    _seed_old_cache(cache_base, "0.3.43")  # active cache at v0.3.43
    _seed_installed_plugins_json(bak_env["installed_plugins"], "0.3.43")

    # Pre-existing legacy bak in cache (from v0.3.42 update).
    legacy_bak = cache_base / "0.3.42.bak.20260430T150312Z"
    legacy_bak.mkdir(parents=True)
    (legacy_bak / "LEGACY_SENTINEL").write_text("preserve me", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])

    assert result.exit_code == 0, result.output
    # No drift → "already at 0.3.43" message.
    assert "already at 0.3.43" in result.output

    # Legacy bak migrated out of cache.
    assert not legacy_bak.is_dir(), "legacy .bak should have been migrated even on no-op"

    # Migrated to new location with the SAME name.
    migrated = bak_root / "0.3.42.bak.20260430T150312Z"
    assert migrated.is_dir(), f"migrated bak missing at {migrated}"
    assert (migrated / "LEGACY_SENTINEL").read_text() == "preserve me"


def test_no_op_update_with_no_legacy_bak_is_silent(bak_env: dict[str, Path]) -> None:
    """v0.3.44 D-9.44.1: no-op update without legacy baks doesn't crash or chatter.

    Migration helper short-circuits when there's nothing to do (cache
    base empty, or only contains active version dir). Output stays
    minimal — just "already at vX".
    """
    marketplace = bak_env["marketplace_dir"]
    cache_base = bak_env["cache_base"]
    _seed_marketplace(marketplace, "0.3.43")
    _seed_old_cache(cache_base, "0.3.43")
    _seed_installed_plugins_json(bak_env["installed_plugins"], "0.3.43")
    # No legacy bak.

    runner = CliRunner()
    result = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])

    assert result.exit_code == 0, result.output
    assert "already at 0.3.43" in result.output
