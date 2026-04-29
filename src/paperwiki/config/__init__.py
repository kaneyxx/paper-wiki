"""Configuration schemas and recipe loading for paper-wiki.

The two names downstream code is most likely to reach for
(:class:`RecipeSchema` and :func:`load_recipe`) are re-exported at the
package root so callers can write::

    from paperwiki.config import RecipeSchema, load_recipe

without remembering the ``.recipe`` submodule. The full submodule
paths (``paperwiki.config.recipe`` for schema + loader,
``paperwiki.config.recipe_migrations`` for the migration table,
``paperwiki.config.layout`` for vault layout constants) keep working
unchanged — the re-exports are additive.

The shorter spelling matches the user's mental model from the v0.3.35
setup smoke trace and replaces the v0.3.36 F5 forbidden-pattern lint
(plan §14, D-9.37.2 / D-9.37.3).
"""

from __future__ import annotations

from paperwiki.config.recipe import RecipeSchema, load_recipe

__all__ = ["RecipeSchema", "load_recipe"]
