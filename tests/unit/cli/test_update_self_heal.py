"""Unit tests for v0.3.39 ``paperwiki update`` self-heal (D-9.39.1).

When the plugin cache at ``~/.claude/plugins/cache/paper-wiki/paper-wiki/``
contains no version subdirs (regex ``^\\d+\\.\\d+\\.\\d+$``), the update
runner must bootstrap from the marketplace clone before running the
existing diff-and-sync logic. This module covers the four acceptance
cases from plan §16.3 task 9.112:

(a) Empty cache → self-heal succeeds.
(b) Cache with only non-version dirs (``.bak.*``) → self-heal succeeds.
(c) Cache with ≥1 version dir → no self-heal (existing logic runs).
(d) Marketplace clone missing → clear error message (existing path).

Plus a direct unit test for the new ``_cache_has_any_version`` helper.

All filesystem state is staged under ``tmp_path``; the ``paperwiki.cli``
module-level constants (``_CACHE_BASE``, ``_INSTALLED_PLUGINS_JSON``,
``_SETTINGS_JSON``, ``_SETTINGS_LOCAL_JSON``) are monkeypatched per test
because they are resolved at import time and don't honor a runtime
``Path.home()`` override.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki import cli as cli_module
from paperwiki.cli import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def update_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stage a fake $HOME + monkeypatch the cli module's path constants.

    Returns a dict with the cache_base + marketplace_dir + installed_plugins
    paths so tests can directly populate / inspect them.
    """
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    cache_base = home / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    marketplace_dir = home / ".claude" / "plugins" / "marketplaces" / "paper-wiki"
    installed_plugins = home / ".claude" / "plugins" / "installed_plugins.json"
    settings_json = home / ".claude" / "settings.json"
    settings_local_json = home / ".claude" / "settings.local.json"

    monkeypatch.setattr(cli_module, "_CACHE_BASE", cache_base)
    monkeypatch.setattr(cli_module, "_INSTALLED_PLUGINS_JSON", installed_plugins)
    monkeypatch.setattr(cli_module, "_SETTINGS_JSON", settings_json)
    monkeypatch.setattr(cli_module, "_SETTINGS_LOCAL_JSON", settings_local_json)
    monkeypatch.setattr(cli_module, "_DEFAULT_MARKETPLACE_DIR", marketplace_dir)

    # Stub the git pull — tests provide a flat marketplace clone, not a
    # real git repo. The self-heal logic doesn't need a fresh fetch.
    monkeypatch.setattr(cli_module, "_git_pull", lambda _dir: None)

    return {
        "home": home,
        "cache_base": cache_base,
        "marketplace_dir": marketplace_dir,
        "installed_plugins": installed_plugins,
    }


def _seed_marketplace(marketplace_dir: Path, version: str) -> None:
    """Build a minimal fake marketplace clone with a plugin.json + sentinel content."""
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
    # A sentinel file so we can verify the copytree actually happened.
    (marketplace_dir / "MARKETPLACE_SENTINEL").write_text("yes", encoding="utf-8")


def _seed_installed_plugins_json(path: Path, version: str) -> None:
    """Pre-populate installed_plugins.json with a paper-wiki entry at ``version``."""
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
# Helper-level: _cache_has_any_version
# ---------------------------------------------------------------------------


class TestCacheHasAnyVersion:
    def test_returns_false_when_cache_dir_does_not_exist(self, tmp_path: Path) -> None:
        cache = tmp_path / "nonexistent"
        assert cli_module._cache_has_any_version(cache) is False

    def test_returns_false_when_cache_dir_is_empty(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        cache.mkdir()
        assert cli_module._cache_has_any_version(cache) is False

    def test_returns_false_when_cache_has_only_bak_dirs(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        (cache / "0.3.37.bak.20260428T120000Z").mkdir(parents=True)
        (cache / "0.3.36.bak.20260427T120000Z").mkdir(parents=True)
        assert cli_module._cache_has_any_version(cache) is False

    def test_returns_true_when_cache_has_version_dir(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        (cache / "0.3.38").mkdir(parents=True)
        assert cli_module._cache_has_any_version(cache) is True

    def test_returns_true_even_with_mix_of_version_and_bak(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        (cache / "0.3.38").mkdir(parents=True)
        (cache / "0.3.37.bak.20260428T120000Z").mkdir(parents=True)
        assert cli_module._cache_has_any_version(cache) is True


# ---------------------------------------------------------------------------
# Integration: the full ``paperwiki update`` flow with self-heal
# ---------------------------------------------------------------------------


class TestUpdateSelfHeal:
    def test_self_heals_when_cache_completely_empty(self, update_env: dict[str, Path]) -> None:
        """(a) Cache dir doesn't exist + marketplace at v0.3.38 → cache populated."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        _seed_marketplace(marketplace, "0.3.38")
        # No installed_plugins.json — that's also part of the broken state.

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        assert "bootstrapped from marketplace at v0.3.38" in result.output
        # Cache populated at v0.3.38 with marketplace contents.
        assert (cache_base / "0.3.38").is_dir()
        assert (cache_base / "0.3.38" / "MARKETPLACE_SENTINEL").read_text() == "yes"
        assert (cache_base / "0.3.38" / "lib" / "bash-helpers.sh").is_file()

    def test_self_heals_when_cache_has_only_bak_dirs(self, update_env: dict[str, Path]) -> None:
        """(b) Cache contains only ``.bak.*`` dirs (no version dir) → self-heal fires."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        _seed_marketplace(marketplace, "0.3.38")
        # Pre-existing .bak dir from a prior failed install.
        bak_dir = cache_base / "0.3.37.bak.20260428T120000Z"
        bak_dir.mkdir(parents=True)
        (bak_dir / "old_sentinel.txt").write_text("backup", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        assert "bootstrapped from marketplace at v0.3.38" in result.output
        # New version dir created.
        assert (cache_base / "0.3.38").is_dir()
        assert (cache_base / "0.3.38" / "MARKETPLACE_SENTINEL").read_text() == "yes"
        # Old .bak dir untouched.
        assert bak_dir.is_dir()
        assert (bak_dir / "old_sentinel.txt").read_text() == "backup"

    def test_no_self_heal_when_version_dir_already_present(
        self, update_env: dict[str, Path]
    ) -> None:
        """(c) Cache has ≥1 version dir → bootstrap skipped, normal flow runs."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        _seed_marketplace(marketplace, "0.3.38")
        # Existing cache at v0.3.38 (marketplace == cache).
        existing = cache_base / "0.3.38"
        existing.mkdir(parents=True)
        (existing / "EXISTING_SENTINEL").write_text("preserved", encoding="utf-8")
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.38")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        # NO bootstrap message — cache wasn't empty.
        assert "bootstrapped from marketplace" not in result.output
        # Normal "already at" path runs; existing files untouched.
        assert "already at 0.3.38" in result.output
        assert (existing / "EXISTING_SENTINEL").read_text() == "preserved"
        # New marketplace files NOT copied (no overwrite of existing version dir).
        assert not (existing / "MARKETPLACE_SENTINEL").exists()

    def test_marketplace_clone_missing_errors_clearly(self, update_env: dict[str, Path]) -> None:
        """(d) Marketplace clone missing → existing error path fires; no self-heal attempt."""
        cache_base = update_env["cache_base"]
        # Don't seed the marketplace dir.

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 2, result.output
        assert "marketplace clone not found" in result.output
        # Cache untouched — no self-heal happened (we never even read marketplace_ver).
        assert not cache_base.exists()
