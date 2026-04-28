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
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """v0.3.35: uninstall uses Path.home()-derived paths via
        ``runners.uninstall``; we monkeypatch Path.home() and pass
        ``--yes`` to skip the new confirmation prompt."""
        import paperwiki.cli as cli_mod

        # Pin Path.home() to claude_home's parent so .claude lookups land in tmp.
        fake_home = claude_home.parent
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        # Move claude_home to ${fake_home}/.claude so the resolver finds it.
        target_claude = fake_home / ".claude"
        if claude_home != target_claude:
            target_claude.parent.mkdir(parents=True, exist_ok=True)
            claude_home.rename(target_claude)
        paths = {
            "installed_plugins": target_claude / "plugins" / "installed_plugins.json",
            "cache_base": target_claude / "plugins" / "cache" / "paper-wiki" / "paper-wiki",
            "settings": target_claude / "settings.json",
            "settings_local": target_claude / "settings.local.json",
        }

        _make_installed_plugins("0.3.19", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)

        # Create the cache dir.
        cache_dir = paths["cache_base"] / "0.3.19"
        cache_dir.mkdir(parents=True)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["uninstall", "--yes"]
        )
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
    "gc-bak",
    "where",
    # Task 9.59 (v0.3.34): diagnostics joined the symmetric CLI surface.
    "diagnostics",
)


def _make_bak_dir(cache_base: Path, name: str) -> Path:
    """Synthesise a fake `.bak.<ts>` directory under cache_base for tests."""
    cache_base.mkdir(parents=True, exist_ok=True)
    bak = cache_base / name
    bak.mkdir()
    (bak / "sentinel.txt").write_text("seed", encoding="utf-8")
    return bak


