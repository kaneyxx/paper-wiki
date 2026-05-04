"""Resolve a vault path through the D-V precedence chain (Task 9.192).

Decision **D-V** (v0.4.5): every CLI command that needs a vault accepts
``--vault <path>`` (flag) or a positional argument with default ``None``,
and falls through to this resolver. The resolution order is:

1. **Explicit** ``Path`` argument — callers wire the user-supplied
   ``--vault`` flag here. Wins unconditionally.
2. **Recipe** ``obsidian.vault_path`` — when a :class:`RecipeSchema`
   instance is in scope (e.g. ``paperwiki digest``), the recipe's
   obsidian reporter config is the authoritative vault. Skipped silently
   if the recipe has no obsidian reporter.
3. **Env var** ``PAPERWIKI_DEFAULT_VAULT`` — set by power users in shell
   init. Tilde-expanded.
4. **Config file** ``$PAPERWIKI_HOME/config.toml::default_vault`` —
   written by ``/paper-wiki:setup`` on first install (Q3, ratified
   under D-V).
5. **Failure** — raise :class:`UserError` with an actionable hint that
   names every override path. The text is part of the public contract:
   SKILLs scrape it to render the user-facing error.

The resolver is pure with respect to its inputs: a caller that passes
``recipe`` and ``config`` explicitly never touches global state. The
zero-argument convenience path (``resolve_vault(None)``) reads
``os.environ`` and ``$PAPERWIKI_HOME/config.toml`` so single-CLI
commands don't have to plumb both through.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from paperwiki.config.config_toml import ConfigToml, read_config
from paperwiki.core.errors import UserError

if TYPE_CHECKING:
    from paperwiki.config.recipe import RecipeSchema

ENV_VAR = "PAPERWIKI_DEFAULT_VAULT"

ERROR_MESSAGE = (
    "No vault specified. Pass --vault, set PAPERWIKI_DEFAULT_VAULT, "
    "or run /paper-wiki:setup to write ~/.config/paper-wiki/config.toml."
)


def _vault_from_recipe(recipe: object | None) -> Path | None:
    """Pull ``vault_path`` from the recipe's obsidian reporter (if any).

    Mirrors :func:`paperwiki.config.recipe._resolve_obsidian_vault` but
    avoids a circular import — vault_resolver is loaded by config-layer
    callers that the recipe module itself depends on indirectly.
    """
    if recipe is None:
        return None
    reporters = getattr(recipe, "reporters", None)
    if not reporters:
        return None
    for spec in reporters:
        if getattr(spec, "name", None) != "obsidian":
            continue
        config = getattr(spec, "config", None)
        if not isinstance(config, dict):
            continue
        value = config.get("vault_path")
        if isinstance(value, str) and value:
            return Path(value).expanduser()
        if isinstance(value, Path):
            return value.expanduser()
    return None


def resolve_vault(
    explicit: Path | None,
    *,
    recipe: RecipeSchema | None = None,
    config: ConfigToml | None = None,
) -> Path:
    """Resolve the vault path through the D-V precedence chain.

    Parameters
    ----------
    explicit:
        The ``--vault`` flag value (or positional Argument). ``None``
        means "no flag passed" — fall through to the next rung.
    recipe:
        Optional :class:`RecipeSchema`. Used by ``digest``-shaped
        commands that already have a recipe in scope. ``None`` skips
        rung 2.
    config:
        Optional pre-read :class:`ConfigToml`. ``None`` triggers a
        canonical read of ``$PAPERWIKI_HOME/config.toml``.

    Returns
    -------
    Path
        Tilde-expanded path to the vault. Existence is **not** checked
        here — callers that care raise their own targeted error.

    Raises
    ------
    UserError
        When all four rungs come up empty. The message is the canonical
        :data:`ERROR_MESSAGE` string.
    """
    # Rung 1 — explicit flag wins.
    if explicit is not None:
        return explicit.expanduser()

    # Rung 2 — recipe.obsidian.vault_path.
    from_recipe = _vault_from_recipe(recipe)
    if from_recipe is not None:
        return from_recipe

    # Rung 3 — env var.
    raw_env = os.environ.get(ENV_VAR)
    if raw_env:
        return Path(raw_env).expanduser()

    # Rung 4 — config.toml default_vault.
    cfg = config if config is not None else read_config()
    if cfg.default_vault is not None:
        return cfg.default_vault.expanduser()

    # Rung 5 — actionable error.
    raise UserError(ERROR_MESSAGE)


__all__ = [
    "ENV_VAR",
    "ERROR_MESSAGE",
    "resolve_vault",
]
