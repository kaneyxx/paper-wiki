"""Smoke test: every bundled recipe loads and instantiates a Pipeline.

Catches the most common kind of recipe regression — a YAML key that no
longer matches a plugin's constructor argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paperwiki.config.recipe import instantiate_pipeline, load_recipe

RECIPES_DIR = Path(__file__).resolve().parents[2] / "recipes"


@pytest.mark.parametrize(
    "recipe_path",
    sorted(RECIPES_DIR.glob("*.yaml")),
    ids=lambda p: p.name,
)
def test_bundled_recipe_loads_and_instantiates(recipe_path: Path) -> None:
    recipe = load_recipe(recipe_path)
    pipeline = instantiate_pipeline(recipe)

    assert recipe.name
    assert pipeline.sources
    assert pipeline.reporters
