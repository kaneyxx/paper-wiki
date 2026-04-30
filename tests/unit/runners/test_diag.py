"""Unit tests for ``paperwiki.runners.diag`` (v0.3.42 D-9.42.1 + D-9.42.4).

The diag-rendering layer is the single source of truth for the
``paperwiki diag`` CLI subcommand and the ``paperwiki_diag`` bash
function (which delegates to the CLI when the shim is available —
D-9.42.4). These tests pin the rendered output's sections, fallbacks,
and read-only contract.

Tests are pure-Python: ``render_diag`` is a pure function that takes
``home`` / ``claude_home`` / optional env strings and returns the
multi-section dump as a string. No subprocess, no real filesystem
beyond the ``tmp_path`` fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

from paperwiki.runners.diag import render_diag


def _seed_helper(home: Path, *, version: str = "0.3.42-test") -> Path:
    """Place a stub ``bash-helpers.sh`` under the canonical install path."""
    helper_dir = home / ".local" / "lib" / "paperwiki"
    helper_dir.mkdir(parents=True)
    helper = helper_dir / "bash-helpers.sh"
    helper.write_text(
        f"# paperwiki bash-helpers — v{version} (test stub)\n",
        encoding="utf-8",
    )
    return helper


def _seed_shim(home: Path, *, version: str = "0.3.42-test") -> Path:
    """Place a stub ``paperwiki`` shim under ``$HOME/.local/bin``."""
    shim_dir = home / ".local" / "bin"
    shim_dir.mkdir(parents=True)
    shim = shim_dir / "paperwiki"
    shim.write_text(
        f"#!/usr/bin/env bash\n# paperwiki shim — v{version} (test stub)\n",
        encoding="utf-8",
    )
    return shim


def _seed_cache(claude_home: Path, *versions: str) -> Path:
    """Place fake cache subdirs under ``~/.claude/plugins/cache/paper-wiki/paper-wiki``."""
    cache_root = claude_home / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    cache_root.mkdir(parents=True)
    for version in versions:
        (cache_root / version).mkdir()
    return cache_root


def _seed_installed_plugins(
    claude_home: Path,
    *,
    version: str = "0.3.42",
    extra: bool = False,
) -> Path:
    """Place a stub ``installed_plugins.json`` with the paper-wiki entry."""
    path = claude_home / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    plugins: dict[str, dict[str, object]] = {
        "paper-wiki@paper-wiki": {
            "scope": "user",
            "version": version,
            "installPath": str(
                claude_home / "plugins" / "cache" / "paper-wiki" / "paper-wiki" / version
            ),
        }
    }
    if extra:
        plugins["other-plugin@other-marketplace"] = {
            "version": "1.2.3",
            "scope": "user",
        }
    path.write_text(json.dumps({"plugins": plugins}), encoding="utf-8")
    return path


def _seed_recipes(home: Path, *names: str) -> Path:
    """Place a recipes directory under ``$HOME/.config/paper-wiki``."""
    recipes_dir = home / ".config" / "paper-wiki" / "recipes"
    recipes_dir.mkdir(parents=True)
    for name in names:
        (recipes_dir / name).write_text(f"name: {name}\n", encoding="utf-8")
    return recipes_dir


# ---------------------------------------------------------------------------
# Section presence + ordering
# ---------------------------------------------------------------------------


def test_render_emits_all_seven_sections(tmp_path: Path) -> None:
    """``render_diag`` produces the seven-section dump (mirrors bash version)."""
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    claude_home.mkdir()
    _seed_helper(home, version="0.3.42")
    _seed_shim(home, version="0.3.42")
    _seed_cache(claude_home, "0.3.41", "0.3.42")
    _seed_installed_plugins(claude_home, version="0.3.42")
    _seed_recipes(home, "daily.yaml", "weekly.yaml")

    out = render_diag(home=home, claude_home=claude_home)

    assert "=== paperwiki_diag — install state ===" in out
    assert "=== end paperwiki_diag ===" in out
    for section in (
        "--- helper ---",
        "--- environment ---",
        "--- shim ",
        "--- plugin cache versions ",
        "--- installed_plugins.json (paper-wiki entry) ---",
        "--- recipes ",
    ):
        assert section in out, f"missing section {section!r}\n{out}"
    # Section content sanity.
    assert "paperwiki bash-helpers" in out  # helper version-tag echoed
    assert "paperwiki shim" in out  # shim header line echoed
    # Cache versions listed.
    assert "0.3.41" in out
    assert "0.3.42" in out
    # Recipes listed.
    assert "daily.yaml" in out
    assert "weekly.yaml" in out
    # installed_plugins entry shown.
    assert '"version": "0.3.42"' in out


# ---------------------------------------------------------------------------
# Missing-dir / fallback behaviour
# ---------------------------------------------------------------------------


def test_render_handles_missing_paths_gracefully(tmp_path: Path) -> None:
    """Bare HOME with no helper/shim/cache/recipes: every section degrades cleanly."""
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()

    out = render_diag(home=home, claude_home=claude_home)

    assert out.startswith("=== paperwiki_diag — install state ===")
    assert out.rstrip().endswith("=== end paperwiki_diag ===")
    assert "(not installed)" in out  # shim missing
    assert "(directory does not exist)" in out  # cache + recipes missing
    assert "(not registered)" in out  # installed_plugins missing


def test_render_environment_uses_supplied_path_and_plugin_root(
    tmp_path: Path,
) -> None:
    """``path_env`` and ``plugin_root`` parameters override ``os.environ`` reads."""
    home = tmp_path / "home"
    home.mkdir()
    out = render_diag(
        home=home,
        claude_home=home / ".claude",
        path_env="/usr/local/bin:/usr/bin",
        plugin_root="/path/to/plugin",
    )
    assert "PATH=/usr/local/bin:/usr/bin" in out
    assert "CLAUDE_PLUGIN_ROOT=/path/to/plugin" in out


def test_render_environment_unset_when_arg_none(tmp_path: Path) -> None:
    """When ``plugin_root`` is None, the section reports ``(unset)``."""
    home = tmp_path / "home"
    home.mkdir()
    out = render_diag(
        home=home,
        claude_home=home / ".claude",
        path_env="/usr/bin",
        plugin_root=None,
    )
    assert "CLAUDE_PLUGIN_ROOT=(unset)" in out


# ---------------------------------------------------------------------------
# installed_plugins.json domain-bounded read
# ---------------------------------------------------------------------------


def test_render_shows_only_paper_wiki_entry_from_installed_plugins(
    tmp_path: Path,
) -> None:
    """Domain boundary: never print other plugins' entries (D-9.40.3 invariant)."""
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    _seed_installed_plugins(claude_home, version="0.3.42", extra=True)

    out = render_diag(home=home, claude_home=claude_home)

    assert "paper-wiki" in out  # our entry shown (in installPath / scope etc.)
    assert "other-plugin" not in out, "diag must NEVER print other plugins' entries"
    assert "other-marketplace" not in out


