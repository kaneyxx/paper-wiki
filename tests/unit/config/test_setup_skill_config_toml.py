"""Task 9.213 — pin the contract between ``/paper-wiki:setup`` and
the D-V resolver.

The setup SKILL is markdown — it instructs Claude Code to invoke
``Write`` on ``recipes/<name>.yaml`` AND ``config.toml`` (this commit's
deliverable; the SKILL change adds the second write). There is no
Python entry point to call directly, so this test simulates what the
SKILL produces and verifies the resulting config.toml is consumable
by both :func:`paperwiki.config.config_toml.read_config` and the
:func:`paperwiki.config.vault_resolver.resolve_vault` chain.

If a future SKILL refactor changes the file shape (e.g. switches to
JSON or YAML), this test trips and forces an audit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from paperwiki.config.config_toml import read_config, write_config
from paperwiki.config.vault_resolver import resolve_vault

if TYPE_CHECKING:
    from pathlib import Path


def test_setup_skill_writes_resolver_compatible_config_toml(tmp_path: Path) -> None:
    """End-to-end: simulate the SKILL's two-file emission, then verify
    the resolver picks up the vault from config.toml."""
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()

    # Step 9a (existing): SKILL writes recipe.
    recipe_path = paperwiki_home / "recipes" / "daily.yaml"
    recipe_path.parent.mkdir()
    recipe_path.write_text(
        'name: personal-daily\n'
        'reporters:\n'
        '  - name: obsidian\n'
        '    config:\n'
        '      vault_path: "~/Documents/Paper-Wiki"\n',
        encoding="utf-8",
    )

    # Step 9c (NEW in 9.213): SKILL writes config.toml.
    config_path = paperwiki_home / "config.toml"
    write_config(
        config_path,
        default_vault="~/Documents/Paper-Wiki",
        default_recipe=str(recipe_path),
    )

    # Reader picks up both keys.
    cfg = read_config(path=config_path)
    assert cfg.default_vault is not None
    assert cfg.default_recipe is not None

    # Resolver Rung 4 (config.toml) is reachable.
    resolved = resolve_vault(None, config=cfg)
    assert str(resolved).endswith("Documents/Paper-Wiki")


def test_setup_skill_overwrite_must_be_explicit(tmp_path: Path) -> None:
    """Re-running setup must NOT silently clobber an existing config.toml.

    The acceptance criterion says "mirrors recipe-overwrite prompt" —
    the SKILL is responsible for asking the user, then passing
    ``force=True``. The writer's default refusal (without ``force``)
    is the safety floor.
    """
    paperwiki_home = tmp_path / "paper-wiki"
    paperwiki_home.mkdir()
    config_path = paperwiki_home / "config.toml"
    config_path.write_text(
        'default_vault = "~/different-vault"\n',
        encoding="utf-8",
    )

    # Default call (no force) raises — the SKILL must call with force=True
    # only after explicit user confirmation.
    import pytest

    from paperwiki.core.errors import UserError

    with pytest.raises(UserError):
        write_config(
            config_path,
            default_vault="~/Documents/Paper-Wiki",
        )

    # With explicit force=True, overwrite happens (the SKILL's "yes,
    # reconfigure from scratch" path).
    write_config(
        config_path,
        default_vault="~/Documents/Paper-Wiki",
        force=True,
    )
    assert "Documents/Paper-Wiki" in config_path.read_text(encoding="utf-8")
