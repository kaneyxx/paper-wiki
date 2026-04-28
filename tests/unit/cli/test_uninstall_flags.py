"""Unit tests for the v0.3.35 flag-driven ``paperwiki uninstall``.

Covers acceptance criteria A1-A12 (help text, --everything fan-out,
vault purge surgical mode, --nuke-vault, validation errors, prompt /
--yes flow, verbose listing, surgical settings.json edits).

All filesystem state is staged under ``tmp_path``; we never touch real
``~/.claude``, ``~/.config/paper-wiki``, or ``~/.local/bin``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki.cli import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage a fake $HOME under tmp_path and pin Path.home() to it.

    Tests get back the home dir; child paths (.claude, .config, .local)
    are created on demand by the helper builders below.
    """
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _seed_plugin_layer(home: Path) -> dict[str, Path]:
    """Pre-populate the plugin-layer files for a test.

    Creates::

        ~/.claude/plugins/cache/paper-wiki/paper-wiki/0.3.34/...
        ~/.claude/plugins/installed_plugins.json (with paper-wiki entry)
        ~/.claude/settings.json (enabledPlugins paper-wiki + omc + extraKnownMarketplaces)
    """
    claude = home / ".claude"
    claude.mkdir(parents=True, exist_ok=True)

    cache_dir = claude / "plugins" / "cache" / "paper-wiki" / "paper-wiki" / "0.3.34"
    cache_dir.mkdir(parents=True)
    (cache_dir / "sentinel.txt").write_text("active", encoding="utf-8")
    bak_dir = (
        claude / "plugins" / "cache" / "paper-wiki" / "paper-wiki" / "0.3.33.bak.20260101T000000Z"
    )
    bak_dir.mkdir(parents=True)
    (bak_dir / "sentinel.txt").write_text("backup", encoding="utf-8")

    installed = claude / "plugins" / "installed_plugins.json"
    installed.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "paper-wiki@paper-wiki": [
                        {"scope": "user", "version": "0.3.34", "installPath": "/fake"}
                    ],
                    "oh-my-claudecode@omc": [
                        {"scope": "user", "version": "1.0.0", "installPath": "/other"}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    settings = claude / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "enabledPlugins": {
                    "oh-my-claudecode@omc": True,
                    "paper-wiki@paper-wiki": True,
                },
                "extraKnownMarketplaces": {
                    "paper-wiki": {
                        "type": "github",
                        "repo": "kaneyxx/paper-wiki",
                    },
                    "omc": {
                        "type": "github",
                        "repo": "example/omc",
                    },
                },
                "model": "sonnet",
            }
        ),
        encoding="utf-8",
    )

    return {
        "cache_dir": cache_dir,
        "bak_dir": bak_dir,
        "installed": installed,
        "settings": settings,
    }


def _seed_everything_layer(home: Path) -> dict[str, Path]:
    """Pre-populate ~/.config/paper-wiki, the shim + marker, marketplace clone."""
    config = home / ".config" / "paper-wiki"
    (config / "recipes").mkdir(parents=True)
    (config / "recipes" / "daily.yaml").write_text("name: daily\n", encoding="utf-8")
    (config / "secrets.env").write_text("API_KEY=test\n", encoding="utf-8")
    (config / "venv" / "bin").mkdir(parents=True)
    (config / "venv" / "bin" / "python").write_text("", encoding="utf-8")

    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    shim = local_bin / "paperwiki"
    shim.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    marker = local_bin / ".paperwiki-path-warned"
    marker.write_text("", encoding="utf-8")

    clone = home / ".claude" / "plugins" / "marketplaces" / "paper-wiki"
    clone.mkdir(parents=True, exist_ok=True)
    (clone / ".claude-plugin").mkdir()
    (clone / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "paper-wiki", "version": "0.3.34"}), encoding="utf-8"
    )

    return {
        "config": config,
        "shim": shim,
        "marker": marker,
        "clone": clone,
    }


