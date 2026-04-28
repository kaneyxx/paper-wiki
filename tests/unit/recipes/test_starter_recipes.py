"""Pin v0.3.33 starter-recipe defang.

Background: in v0.3.32 ``recipes/daily-arxiv.yaml`` shipped with
``vault_path: ~/Documents/Obsidian-Vault`` as the bundled default. When
the digest SKILL fell through to the bundled starter (the v0.3.32 bug),
the runner happily wrote into the user's UNRELATED Obsidian vault.

v0.3.33 replaces every real default path in starter recipes with the
placeholder ``<EDIT_ME_BEFORE_USE>`` so even if the SKILL fallback path
fires, the runner fails loud at path resolution rather than silently
clobbering a real vault.

The example documentation at ``docs/example-recipes/`` is intentionally
exempt — those files document real layout patterns for users to adapt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RECIPES_DIR = REPO_ROOT / "recipes"

PLACEHOLDER = "<EDIT_ME_BEFORE_USE>"


@pytest.mark.parametrize(
    "recipe_path",
    sorted(RECIPES_DIR.glob("*.yaml")),
    ids=lambda p: p.name,
)
def test_starter_recipe_vault_paths_are_defanged(recipe_path: Path) -> None:
    """Every starter recipe must use the EDIT_ME placeholder for vault_path /
    output_dir. No real path defaults are allowed in the bundled set.
    """
    data: dict[str, Any] = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))

    # Reporters: vault_path (obsidian) + output_dir (markdown) must be the
    # placeholder.
    for reporter in data.get("reporters", []):
        config = reporter.get("config", {}) or {}
        if "vault_path" in config:
            assert config["vault_path"] == PLACEHOLDER, (
                f"{recipe_path.name}: reporter `{reporter.get('name')}` has a real "
                f"vault_path default ({config['vault_path']!r}). v0.3.33 requires "
                f"`{PLACEHOLDER}` so users must edit before use."
            )
        if "output_dir" in config:
            assert config["output_dir"] == PLACEHOLDER, (
                f"{recipe_path.name}: reporter `{reporter.get('name')}` has a real "
                f"output_dir default ({config['output_dir']!r}). v0.3.33 requires "
                f"`{PLACEHOLDER}` so users must edit before use."
            )

    # Filters: dedup.vault_paths entries pointing at real directories must
    # also be defanged.
    for filt in data.get("filters", []) or []:
        if filt.get("name") != "dedup":
            continue
        config = filt.get("config", {}) or {}
        for vp in config.get("vault_paths", []) or []:
            assert vp == PLACEHOLDER, (
                f"{recipe_path.name}: dedup filter has a real vault_paths "
                f"entry ({vp!r}). v0.3.33 requires `{PLACEHOLDER}` so users "
                f"must edit before use."
            )


def test_daily_arxiv_recipe_uses_placeholder() -> None:
    """Hard pin on the flagship recipe — it was the proximate cause of the v0.3.32 bug."""
    body = (RECIPES_DIR / "daily-arxiv.yaml").read_text(encoding="utf-8")
    # No real Obsidian-Vault default may appear anywhere in the file.
    assert "~/Documents/Obsidian-Vault" not in body, (
        "daily-arxiv.yaml must not contain `~/Documents/Obsidian-Vault` as a "
        "default — that path silently clobbered the user's unrelated vault in v0.3.32"
    )
    assert "~/paper-wiki/digests" not in body, (
        "daily-arxiv.yaml must not contain `~/paper-wiki/digests` as the markdown "
        "reporter default; use the EDIT_ME placeholder instead"
    )
    assert PLACEHOLDER in body, (
        f"daily-arxiv.yaml must contain `{PLACEHOLDER}` somewhere as the "
        f"defanged default for vault_path / output_dir"
    )
