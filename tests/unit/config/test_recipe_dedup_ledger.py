"""Recipe wiring for the dedup ledger (task 9.168 / **D-F** + **D-M**).

When a recipe has both a ``dedup`` filter AND an ``obsidian`` reporter,
the recipe builder auto-engages the persistent dedup ledger by adding
a :class:`DedupLedgerKeyLoader` to the filter's loader list. The
loader points at the obsidian reporter's ``vault_path`` (vault-global
scope per **D-M**) and reads from
``<vault>/.paperwiki/dedup-ledger.jsonl``.

Auto-engagement keeps the user's recipe simple — they don't have to
remember to wire the ledger in two places. Opt-out is available via
``ledger: false`` on the dedup filter config (e.g. for sources-only
recipes that share a vault but don't want cross-recipe dedup).
"""

from __future__ import annotations

from typing import Any

from paperwiki.config.recipe import RecipeSchema, instantiate_pipeline
from paperwiki.plugins.filters.dedup import (
    DedupFilter,
    DedupLedgerKeyLoader,
    MarkdownVaultKeyLoader,
)


def _recipe_with_dedup_and_obsidian(
    *,
    vault_path: str,
    ledger_flag: bool | None = None,
) -> RecipeSchema:
    dedup_config: dict[str, Any] = {"vault_paths": []}
    if ledger_flag is not None:
        dedup_config["ledger"] = ledger_flag
    data = {
        "name": "9168-fixture",
        "sources": [{"name": "arxiv", "config": {"categories": ["cs.AI"], "lookback_days": 1}}],
        "filters": [{"name": "dedup", "config": dedup_config}],
        "scorer": {
            "name": "composite",
            "config": {"topics": [{"name": "vlm", "keywords": ["foundation model"]}]},
        },
        "reporters": [
            {
                "name": "obsidian",
                "config": {"vault_path": vault_path, "daily_subdir": "Daily"},
            }
        ],
        "top_k": 10,
    }
    return RecipeSchema.model_validate(data)


class TestDedupLedgerAutoEngagement:
    def test_obsidian_reporter_auto_adds_ledger_loader(self, tmp_path: str) -> None:
        recipe = _recipe_with_dedup_and_obsidian(vault_path=str(tmp_path))
        pipeline = instantiate_pipeline(recipe)

        dedup = next(f for f in pipeline.filters if isinstance(f, DedupFilter))
        loader_types = [type(loader).__name__ for loader in dedup.loaders]
        assert "DedupLedgerKeyLoader" in loader_types

    def test_recipe_without_obsidian_reporter_skips_ledger(self, tmp_path: str) -> None:
        """No obsidian reporter → no vault-global path to anchor the ledger."""
        data = {
            "name": "9168-no-vault",
            "sources": [{"name": "arxiv", "config": {"categories": ["cs.AI"], "lookback_days": 1}}],
            "filters": [{"name": "dedup", "config": {"vault_paths": []}}],
            "scorer": {
                "name": "composite",
                "config": {"topics": [{"name": "vlm", "keywords": ["foundation model"]}]},
            },
            "reporters": [{"name": "markdown", "config": {"output_dir": str(tmp_path)}}],
            "top_k": 10,
        }
        recipe = RecipeSchema.model_validate(data)
        pipeline = instantiate_pipeline(recipe)

        dedup = next(f for f in pipeline.filters if isinstance(f, DedupFilter))
        loader_types = [type(loader).__name__ for loader in dedup.loaders]
        assert "DedupLedgerKeyLoader" not in loader_types

    def test_explicit_ledger_false_disables_loader(self, tmp_path: str) -> None:
        """Recipes can opt out of the ledger via ``ledger: false`` config."""
        recipe = _recipe_with_dedup_and_obsidian(vault_path=str(tmp_path), ledger_flag=False)
        pipeline = instantiate_pipeline(recipe)

        dedup = next(f for f in pipeline.filters if isinstance(f, DedupFilter))
        loader_types = [type(loader).__name__ for loader in dedup.loaders]
        assert "DedupLedgerKeyLoader" not in loader_types

    def test_existing_vault_paths_loaders_preserved(self, tmp_path: str) -> None:
        """The ledger loader is additive, not a replacement for vault_paths."""
        data = {
            "name": "9168-mixed",
            "sources": [{"name": "arxiv", "config": {"categories": ["cs.AI"], "lookback_days": 1}}],
            "filters": [
                {
                    "name": "dedup",
                    "config": {
                        "vault_paths": [str(tmp_path / "Wiki" / "sources")],
                    },
                }
            ],
            "scorer": {
                "name": "composite",
                "config": {"topics": [{"name": "vlm", "keywords": ["foundation model"]}]},
            },
            "reporters": [
                {
                    "name": "obsidian",
                    "config": {"vault_path": str(tmp_path), "daily_subdir": "Daily"},
                }
            ],
            "top_k": 10,
        }
        recipe = RecipeSchema.model_validate(data)
        pipeline = instantiate_pipeline(recipe)

        dedup = next(f for f in pipeline.filters if isinstance(f, DedupFilter))
        # Both loaders are present.
        assert any(isinstance(loader, MarkdownVaultKeyLoader) for loader in dedup.loaders)
        assert any(isinstance(loader, DedupLedgerKeyLoader) for loader in dedup.loaders)
