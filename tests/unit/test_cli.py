"""Unit tests for paperwiki.cli — the paperwiki console-script.

Uses ``typer.testing.CliRunner`` plus ``tmp_path`` fixtures to simulate
``~/.claude`` state without touching the real filesystem.

Test scenarios
--------------
- stale_cache: installed_plugins has an older version → update performs backup
  + prunes JSON entries, prints upgrade message, exit 0.
- up_to_date: cache version == marketplace version → no-op message, exit 0.
- missing_marketplace_clone: marketplace dir absent → exit 2 with helpful message.
- malformed_json: installed_plugins.json is corrupt → exit 1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin_json(version: str, dest: Path) -> None:
    """Write a minimal .claude-plugin/plugin.json to *dest*."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "plugin.json").write_text(
        json.dumps({"name": "paper-wiki", "version": version}), encoding="utf-8"
    )


def _make_installed_plugins(version: str | None, dest: Path) -> None:
    """Write installed_plugins.json using the real Claude Code 2.1.119 dict shape."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    plugins: dict[str, object] = {}
    if version is not None:
        plugins["paper-wiki@paper-wiki"] = [
            {
                "scope": "user",
                "version": version,
                "installPath": "/fake/path",
            }
        ]
    dest.write_text(json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8")


def _make_settings(dest: Path, enabled: bool = True) -> None:
    """Write settings.json using the real Claude Code 2.1.119 dict shape."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    enabled_plugins: dict[str, bool] = {}
    if enabled:
        enabled_plugins["oh-my-claudecode@omc"] = True
        enabled_plugins["paper-wiki@paper-wiki"] = True
    dest.write_text(json.dumps({"enabledPlugins": enabled_plugins}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def claude_home(tmp_path: Path) -> Path:
    """Return a temp directory mirroring ~/.claude structure."""
    home = tmp_path / ".claude"
    home.mkdir()
    return home


def _patch_cli_paths(claude_home: Path) -> dict[str, Path]:
    """Return the canonical paths under claude_home for monkeypatching."""
    return {
        "default_marketplace": claude_home / "plugins" / "marketplaces" / "paper-wiki",
        "installed_plugins": claude_home / "plugins" / "installed_plugins.json",
        "cache_base": claude_home / "plugins" / "cache" / "paper-wiki" / "paper-wiki",
        "settings": claude_home / "settings.json",
        "settings_local": claude_home / "settings.local.json",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _noop_git_pull(marketplace_dir: Path) -> None:  # type: ignore[misc]
    """Stub that does nothing (simulates a fast-forward pull)."""


class TestCliUpdate:
    def test_stale_cache_upgrades_and_prunes_json(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale cache: installed=0.3.19, marketplace=0.3.20 → backup + prune."""
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)

        # Wire paths into cli module constants.
        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])

        # Marketplace clone with 0.3.20.
        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.20", marketplace_dir / ".claude-plugin")

        # Installed state: 0.3.19.
        _make_installed_plugins("0.3.19", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)
        _make_settings(paths["settings_local"], enabled=True)

        # Create the stale cache dir.
        old_cache = paths["cache_base"] / "0.3.19"
        old_cache.mkdir(parents=True)

        # Stub git pull so no real subprocess happens.
        monkeypatch.setattr(cli_mod, "_git_pull", _noop_git_pull)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output

        # Upgrade message shown.
        assert "0.3.19" in result.output
        assert "0.3.20" in result.output

        # JSON entries cleared.
        installed = json.loads(paths["installed_plugins"].read_text())
        assert "paper-wiki@paper-wiki" not in installed.get("plugins", {})
        settings = json.loads(paths["settings"].read_text())
        assert "paper-wiki@paper-wiki" not in settings.get("enabledPlugins", {})

        # Cache dir backed up (renamed, not deleted).
        children = list(paths["cache_base"].iterdir())
        assert any(".bak." in c.name for c in children), "stale cache must be backed up"
        assert not old_cache.exists(), "original 0.3.19 dir must be gone"

    def test_up_to_date_is_noop(self, claude_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When cache == marketplace, nothing changes, exit 0."""
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])

        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.20", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.20", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_git_pull", _noop_git_pull)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output
        assert "already at" in result.output

    def test_missing_marketplace_clone_exits_2(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing marketplace dir → exit 2 with descriptive message."""
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])

        missing_dir = claude_home / "plugins" / "marketplaces" / "nonexistent"

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(missing_dir)]
        )
        assert result.exit_code == 2, result.output

    def test_malformed_installed_plugins_json_exits_1(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Corrupt installed_plugins.json → exit 1."""
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])

        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.20", marketplace_dir / ".claude-plugin")

        # Write corrupt JSON.
        paths["installed_plugins"].parent.mkdir(parents=True, exist_ok=True)
        paths["installed_plugins"].write_text("not json {{{", encoding="utf-8")

        monkeypatch.setattr(cli_mod, "_git_pull", _noop_git_pull)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 1, result.output


class TestCliStatus:
    def test_prints_three_lines(self, claude_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])

        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.20", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.19", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["status", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output
        assert "cache version" in result.output
        assert "marketplace ver" in result.output
        assert "enabledPlugins" in result.output


class TestCliUninstall:
    def test_uninstall_removes_cache_and_json(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])

        _make_installed_plugins("0.3.19", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)

        # Create the cache dir.
        cache_dir = paths["cache_base"] / "0.3.19"
        cache_dir.mkdir(parents=True)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(cli_mod.app, ["uninstall"])
        assert result.exit_code == 0, result.output
        assert not cache_dir.exists()

        installed = json.loads(paths["installed_plugins"].read_text())
        assert "paper-wiki@paper-wiki" not in installed.get("plugins", {})


