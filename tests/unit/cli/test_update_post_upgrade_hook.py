"""Task 9.212 — ``paperwiki update`` post-upgrade hook auto-creates
``config.toml`` when a recipe with ``vault_path`` exists.

The D-V resolver was designed around
``$PAPERWIKI_HOME/config.toml::default_vault`` as Rung 4, but no code
path actually wrote that file. v0.4.4 → v0.4.6 upgrade therefore left
users with ``recipes/daily.yaml`` containing ``vault_path`` but no
config.toml — every D-V-flavoured CLI command (``dedup-list``,
``wiki-graph`` standalone, etc.) broke.

The hook fires at the end of ``update()`` (both no-op and apply
branches) and bridges the gap by extracting ``vault_path`` from the
single recipe in ``$PAPERWIKI_HOME/recipes/`` and writing a minimal
config.toml — but only when:

* config.toml doesn't exist (idempotent, never clobbers).
* exactly one recipe with ``obsidian.vault_path`` is in scope
  (multi-recipe → silent, don't guess which is canonical).

Tests below cover all eight branches of that decision tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from paperwiki.cli import _post_upgrade_ensure_config_toml
from paperwiki.config.config_toml import read_config

if TYPE_CHECKING:
    from pathlib import Path


def _write_recipe(
    target: Path,
    *,
    name: str = "daily",
    vault_path: str | None = "~/Documents/Paper-Wiki",
) -> None:
    """Helper: emit a minimal recipe YAML."""
    lines = [f"name: {name}"]
    if vault_path is not None:
        lines += [
            "reporters:",
            "  - name: obsidian",
            "    config:",
            f'      vault_path: "{vault_path}"',
        ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_hook_writes_config_when_single_recipe_exists(
    tmp_path: Path, capsys: object
) -> None:
    """Single recipe with ``vault_path`` → config.toml written."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    recipe_path = paperwiki_home / "recipes" / "daily.yaml"
    _write_recipe(recipe_path, vault_path="~/Documents/Paper-Wiki")

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    config_path = paperwiki_home / "config.toml"
    assert config_path.is_file(), "hook must write config.toml"
    cfg = read_config(path=config_path)
    assert cfg.default_vault is not None
    assert str(cfg.default_vault).endswith("Documents/Paper-Wiki")
    assert cfg.default_recipe is not None
    assert str(cfg.default_recipe).endswith("daily.yaml")

    # Visible action message.
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "config.toml" in captured.out
    assert "daily.yaml" in captured.out


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_hook_does_not_overwrite_existing_config(
    tmp_path: Path, capsys: object
) -> None:
    """Existing config.toml is sacrosanct — never clobbered."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    config_path = paperwiki_home / "config.toml"
    config_path.write_text(
        'default_vault = "~/different-vault"\n',
        encoding="utf-8",
    )
    original = config_path.read_text(encoding="utf-8")

    _write_recipe(paperwiki_home / "recipes" / "daily.yaml")
    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    assert config_path.read_text(encoding="utf-8") == original, (
        "hook must NOT clobber an existing config.toml"
    )

    # No action message printed (hook is silent on the existing-file path).
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "config.toml" not in captured.out


def test_hook_idempotent_across_multiple_invocations(
    tmp_path: Path, capsys: object
) -> None:
    """Second call leaves byte-identical file."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    _write_recipe(paperwiki_home / "recipes" / "daily.yaml")

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)
    capsys.readouterr()  # type: ignore[attr-defined]
    after_first = (paperwiki_home / "config.toml").read_text(encoding="utf-8")

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)
    capsys.readouterr()  # type: ignore[attr-defined]
    after_second = (paperwiki_home / "config.toml").read_text(encoding="utf-8")

    assert after_first == after_second, "hook must be idempotent"


# ---------------------------------------------------------------------------
# Silent skip cases
# ---------------------------------------------------------------------------


def test_hook_silent_when_no_recipes_dir(tmp_path: Path, capsys: object) -> None:
    """``recipes/`` directory absent → no write, no log."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    assert not (paperwiki_home / "config.toml").exists()
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]


def test_hook_silent_when_recipes_dir_empty(tmp_path: Path, capsys: object) -> None:
    """``recipes/`` exists but has no YAML files → silent skip."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    (paperwiki_home / "recipes").mkdir()

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    assert not (paperwiki_home / "config.toml").exists()
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]


def test_hook_silent_when_multiple_recipes(tmp_path: Path, capsys: object) -> None:
    """Multi-recipe install → ambiguous, hook refuses to guess."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    _write_recipe(
        paperwiki_home / "recipes" / "daily.yaml",
        name="daily",
        vault_path="~/A",
    )
    _write_recipe(
        paperwiki_home / "recipes" / "weekly.yaml",
        name="weekly",
        vault_path="~/B",
    )

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    assert not (paperwiki_home / "config.toml").exists()
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]


def test_hook_silent_when_recipe_lacks_vault_path(
    tmp_path: Path, capsys: object
) -> None:
    """Single recipe but no ``obsidian.vault_path`` → silent skip."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    _write_recipe(
        paperwiki_home / "recipes" / "daily.yaml",
        vault_path=None,
    )

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    assert not (paperwiki_home / "config.toml").exists()
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]


def test_hook_silent_when_recipe_yaml_unparseable(
    tmp_path: Path, capsys: object
) -> None:
    """Malformed recipe YAML → silent skip (don't crash the upgrade flow)."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    bad = paperwiki_home / "recipes" / "broken.yaml"
    bad.parent.mkdir()
    bad.write_text("[this is not yaml: at all", encoding="utf-8")

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    assert not (paperwiki_home / "config.toml").exists()
    # No traceback, no echo — graceful degradation.
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]


def test_hook_silent_when_paperwiki_home_missing(
    tmp_path: Path, capsys: object
) -> None:
    """``$PAPERWIKI_HOME`` itself doesn't exist → silent skip.

    Defensive: never crash the upgrade flow on filesystem state we
    didn't expect.
    """
    paperwiki_home = tmp_path / "does-not-exist"

    _post_upgrade_ensure_config_toml(paperwiki_home=paperwiki_home)

    assert not paperwiki_home.exists()
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]
