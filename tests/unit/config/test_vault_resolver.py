"""Unit tests for ``paperwiki.config.vault_resolver`` (Task 9.192 / D-V).

The resolver is the choke point where every CLI command that needs a
vault path looks up the canonical answer. Pinning the precedence order
in tests keeps "I forgot which env var wins" out of the hot path.

Resolution order (highest priority first):

1. Explicit ``Path`` argument (callers pass ``--vault`` flag here).
2. Recipe's ``obsidian.vault_path`` (when a ``RecipeSchema`` is in scope).
3. ``$PAPERWIKI_DEFAULT_VAULT`` env var.
4. ``config.toml`` ``default_vault`` field.
5. Raise :class:`UserError` with an actionable message.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Test fixtures — env isolation per test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear paper-wiki env vars so each test starts from a clean baseline."""
    for var in (
        "PAPERWIKI_DEFAULT_VAULT",
        "PAPERWIKI_HOME",
        "PAPERWIKI_CONFIG_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


def _fake_recipe_with_obsidian_vault(vault_path: str) -> MagicMock:
    """Build a duck-typed RecipeSchema that surfaces an obsidian reporter."""
    spec = MagicMock()
    spec.name = "obsidian"
    spec.config = {"vault_path": vault_path}
    recipe = MagicMock()
    recipe.reporters = [spec]
    return recipe


def _fake_recipe_without_obsidian(output_dir: Path) -> MagicMock:
    """Recipe with reporters but no obsidian one (markdown-only digest)."""
    spec = MagicMock()
    spec.name = "markdown"
    spec.config = {"output_dir": str(output_dir)}
    recipe = MagicMock()
    recipe.reporters = [spec]
    return recipe


# ---------------------------------------------------------------------------
# Precedence rung 1 — explicit flag
# ---------------------------------------------------------------------------


def test_resolve_vault_explicit_flag_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit Path beats every other rung — including a recipe + env + config."""
    env_vault = tmp_path / "from-env"
    recipe_vault = tmp_path / "from-recipe"
    config_vault = tmp_path / "from-config"
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(env_vault))
    recipe = _fake_recipe_with_obsidian_vault(str(recipe_vault))

    from paperwiki.config.config_toml import ConfigToml
    from paperwiki.config.vault_resolver import resolve_vault

    config = ConfigToml(default_vault=config_vault)
    explicit = tmp_path / "explicit"

    resolved = resolve_vault(explicit, recipe=recipe, config=config)
    assert resolved == explicit


def test_resolve_vault_explicit_path_is_expanduser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``~/foo`` argument is expanded to ``$HOME/foo``."""
    monkeypatch.setenv("HOME", str(tmp_path))

    from paperwiki.config.vault_resolver import resolve_vault

    resolved = resolve_vault(Path("~/Documents/Paper-Wiki"))
    assert resolved == tmp_path / "Documents" / "Paper-Wiki"


# ---------------------------------------------------------------------------
# Precedence rung 2 — recipe.obsidian.vault_path
# ---------------------------------------------------------------------------


def test_resolve_vault_falls_back_to_recipe_when_no_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No explicit flag → recipe's obsidian.vault_path wins over env + config."""
    env_vault = tmp_path / "from-env"
    recipe_vault = tmp_path / "from-recipe"
    config_vault = tmp_path / "from-config"
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(env_vault))
    recipe = _fake_recipe_with_obsidian_vault(str(recipe_vault))

    from paperwiki.config.config_toml import ConfigToml
    from paperwiki.config.vault_resolver import resolve_vault

    config = ConfigToml(default_vault=config_vault)

    resolved = resolve_vault(None, recipe=recipe, config=config)
    assert resolved == recipe_vault


def test_resolve_vault_recipe_without_obsidian_reporter_falls_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recipe present but lacking an obsidian reporter must not bind the
    resolver to the recipe; it should keep falling through to env/config."""
    env_vault = tmp_path / "from-env"
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(env_vault))
    recipe = _fake_recipe_without_obsidian(tmp_path / "out")

    from paperwiki.config.vault_resolver import resolve_vault

    resolved = resolve_vault(None, recipe=recipe)
    assert resolved == env_vault


# ---------------------------------------------------------------------------
# Precedence rung 3 — $PAPERWIKI_DEFAULT_VAULT
# ---------------------------------------------------------------------------


def test_resolve_vault_falls_back_to_env_when_no_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No flag, no recipe → env var wins over config.toml."""
    env_vault = tmp_path / "from-env"
    config_vault = tmp_path / "from-config"
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(env_vault))

    from paperwiki.config.config_toml import ConfigToml
    from paperwiki.config.vault_resolver import resolve_vault

    config = ConfigToml(default_vault=config_vault)

    resolved = resolve_vault(None, config=config)
    assert resolved == env_vault


def test_resolve_vault_env_var_is_expanduser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``$PAPERWIKI_DEFAULT_VAULT=~/foo`` expands to ``$HOME/foo``."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", "~/Documents/Paper-Wiki")

    from paperwiki.config.vault_resolver import resolve_vault

    resolved = resolve_vault(None)
    assert resolved == tmp_path / "Documents" / "Paper-Wiki"


# ---------------------------------------------------------------------------
# Precedence rung 4 — config.toml default_vault
# ---------------------------------------------------------------------------


def test_resolve_vault_falls_back_to_config_toml_when_no_env(
    tmp_path: Path,
) -> None:
    """No flag, no recipe, no env → ``ConfigToml.default_vault`` wins."""
    config_vault = tmp_path / "from-config"

    from paperwiki.config.config_toml import ConfigToml
    from paperwiki.config.vault_resolver import resolve_vault

    config = ConfigToml(default_vault=config_vault)

    resolved = resolve_vault(None, config=config)
    assert resolved == config_vault


def test_resolve_vault_reads_config_when_not_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``config=`` argument → resolver reads the canonical config.toml."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    auto_vault = tmp_path / "auto-loaded"
    (tmp_path / "config.toml").write_text(
        f'default_vault = "{auto_vault}"\n',
        encoding="utf-8",
    )

    from paperwiki.config.vault_resolver import resolve_vault

    resolved = resolve_vault(None)
    assert resolved == auto_vault


# ---------------------------------------------------------------------------
# Precedence rung 5 — actionable error
# ---------------------------------------------------------------------------


def test_resolve_vault_raises_actionable_error_when_all_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All four sources empty → raise with the exact action hint locked in
    plan.md §3.5.5."""
    # Point PAPERWIKI_HOME at an empty dir so config.toml is missing.
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))

    from paperwiki.config.vault_resolver import resolve_vault
    from paperwiki.core.errors import UserError

    with pytest.raises(UserError) as exc_info:
        resolve_vault(None)

    msg = str(exc_info.value)
    # The exact wording is part of the public contract — SKILLs scrape
    # this string to surface the action hint to the user.
    assert "--vault" in msg
    assert "PAPERWIKI_DEFAULT_VAULT" in msg
    assert "/paper-wiki:setup" in msg
    assert "config.toml" in msg
