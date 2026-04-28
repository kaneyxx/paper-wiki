"""Integration test for v0.3.29 venv migration (Task 9.31, D-9.31.3).

Exercises ``hooks/ensure-env.sh`` end-to-end against a synthesised
``${PLUGIN_ROOT}/.venv`` real-directory state from <= v0.3.28. After
the hook runs:

1. ``${PLUGIN_ROOT}/.venv`` is now a symlink (not a real directory).
2. The symlink points to ``${PAPERWIKI_HOME}/venv``.
3. The shared venv directory contains the migrated state from the
   legacy per-version venv.
4. The ``.installed`` stamp inside the shared venv carries the
   plugin version.

The bootstrap (uv pip install) step is short-circuited by pre-staging
the stamp content to match ``__version__`` in the fake plugin source.
This test focuses on migration mechanics, not on uv install behavior
(covered separately by the integration smoke when v0.3.29 ships).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_legacy_plugin_root(
    plugin_root: Path,
    *,
    version: str,
    legacy_files: dict[str, str] | None = None,
) -> None:
    """Synthesise a v0.3.28-style cache dir with a real per-version .venv/."""
    init_py = plugin_root / "src" / "paperwiki" / "__init__.py"
    init_py.parent.mkdir(parents=True)
    init_py.write_text(f'__version__ = "{version}"\n', encoding="utf-8")

    legacy_venv = plugin_root / ".venv"
    (legacy_venv / "bin").mkdir(parents=True)
    (legacy_venv / ".installed").write_text(version, encoding="utf-8")
    for relpath, content in (legacy_files or {}).items():
        target = legacy_venv / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _run_hook(plugin_root: Path, home: Path, *, extra_env: dict[str, str] | None = None) -> None:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    if extra_env:
        env.update(extra_env)

    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ensure-env.sh failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


class TestLegacyToSharedMigration:
    def test_real_venv_dir_becomes_symlink(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        _make_legacy_plugin_root(plugin_root, version="0.0.1")

        # Pre-condition: legacy state.
        legacy_venv = plugin_root / ".venv"
        assert legacy_venv.is_dir()
        assert not legacy_venv.is_symlink()

        _run_hook(plugin_root, home)

        # Post-condition: symlink in place.
        assert legacy_venv.is_symlink(), (
            "legacy .venv directory must be replaced with a symlink to the shared venv"
        )

    def test_symlink_target_is_paperwiki_home_venv(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        _make_legacy_plugin_root(plugin_root, version="0.0.1")

        _run_hook(plugin_root, home)

        legacy_venv = plugin_root / ".venv"
        target = legacy_venv.resolve()
        expected = home / ".config" / "paper-wiki" / "venv"
        assert target == expected.resolve(), f"symlink points at {target}, expected {expected}"

    def test_shared_venv_contains_migrated_legacy_files(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        _make_legacy_plugin_root(
            plugin_root,
            version="0.0.1",
            legacy_files={"lib/python3.12/site-packages/sentinel.txt": "from-legacy"},
        )

        _run_hook(plugin_root, home)

        shared = home / ".config" / "paper-wiki" / "venv"
        sentinel = shared / "lib" / "python3.12" / "site-packages" / "sentinel.txt"
        assert sentinel.is_file(), "migration must copy legacy contents into the shared venv"
        assert sentinel.read_text(encoding="utf-8") == "from-legacy"

    def test_stamp_matches_plugin_version(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        _make_legacy_plugin_root(plugin_root, version="0.0.1")

        _run_hook(plugin_root, home)

        stamp = home / ".config" / "paper-wiki" / "venv" / ".installed"
        assert stamp.read_text(encoding="utf-8").strip() == "0.0.1"

    def test_idempotent_second_run(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        _make_legacy_plugin_root(plugin_root, version="0.0.1")

        _run_hook(plugin_root, home)

        # Second run should be a no-op (early exit path).
        legacy_venv = plugin_root / ".venv"
        first_inode = legacy_venv.resolve().stat().st_ino

        _run_hook(plugin_root, home)
        second_inode = legacy_venv.resolve().stat().st_ino
        assert first_inode == second_inode, "shared venv must not be recreated on second run"


class TestPaperwikiHomeOverride:
    def test_paperwiki_home_routes_venv_under_custom_root(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        custom_pw_home = tmp_path / "custom-pw-home"
        _make_legacy_plugin_root(plugin_root, version="0.0.1")

        _run_hook(plugin_root, home, extra_env={"PAPERWIKI_HOME": str(custom_pw_home)})

        target = (plugin_root / ".venv").resolve()
        assert target == (custom_pw_home / "venv").resolve(), (
            f"PAPERWIKI_HOME override should route venv to {custom_pw_home}/venv; got {target}"
        )

    def test_legacy_paperwiki_config_dir_alias_works(self, tmp_path: Path) -> None:
        """Backward compat: PAPERWIKI_CONFIG_DIR (v0.3.4+) still routes the venv."""
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        legacy_config = tmp_path / "legacy-config"
        _make_legacy_plugin_root(plugin_root, version="0.0.1")

        _run_hook(plugin_root, home, extra_env={"PAPERWIKI_CONFIG_DIR": str(legacy_config)})

        target = (plugin_root / ".venv").resolve()
        assert target == (legacy_config / "venv").resolve(), (
            "PAPERWIKI_CONFIG_DIR alias should still route the venv"
        )

    def test_paperwiki_venv_dir_finer_grained_override(self, tmp_path: Path) -> None:
        """PAPERWIKI_VENV_DIR overrides JUST the venv even when HOME is set."""
        plugin_root = tmp_path / "cache" / "paper-wiki" / "0.0.1"
        home = tmp_path / "home"
        home.mkdir()
        custom_home = tmp_path / "custom-home"
        custom_venv = tmp_path / "just-venv"
        _make_legacy_plugin_root(plugin_root, version="0.0.1")

        _run_hook(
            plugin_root,
            home,
            extra_env={
                "PAPERWIKI_HOME": str(custom_home),
                "PAPERWIKI_VENV_DIR": str(custom_venv),
            },
        )

        target = (plugin_root / ".venv").resolve()
        assert target == custom_venv.resolve(), (
            "PAPERWIKI_VENV_DIR should win over PAPERWIKI_HOME for venv path"
        )