def _seed_vault(parent: Path) -> Path:
    """Stage a vault with paperwiki content + non-paperwiki content."""
    vault = parent / "Obsidian-Vault"
    vault.mkdir()

    # paperwiki-created
    (vault / "Daily").mkdir()
    (vault / "Daily" / "2026-04-28.md").write_text("# Today\n", encoding="utf-8")
    (vault / "Wiki").mkdir()
    (vault / "Wiki" / "Concepts").mkdir()
    (vault / ".digest-archive").mkdir()
    (vault / ".vault.lock").write_text("locked", encoding="utf-8")
    (vault / "Welcome.md").write_text("welcome", encoding="utf-8")

    # NOT paperwiki-created — must survive
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.json").write_text("{}", encoding="utf-8")
    (vault / ".DS_Store").write_text("ds", encoding="utf-8")
    (vault / "personal-note.md").write_text("mine", encoding="utf-8")

    return vault


# ---------------------------------------------------------------------------
# A1 — help text lists the new flags
# ---------------------------------------------------------------------------


def test_uninstall_help_lists_new_flags() -> None:
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    # Wider terminal so Typer doesn't word-wrap option names mid-flag.
    result = runner.invoke(app, ["uninstall", "--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    assert "--everything" in result.output
    assert "--purge-vault" in result.output
    assert "--nuke-vault" in result.output
    assert "--yes" in result.output


# ---------------------------------------------------------------------------
# A2 — --everything --yes removes all 7 plugin/everything targets
# ---------------------------------------------------------------------------


def test_uninstall_everything_yes_removes_seven_targets(fake_home: Path) -> None:
    """A2: --everything --yes removes all 7 default + everything targets."""
    plugin = _seed_plugin_layer(fake_home)
    extras = _seed_everything_layer(fake_home)

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall", "--everything", "--yes"])
    assert result.exit_code == 0, result.output

    cache_base = fake_home / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    assert not cache_base.exists(), "plugin cache base must be wiped"

    installed = json.loads(plugin["installed"].read_text())
    assert "paper-wiki@paper-wiki" not in installed.get("plugins", {})

    settings = json.loads(plugin["settings"].read_text())
    assert "paper-wiki@paper-wiki" not in settings.get("enabledPlugins", {})
    assert "paper-wiki" not in settings.get("extraKnownMarketplaces", {})

    assert not extras["config"].exists(), "~/.config/paper-wiki must be wiped"
    assert not extras["shim"].exists(), "~/.local/bin/paperwiki must be removed"
    assert not extras["marker"].exists(), "~/.local/bin/.paperwiki-path-warned must be removed"
    assert not extras["clone"].exists(), "marketplace clone must be wiped"


# ---------------------------------------------------------------------------
# A3 — --purge-vault is surgical (preserves non-paperwiki content)
# ---------------------------------------------------------------------------


def test_uninstall_purge_vault_is_surgical(fake_home: Path, tmp_path: Path) -> None:
    """A3: --purge-vault removes paperwiki content; preserves .obsidian + others."""
    _seed_plugin_layer(fake_home)
    _seed_everything_layer(fake_home)
    vault = _seed_vault(tmp_path)

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(
        app,
        [
            "uninstall",
            "--everything",
            "--purge-vault",
            str(vault),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output

    # paperwiki content gone
    assert not (vault / "Daily").exists()
    assert not (vault / "Wiki").exists()
    assert not (vault / ".digest-archive").exists()
    assert not (vault / ".vault.lock").exists()
    assert not (vault / "Welcome.md").exists()

    # non-paperwiki preserved
    assert (vault / ".obsidian").is_dir()
    assert (vault / ".obsidian" / "config.json").is_file()
    assert (vault / ".DS_Store").is_file()
    assert (vault / "personal-note.md").is_file()


# ---------------------------------------------------------------------------
# A4 — --nuke-vault removes the entire vault directory
# ---------------------------------------------------------------------------


def test_uninstall_nuke_vault_removes_entire_directory(fake_home: Path, tmp_path: Path) -> None:
    """A4: --nuke-vault removes the entire vault, including .obsidian."""
    _seed_plugin_layer(fake_home)
    vault = _seed_vault(tmp_path)

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(
        app,
        [
            "uninstall",
            "--everything",
            "--purge-vault",
            str(vault),
            "--nuke-vault",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not vault.exists(), "vault root must be removed entirely"


# ---------------------------------------------------------------------------
# A5 — --purge-vault without --everything is allowed
# ---------------------------------------------------------------------------


def test_uninstall_purge_vault_without_everything_is_allowed(
    fake_home: Path, tmp_path: Path
) -> None:
    """A5: vault-only purge skips plugin layer."""
    plugin = _seed_plugin_layer(fake_home)
    vault = _seed_vault(tmp_path)

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(
        app,
        ["uninstall", "--purge-vault", str(vault), "--yes"],
    )
    assert result.exit_code == 0, result.output

    # vault content removed (paperwiki-created only)
    assert not (vault / "Daily").exists()
    assert not (vault / "Welcome.md").exists()
    assert (vault / ".obsidian").is_dir()

    # plugin layer ALSO removed (default targets always run if present)
    # — they're part of the plan when they exist regardless of vault flags.
    cache_base = fake_home / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    assert not cache_base.exists()
    installed = json.loads(plugin["installed"].read_text())
    assert "paper-wiki@paper-wiki" not in installed.get("plugins", {})


# ---------------------------------------------------------------------------
# A6 — --nuke-vault without --purge-vault errors out
# ---------------------------------------------------------------------------


def test_uninstall_nuke_vault_without_purge_vault_errors() -> None:
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall", "--nuke-vault", "--yes"])
    assert result.exit_code != 0
    assert "ERROR: --nuke-vault requires --purge-vault" in result.output


# ---------------------------------------------------------------------------
# A7 — --purge-vault on non-existent path errors out
# ---------------------------------------------------------------------------


def test_uninstall_nonexistent_vault_path_errors(fake_home: Path) -> None:
    _seed_plugin_layer(fake_home)
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(
        app,
        [
            "uninstall",
            "--everything",
            "--purge-vault",
            "/does/not/exist/anywhere",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "ERROR: vault path does not exist" in result.output


# ---------------------------------------------------------------------------
# A8 — without --yes, confirmation prompt is required
# ---------------------------------------------------------------------------


def test_uninstall_without_yes_prompts_and_aborts_on_n(fake_home: Path) -> None:
    plugin = _seed_plugin_layer(fake_home)
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall"], input="n\n")
    assert result.exit_code != 0, "answering 'n' must abort with non-zero"
    assert "The following targets will be removed" in result.output
    assert "Continue?" in result.output

    # Nothing happened — cache + JSON entries still present.
    assert plugin["cache_dir"].exists()
    installed = json.loads(plugin["installed"].read_text())
    assert "paper-wiki@paper-wiki" in installed.get("plugins", {})


def test_uninstall_without_yes_proceeds_on_y(fake_home: Path) -> None:
    plugin = _seed_plugin_layer(fake_home)
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall"], input="y\n")
    assert result.exit_code == 0, result.output
    assert not plugin["cache_dir"].exists()
    installed = json.loads(plugin["installed"].read_text())
    assert "paper-wiki@paper-wiki" not in installed.get("plugins", {})


# ---------------------------------------------------------------------------
# A9 — --yes runs immediately, no prompt
# ---------------------------------------------------------------------------


def test_uninstall_yes_skips_prompt(fake_home: Path) -> None:
    _seed_plugin_layer(fake_home)
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Continue?" not in result.output


# ---------------------------------------------------------------------------
# A10 — verbose mode logs each removal
# ---------------------------------------------------------------------------


def test_uninstall_verbose_lists_each_removal(fake_home: Path) -> None:
    _seed_plugin_layer(fake_home)
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall", "--yes", "-v"])
    assert result.exit_code == 0, result.output
    # The structured logger emits "removed: <label>" via INFO; CliRunner
    # captures stderr by default and merges into output.
    assert "removed: " in result.output


# ---------------------------------------------------------------------------
# A12 — settings.json edit is surgical (preserves unrelated keys)
# ---------------------------------------------------------------------------


def test_uninstall_preserves_unrelated_settings_keys(fake_home: Path) -> None:
    plugin = _seed_plugin_layer(fake_home)
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall", "--everything", "--yes"])
    assert result.exit_code == 0, result.output

    settings = json.loads(plugin["settings"].read_text())
    # paper-wiki gone
    assert "paper-wiki@paper-wiki" not in settings.get("enabledPlugins", {})
    assert "paper-wiki" not in settings.get("extraKnownMarketplaces", {})
    # OMC + model preserved
    assert settings.get("enabledPlugins", {}).get("oh-my-claudecode@omc") is True
    assert "omc" in settings.get("extraKnownMarketplaces", {})
    assert settings.get("model") == "sonnet"

    # installed_plugins.json: omc preserved.
    installed = json.loads(plugin["installed"].read_text())
    assert "oh-my-claudecode@omc" in installed.get("plugins", {})
