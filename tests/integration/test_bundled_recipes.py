"""Smoke test: every bundled recipe loads and instantiates a Pipeline.

Catches the most common kind of recipe regression — a YAML key that no
longer matches a plugin's constructor argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paperwiki.config.recipe import DEFAULTS_FILENAME, instantiate_pipeline, load_recipe

RECIPES_DIR = Path(__file__).resolve().parents[2] / "recipes"


@pytest.mark.parametrize(
    "recipe_path",
    # ``_defaults.yaml`` (task 9.162 / **D-N**) is a fall-through layer,
    # not a standalone recipe — load_recipe rejects it by design.
    sorted(p for p in RECIPES_DIR.glob("*.yaml") if p.name != DEFAULTS_FILENAME),
    ids=lambda p: p.name,
)
def test_bundled_recipe_loads_and_instantiates(recipe_path: Path) -> None:
    recipe = load_recipe(recipe_path)
    pipeline = instantiate_pipeline(recipe)

    assert recipe.name
    assert pipeline.sources
    assert pipeline.reporters


def test_daily_arxiv_demonstrates_wiki_backend_flag() -> None:
    """The flagship recipe must show users how to opt in to ``wiki_backend``.

    The reference is intentionally a commented YAML line — we don't want
    to surprise-write into a fresh user's vault on first run, but the
    feature has to be discoverable from the canonical recipe.
    """
    text = (RECIPES_DIR / "daily-arxiv.yaml").read_text(encoding="utf-8")
    assert "wiki_backend" in text, (
        "daily-arxiv.yaml must demonstrate the wiki_backend flag (commented or live)"
    )
