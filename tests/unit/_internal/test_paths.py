"""Tests for paperwiki._internal.paths — central path resolution (Task 9.31).

The three resolvers honor an env-var precedence chain:

    PAPERWIKI_VENV_DIR > PAPERWIKI_HOME > PAPERWIKI_CONFIG_DIR > default

Default `PAPERWIKI_HOME = ~/.config/paper-wiki/` per D-9.31.1; recipes
and the shared venv co-locate under it. `PAPERWIKI_CONFIG_DIR` is the
deprecated alias retained for v0.3.4+ compat (D-9.31.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from paperwiki._internal.paths import (
    DEFAULT_HOME,
    resolve_paperwiki_home,
    resolve_paperwiki_recipes_dir,
    resolve_paperwiki_venv_dir,
)

if TYPE_CHECKING:
    import pytest


class TestResolvePaperwikiHome:
    def test_default_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PAPERWIKI_HOME", raising=False)
        monkeypatch.delenv("PAPERWIKI_CONFIG_DIR", raising=False)
        result = resolve_paperwiki_home()
        assert result == Path.home() / ".config" / "paper-wiki"

    def test_default_constant_matches(self) -> None:
        assert Path.home() / ".config" / "paper-wiki" == DEFAULT_HOME

    def test_paperwiki_home_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "custom-home"
        monkeypatch.setenv("PAPERWIKI_HOME", str(target))
        monkeypatch.setenv("PAPERWIKI_CONFIG_DIR", str(tmp_path / "should-be-ignored"))
        assert resolve_paperwiki_home() == target

    def test_legacy_paperwiki_config_dir_used_when_home_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "legacy"
        monkeypatch.delenv("PAPERWIKI_HOME", raising=False)
        monkeypatch.setenv("PAPERWIKI_CONFIG_DIR", str(target))
        assert resolve_paperwiki_home() == target

    def test_empty_string_treated_as_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty env var must NOT clobber the fallback chain."""
        monkeypatch.setenv("PAPERWIKI_HOME", "")
        monkeypatch.setenv("PAPERWIKI_CONFIG_DIR", "")
        assert resolve_paperwiki_home() == Path.home() / ".config" / "paper-wiki"

    def test_tilde_expansion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PAPERWIKI_HOME", "~/custom-pw")
        result = resolve_paperwiki_home()
        # Expanded — no leading tilde remains.
        assert "~" not in str(result)
        assert result == Path.home() / "custom-pw"


class TestResolvePaperwikiVenvDir:
    def test_default_under_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PAPERWIKI_VENV_DIR", raising=False)
        monkeypatch.delenv("PAPERWIKI_HOME", raising=False)
        monkeypatch.delenv("PAPERWIKI_CONFIG_DIR", raising=False)
        result = resolve_paperwiki_venv_dir()
        assert result == Path.home() / ".config" / "paper-wiki" / "venv"

    def test_paperwiki_venv_dir_overrides_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Finer-grained override: venv goes its own way even when HOME is custom."""
        monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("PAPERWIKI_VENV_DIR", str(tmp_path / "just-venv"))
        assert resolve_paperwiki_venv_dir() == tmp_path / "just-venv"

    def test_follows_paperwiki_home_when_venv_dir_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target_home = tmp_path / "ph"
        monkeypatch.setenv("PAPERWIKI_HOME", str(target_home))
        monkeypatch.delenv("PAPERWIKI_VENV_DIR", raising=False)
        assert resolve_paperwiki_venv_dir() == target_home / "venv"

    def test_empty_venv_dir_treated_as_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target_home = tmp_path / "ph"
        monkeypatch.setenv("PAPERWIKI_HOME", str(target_home))
        monkeypatch.setenv("PAPERWIKI_VENV_DIR", "")
        assert resolve_paperwiki_venv_dir() == target_home / "venv"

    def test_full_precedence_chain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PAPERWIKI_VENV_DIR > PAPERWIKI_HOME > PAPERWIKI_CONFIG_DIR > default."""
        # Set all three; venv-dir wins.
        monkeypatch.setenv("PAPERWIKI_VENV_DIR", str(tmp_path / "v"))
        monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path / "h"))
        monkeypatch.setenv("PAPERWIKI_CONFIG_DIR", str(tmp_path / "c"))
        assert resolve_paperwiki_venv_dir() == tmp_path / "v"

        # Drop venv-dir; home wins.
        monkeypatch.delenv("PAPERWIKI_VENV_DIR")
        assert resolve_paperwiki_venv_dir() == tmp_path / "h" / "venv"

        # Drop home; legacy config-dir wins.
        monkeypatch.delenv("PAPERWIKI_HOME")
        assert resolve_paperwiki_venv_dir() == tmp_path / "c" / "venv"

        # Drop config-dir; default.
        monkeypatch.delenv("PAPERWIKI_CONFIG_DIR")
        assert resolve_paperwiki_venv_dir() == Path.home() / ".config" / "paper-wiki" / "venv"


class TestResolvePaperwikiRecipesDir:
    def test_default_is_home_slash_recipes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PAPERWIKI_HOME", raising=False)
        monkeypatch.delenv("PAPERWIKI_CONFIG_DIR", raising=False)
        assert resolve_paperwiki_recipes_dir() == Path.home() / ".config" / "paper-wiki" / "recipes"

    def test_follows_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path / "ph"))
        assert resolve_paperwiki_recipes_dir() == tmp_path / "ph" / "recipes"

    def test_no_separate_override_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Recipes dir ALWAYS hangs off home; no PAPERWIKI_RECIPES_DIR override."""
        monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path / "h"))
        # Setting an unrelated var doesn't change resolution.
        monkeypatch.setenv("PAPERWIKI_RECIPES_DIR", str(tmp_path / "should-be-ignored"))
        assert resolve_paperwiki_recipes_dir() == tmp_path / "h" / "recipes"