class TestCliUpdateUninstallsStaleEditableInstall:
    """Task v0.3.31-B: `paperwiki update` must uninstall the editable
    `paperwiki` install from the shared venv BEFORE renaming the cache
    dir, so the .pth file (referencing the soon-to-be-renamed path)
    doesn't orphan the next `paperwiki <X>` call with
    `ModuleNotFoundError: No module named 'paperwiki'`.
    """

    def test_uninstall_called_before_rename(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.30", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.29", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)
        cache_dir = paths["cache_base"] / "0.3.29"
        cache_dir.mkdir(parents=True)

        # Synthesise a fake shared venv so the uninstall helper finds
        # bin/python and attempts the subprocess call.
        fake_venv = tmp_path / "venv"
        (fake_venv / "bin").mkdir(parents=True)
        (fake_venv / "bin" / "python").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        (fake_venv / "bin" / "python").chmod(0o755)
        monkeypatch.setattr(cli_mod, "resolve_paperwiki_venv_dir", lambda: fake_venv)

        # Capture order: uninstall subprocess call BEFORE cache rename.
        call_log: list[str] = []
        original_subprocess_run = cli_mod.subprocess.run

        def _logged_run(cmd: list[str], **kwargs: object) -> object:
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "uninstall" in cmd_str and "paperwiki" in cmd_str:
                call_log.append("uninstall")
            return original_subprocess_run(cmd, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(cli_mod.subprocess, "run", _logged_run)

        # Wrap rename to also log.
        original_rename = type(cache_dir).rename

        def _logged_rename(self_path: Path, target: Path) -> Path:  # type: ignore[no-redef]
            call_log.append("rename")
            return original_rename(self_path, target)

        monkeypatch.setattr(type(cache_dir), "rename", _logged_rename)

        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])
        monkeypatch.setattr(cli_mod, "_git_pull", _noop_git_pull)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output
        # Both happened, in the right order.
        assert "uninstall" in call_log, "expected pip uninstall to be called"
        assert "rename" in call_log, "expected cache rename to be called"
        assert call_log.index("uninstall") < call_log.index("rename"), (
            f"uninstall must precede rename; actual order: {call_log}"
        )

    def test_uninstall_is_noop_when_venv_missing(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No shared venv = no editable install to clean. Update flow continues."""
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.30", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.29", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)
        cache_dir = paths["cache_base"] / "0.3.29"
        cache_dir.mkdir(parents=True)

        # Point at a path that doesn't exist.
        monkeypatch.setattr(cli_mod, "resolve_paperwiki_venv_dir", lambda: tmp_path / "nonexistent")
        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])
        monkeypatch.setattr(cli_mod, "_git_pull", _noop_git_pull)

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(marketplace_dir)]
        )
        # Update still succeeds; uninstall was skipped silently.
        assert result.exit_code == 0, result.output


class TestCliUpdateAutoPruneBak:
    """Task 9.33 / D-9.33.2: `paperwiki update` auto-prunes old .bak after success."""

    def test_keeps_recent_n_when_paperwiki_bak_keep_set(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.30", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.29", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)
        cache_dir = paths["cache_base"] / "0.3.29"
        cache_dir.mkdir(parents=True)

        # Seed 5 historic .bak directories.
        for i in range(5):
            _make_bak_dir(paths["cache_base"], f"0.3.{20 + i}.bak.2026010{i + 1}T000000Z")

        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])
        monkeypatch.setattr(cli_mod, "_git_pull", _noop_git_pull)
        monkeypatch.setenv("PAPERWIKI_BAK_KEEP", "2")

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output
        # The cache rename creates a new bak (0.3.29.bak.<ts>); after prune
        # we should keep the newest 2 (one of which is the new bak).
        remaining = sorted(p.name for p in paths["cache_base"].iterdir() if p.is_dir())
        bak_dirs = [n for n in remaining if ".bak." in n]
        assert len(bak_dirs) == 2, (
            f"expected 2 bak dirs after prune (PAPERWIKI_BAK_KEEP=2); got {bak_dirs}"
        )

    def test_paperwiki_bak_keep_zero_skips_prune(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.30", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.29", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)
        cache_dir = paths["cache_base"] / "0.3.29"
        cache_dir.mkdir(parents=True)

        for i in range(3):
            _make_bak_dir(paths["cache_base"], f"0.3.{20 + i}.bak.2026010{i + 1}T000000Z")

        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])
        monkeypatch.setattr(cli_mod, "_git_pull", _noop_git_pull)
        monkeypatch.setenv("PAPERWIKI_BAK_KEEP", "0")

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["update", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output
        # All 3 historic baks + the new bak from this update preserved.
        bak_dirs = [
            p.name for p in paths["cache_base"].iterdir() if p.is_dir() and ".bak." in p.name
        ]
        assert len(bak_dirs) >= 3, (
            f"PAPERWIKI_BAK_KEEP=0 must skip prune; expected >= 3 bak dirs, got {bak_dirs}"
        )


class TestCliStatusBakLine:
    """Task 9.33: `paperwiki status` shows a 4th line with .bak retention state."""

    def test_no_bak_shows_no_backups(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.29", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.29", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)
        paths["cache_base"].mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["status", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output
        assert "bak directories" in result.output
        assert "no backups" in result.output

    def test_bak_count_and_oldest_date(
        self, claude_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import paperwiki.cli as cli_mod

        paths = _patch_cli_paths(claude_home)
        marketplace_dir = paths["default_marketplace"]
        _make_plugin_json("0.3.29", marketplace_dir / ".claude-plugin")
        _make_installed_plugins("0.3.29", paths["installed_plugins"])
        _make_settings(paths["settings"], enabled=True)

        _make_bak_dir(paths["cache_base"], "0.3.27.bak.20260101T000000Z")
        _make_bak_dir(paths["cache_base"], "0.3.28.bak.20260301T120000Z")

        monkeypatch.setattr(cli_mod, "_INSTALLED_PLUGINS_JSON", paths["installed_plugins"])
        monkeypatch.setattr(cli_mod, "_CACHE_BASE", paths["cache_base"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_JSON", paths["settings"])
        monkeypatch.setattr(cli_mod, "_SETTINGS_LOCAL_JSON", paths["settings_local"])

        from typer.testing import CliRunner

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(
            cli_mod.app, ["status", "--marketplace-dir", str(marketplace_dir)]
        )
        assert result.exit_code == 0, result.output
        assert "2 kept" in result.output
        # The oldest bak was 2026-01-01 — date should appear human-formatted.
        assert "2026-01-01" in result.output


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

    def test_all_runner_mains_importable(self) -> None:
        """v0.3.30: cli.py re-uses runner.main callables directly via
        app.command(name=...)(...). This test pins the import names so a
        runner rename can't silently drop a parent-app subcommand."""
        from paperwiki.cli import (
            _diagnostics_main,
            _digest_main,
            _extract_images_main,
            _gc_archive_main,
            _gc_bak_main,
            _migrate_recipe_main,
            _migrate_sources_main,
            _where_main,
            _wiki_compile_main,
            _wiki_ingest_main,
            _wiki_lint_main,
            _wiki_query_main,
        )

        for name, runner_main in (
            ("diagnostics", _diagnostics_main),
            ("digest", _digest_main),
            ("extract-images", _extract_images_main),
            ("gc-archive", _gc_archive_main),
            ("gc-bak", _gc_bak_main),
            ("migrate-recipe", _migrate_recipe_main),
            ("migrate-sources", _migrate_sources_main),
            ("where", _where_main),
            ("wiki-compile", _wiki_compile_main),
            ("wiki-ingest", _wiki_ingest_main),
            ("wiki-lint", _wiki_lint_main),
            ("wiki-query", _wiki_query_main),
        ):
            assert callable(runner_main), f"runner main {name} not callable"


class TestCliDiagnosticsSubcommand:
    """Task 9.59 (v0.3.34): `paperwiki diagnostics` runs end-to-end.

    The runner module exposes ``build_report`` already; this just pins
    that the parent CLI surface invokes it without crashing.
    """

    def test_diagnostics_emits_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`paperwiki diagnostics` exits 0 and emits valid JSON."""
        from typer.testing import CliRunner

        import paperwiki.runners.diagnostics as diag_mod
        from paperwiki.cli import app

        # Stub `claude mcp list` so the test never spawns a real subprocess.
        # Without this, the test depends on whether `claude` is on PATH.
        monkeypatch.setattr(diag_mod, "_detect_mcp_servers", lambda issues: [])

        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(app, ["diagnostics"])
        assert result.exit_code == 0, result.output
        # Output must be valid JSON with the expected top-level keys.
        report = json.loads(result.output)
        assert "paperwiki_version" in report
        assert "python_version" in report
        assert "bundled_recipes" in report