# ---------------------------------------------------------------------------
# Task 9.29 / D-9.29.2 — CLI surface symmetry: every runner exposed as
# a paperwiki subcommand
# ---------------------------------------------------------------------------


_EXPECTED_PAPERWIKI_COMMANDS: tuple[str, ...] = (
    "update",
    "status",
    "uninstall",
    "migrate-recipe",
    "digest",
    "wiki-ingest",
    "wiki-lint",
    "wiki-compile",
    "wiki-query",
    "extract-images",
    "migrate-sources",
    "gc-archive",
)


class TestCliSubcommandSurface:
    """Pin the paperwiki CLI's command list against drift.

    v0.3.27 mirrored 7 runners + the migrate-recipe subcommand into the
    `paperwiki` console-script via `app.add_typer`. The `update`,
    `status`, and `uninstall` commands stay defined inline in cli.py
    because they manage the plugin lifecycle (no runner counterpart).
    """

    def test_all_expected_subcommands_registered(self) -> None:
        from typer.testing import CliRunner

        from paperwiki.cli import app

        result = CliRunner().invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in _EXPECTED_PAPERWIKI_COMMANDS:
            assert name in result.output, (
                f"`paperwiki {name}` missing from --help; "
                "did a runner rename or add_typer plumbing get dropped?"
            )

    @pytest.mark.parametrize("name", _EXPECTED_PAPERWIKI_COMMANDS)
    def test_subcommand_help_runs_cleanly(self, name: str) -> None:
        """Each subcommand's --help exits 0.

        This catches the most common runner-rename regression: a Typer
        sub-app whose @app.command name doesn't match the parent's
        add_typer name routes user to `paperwiki <name> main --help`
        instead of working as a single-command app.
        """
        from typer.testing import CliRunner

        from paperwiki.cli import app

        result = CliRunner().invoke(app, [name, "--help"])
        assert result.exit_code == 0, (
            f"`paperwiki {name} --help` exited {result.exit_code}: {result.output}"
        )


class TestCliRunnerImports:
    """Sanity check: cli.py imports each runner Typer app at module load.

    A regression here usually means a runner was renamed or moved
    without updating cli.py.
    """

    def test_all_runner_apps_importable(self) -> None:
        from paperwiki.cli import (
            _digest_app,
            _extract_images_app,
            _gc_archive_app,
            _migrate_recipe_app,
            _migrate_sources_app,
            _wiki_compile_app,
            _wiki_ingest_app,
            _wiki_lint_app,
            _wiki_query_app,
        )

        for name, runner_app in (
            ("digest", _digest_app),
            ("extract-images", _extract_images_app),
            ("gc-archive", _gc_archive_app),
            ("migrate-recipe", _migrate_recipe_app),
            ("migrate-sources", _migrate_sources_app),
            ("wiki-compile", _wiki_compile_app),
            ("wiki-ingest", _wiki_ingest_app),
            ("wiki-lint", _wiki_lint_app),
            ("wiki-query", _wiki_query_app),
        ):
            assert runner_app is not None, f"runner app {name} failed to import"