def test_render_handles_malformed_installed_plugins(tmp_path: Path) -> None:
    """Malformed JSON → ``(read failed: <msg>)`` line; never crashes."""
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    bad = claude_home / "plugins" / "installed_plugins.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not-json", encoding="utf-8")

    out = render_diag(home=home, claude_home=claude_home)

    assert "(read failed:" in out
    # The diag must still render the rest of the dump.
    assert "=== end paperwiki_diag ===" in out


# ---------------------------------------------------------------------------
# Read-only / no-secrets contract
# ---------------------------------------------------------------------------


def test_render_does_not_dump_secrets_env(tmp_path: Path) -> None:
    """``render_diag`` must not echo ``secrets.env`` content."""
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    config_dir = home / ".config" / "paper-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "secrets.env").write_text(
        "PAPERWIKI_S2_API_KEY=DO_NOT_LEAK_42\n",
        encoding="utf-8",
    )

    out = render_diag(home=home, claude_home=claude_home)

    assert "DO_NOT_LEAK_42" not in out
    assert "PAPERWIKI_S2_API_KEY" not in out


def test_render_does_not_create_or_modify_files(tmp_path: Path) -> None:
    """``render_diag`` is read-only — no filesystem writes outside ``tmp_path``."""
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    _seed_helper(home, version="0.3.42")
    _seed_recipes(home, "daily.yaml")

    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    _ = render_diag(home=home, claude_home=claude_home)
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    assert before == after, "render_diag must not mutate the filesystem"
