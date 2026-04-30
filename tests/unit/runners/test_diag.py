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
    extra_scopes: bool = False,
) -> Path:
    """Place a stub ``installed_plugins.json`` with the paper-wiki entry.

    Real Claude Code data stores per-plugin entries as a **list of dicts**
    (one dict per scope), not a single dict — see
    ``cli.py:_cache_version`` which iterates ``entries: list``. v0.3.43
    D-9.43.1 fixes a bug where ``runners/diag.py`` double-wrapped this
    list. The fixture now writes the real shape so the regression test
    can pin the correct (single-list) output.

    Pass ``extra_scopes=True`` to seed a second scope entry — exercises
    the multi-scope path that real Claude Code emits when the plugin is
    installed both at user scope and project scope.
    """
    path = claude_home / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    paper_wiki_entries: list[dict[str, object]] = [
        {
            "scope": "user",
            "version": version,
            "installPath": str(
                claude_home / "plugins" / "cache" / "paper-wiki" / "paper-wiki" / version
            ),
        }
    ]
    if extra_scopes:
        paper_wiki_entries.append(
            {
                "scope": "project",
                "version": version,
                "installPath": str(
                    claude_home / "plugins" / "cache" / "paper-wiki" / "paper-wiki" / version
                ),
            }
        )
    plugins: dict[str, object] = {
        "paper-wiki@paper-wiki": paper_wiki_entries,
    }
    if extra:
        plugins["other-plugin@other-marketplace"] = [
            {
                "version": "1.2.3",
                "scope": "user",
            }
        ]
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


# ---------------------------------------------------------------------------
# v0.3.43 D-9.43.1 — installed_plugins entry shape regression
# ---------------------------------------------------------------------------


def test_render_does_not_double_wrap_installed_plugins_list(tmp_path: Path) -> None:
    """Regression for v0.3.43 D-9.43.1: single-list, never double-wrapped.

    Real Claude Code stores ``installed_plugins.json`` entries as a list
    of per-scope dicts. v0.3.42's ``_read_paper_wiki_entry`` wrapped that
    list in another list, producing ``[[{...}]]`` in the diag output.
    This test pins the correct shape — exactly one open bracket before
    the dict — so future refactors can't reintroduce the wrap silently.
    """
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    _seed_installed_plugins(claude_home, version="0.3.43")

    out = render_diag(home=home, claude_home=claude_home)

    # Locate the section header and the JSON that follows.
    marker = "--- installed_plugins.json (paper-wiki entry) ---\n"
    assert marker in out
    body = out.split(marker, 1)[1]
    # The body up to the next "--- " section header is our JSON dump.
    json_chunk = body.split("\n--- ", 1)[0].rstrip("\n")

    # Must start with a single open bracket + a dict (no nested list).
    assert json_chunk.startswith("[\n  {\n"), (
        f"installed_plugins entry must be a single list of dicts, got:\n{json_chunk!r}"
    )
    # And explicitly NOT the double-wrapped form.
    assert not json_chunk.startswith("[\n  [\n"), (
        f"installed_plugins entry must NOT be a list-of-lists, got:\n{json_chunk!r}"
    )


def test_render_handles_multi_scope_installed_plugins_entry(tmp_path: Path) -> None:
    """v0.3.43 D-9.43.1: multi-scope entries (user + project) render
    as a single list with two dicts, not a list-of-lists.
    """
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    _seed_installed_plugins(claude_home, version="0.3.43", extra_scopes=True)

    out = render_diag(home=home, claude_home=claude_home)
    marker = "--- installed_plugins.json (paper-wiki entry) ---\n"
    json_chunk = out.split(marker, 1)[1].split("\n--- ", 1)[0].rstrip("\n")

    # Two scope entries → JSON list with exactly two dicts.
    assert json_chunk.count('"scope": "user"') == 1
    assert json_chunk.count('"scope": "project"') == 1
    assert json_chunk.startswith("[\n  {\n")
    # Sanity: parsing back gives a list of 2.
    parsed = json.loads(json_chunk)
    assert isinstance(parsed, list)
    assert len(parsed) == 2


def test_render_coerces_legacy_dict_shape_for_back_compat(tmp_path: Path) -> None:
    """v0.3.43 D-9.43.1 defensive coercion: a legacy dict-shaped entry
    (hand-edited fixture or ancient Claude Code data) is wrapped to
    ``[entry]`` so the JSON output stays a list — never crashes.

    This guards against a hypothetical future shape change in Claude
    Code's installed_plugins.json. If they revert to a dict shape, our
    diag still emits a parseable list and the tests still pass.
    """
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    legacy_path = claude_home / "plugins" / "installed_plugins.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    # Legacy/hand-edited shape: dict, not list.
    legacy_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "paper-wiki@paper-wiki": {
                        "scope": "user",
                        "version": "0.3.43",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    out = render_diag(home=home, claude_home=claude_home)
    marker = "--- installed_plugins.json (paper-wiki entry) ---\n"
    json_chunk = out.split(marker, 1)[1].split("\n--- ", 1)[0].rstrip("\n")

    # Coerced to a single-element list.
    parsed = json.loads(json_chunk)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["scope"] == "user"
