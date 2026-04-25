"""Unit tests for paperwiki.config.recipe."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperwiki.config.recipe import (
    PluginSpec,
    RecipeSchema,
    instantiate_pipeline,
    load_recipe,
)
from paperwiki.core.errors import UserError
from paperwiki.core.pipeline import Pipeline
from paperwiki.plugins.filters.dedup import DedupFilter, MarkdownVaultKeyLoader
from paperwiki.plugins.filters.recency import RecencyFilter
from paperwiki.plugins.filters.relevance import RelevanceFilter
from paperwiki.plugins.reporters.markdown import MarkdownReporter
from paperwiki.plugins.reporters.obsidian import ObsidianReporter
from paperwiki.plugins.scorers.composite import CompositeScorer
from paperwiki.plugins.sources.arxiv import ArxivSource
from paperwiki.plugins.sources.semantic_scholar import SemanticScholarSource

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


_VALID_RECIPE: dict[str, object] = {
    "name": "daily-arxiv",
    "sources": [
        {"name": "arxiv", "config": {"categories": ["cs.AI"], "lookback_days": 1}},
    ],
    "filters": [
        {"name": "recency", "config": {"max_days": 7}},
    ],
    "scorer": {
        "name": "composite",
        "config": {
            "topics": [{"name": "vlm", "keywords": ["foundation model"]}],
        },
    },
    "reporters": [
        {"name": "markdown", "config": {"output_dir": "./out"}},
    ],
    "top_k": 10,
}


class TestRecipeSchema:
    def test_valid_recipe_parses(self) -> None:
        recipe = RecipeSchema.model_validate(_VALID_RECIPE)
        assert recipe.name == "daily-arxiv"
        assert recipe.top_k == 10
        assert len(recipe.sources) == 1
        assert recipe.sources[0].name == "arxiv"

    def test_sources_required(self) -> None:
        bad = dict(_VALID_RECIPE)
        bad["sources"] = []
        with pytest.raises(ValueError, match="sources"):
            RecipeSchema.model_validate(bad)

    def test_reporters_required(self) -> None:
        bad = dict(_VALID_RECIPE)
        bad["reporters"] = []
        with pytest.raises(ValueError, match="reporters"):
            RecipeSchema.model_validate(bad)

    def test_unknown_top_level_field_rejected(self) -> None:
        bad = dict(_VALID_RECIPE)
        bad["bogus"] = "value"
        with pytest.raises(ValueError, match="bogus"):
            RecipeSchema.model_validate(bad)

    def test_plugin_spec_default_empty_config(self) -> None:
        spec = PluginSpec(name="recency")
        assert spec.config == {}


# ---------------------------------------------------------------------------
# load_recipe
# ---------------------------------------------------------------------------


class TestLoadRecipe:
    def test_loads_valid_recipe(self, tmp_path: Path) -> None:
        path = tmp_path / "r.yaml"
        path.write_text(
            "name: x\n"
            "sources:\n"
            "  - name: arxiv\n"
            "    config:\n"
            "      categories: [cs.AI]\n"
            "scorer:\n"
            "  name: composite\n"
            "  config:\n"
            "    topics:\n"
            "      - name: vlm\n"
            "        keywords: [llm]\n"
            "reporters:\n"
            "  - name: markdown\n"
            "    config:\n"
            "      output_dir: ./out\n",
            encoding="utf-8",
        )
        recipe = load_recipe(path)
        assert recipe.name == "x"

    def test_missing_file_raises_user_error(self, tmp_path: Path) -> None:
        with pytest.raises(UserError, match="failed to read"):
            load_recipe(tmp_path / "missing.yaml")

    def test_invalid_yaml_raises_user_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text(": : not yaml :\n", encoding="utf-8")
        with pytest.raises(UserError, match="not valid YAML"):
            load_recipe(path)

    def test_non_mapping_recipe_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(UserError, match="mapping"):
            load_recipe(path)

    def test_invalid_schema_raises_user_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("name: x\nsources: []\nscorer: {}\nreporters: []\n", encoding="utf-8")
        with pytest.raises(UserError, match="invalid schema"):
            load_recipe(path)


# ---------------------------------------------------------------------------
# instantiate_pipeline
# ---------------------------------------------------------------------------


class TestInstantiatePipeline:
    def test_builds_pipeline_with_built_in_plugins(self, tmp_path: Path) -> None:
        recipe = RecipeSchema.model_validate(
            {
                "name": "full",
                "sources": [
                    {
                        "name": "arxiv",
                        "config": {"categories": ["cs.AI"], "lookback_days": 1},
                    },
                    {
                        "name": "semantic_scholar",
                        "config": {"query": "foundation model", "limit": 10},
                    },
                ],
                "filters": [
                    {"name": "recency", "config": {"max_days": 7}},
                    {
                        "name": "relevance",
                        "config": {"topics": [{"name": "vlm", "keywords": ["foundation model"]}]},
                    },
                    {
                        "name": "dedup",
                        "config": {"vault_paths": [str(tmp_path)]},
                    },
                ],
                "scorer": {
                    "name": "composite",
                    "config": {"topics": [{"name": "vlm", "keywords": ["foundation model"]}]},
                },
                "reporters": [
                    {"name": "markdown", "config": {"output_dir": str(tmp_path)}},
                    {
                        "name": "obsidian",
                        "config": {
                            "vault_path": str(tmp_path),
                            "daily_subdir": "daily",
                        },
                    },
                ],
            }
        )

        pipeline = instantiate_pipeline(recipe)

        assert isinstance(pipeline, Pipeline)
        assert len(pipeline.sources) == 2
        assert isinstance(pipeline.sources[0], ArxivSource)
        assert isinstance(pipeline.sources[1], SemanticScholarSource)

        assert len(pipeline.filters) == 3
        assert isinstance(pipeline.filters[0], RecencyFilter)
        assert isinstance(pipeline.filters[1], RelevanceFilter)
        assert isinstance(pipeline.filters[2], DedupFilter)
        # Dedup loader was constructed from vault_paths.
        assert isinstance(pipeline.filters[2].loaders[0], MarkdownVaultKeyLoader)

        assert isinstance(pipeline.scorer, CompositeScorer)

        assert len(pipeline.reporters) == 2
        assert isinstance(pipeline.reporters[0], MarkdownReporter)
        assert isinstance(pipeline.reporters[1], ObsidianReporter)

    def test_unknown_source_raises_user_error(self) -> None:
        recipe = RecipeSchema.model_validate(_VALID_RECIPE)
        recipe.sources[0] = PluginSpec(name="bogus")
        with pytest.raises(UserError, match="unknown source"):
            instantiate_pipeline(recipe)

    def test_paperclip_source_builds(self) -> None:
        """Recipes can name ``paperclip`` like any other source plugin."""
        from paperwiki.plugins.sources.paperclip import PaperclipSource

        recipe = RecipeSchema.model_validate(
            {
                **_VALID_RECIPE,
                "sources": [
                    {
                        "name": "paperclip",
                        "config": {
                            "query": "vision-language pathology",
                            "limit": 25,
                            "sources": ["biorxiv", "pmc"],
                        },
                    }
                ],
            }
        )
        pipeline = instantiate_pipeline(recipe)
        assert len(pipeline.sources) == 1
        source = pipeline.sources[0]
        assert isinstance(source, PaperclipSource)
        assert source.query == "vision-language pathology"
        assert source.limit == 25
        assert source.sources == ["biorxiv", "pmc"]

    def test_unknown_filter_raises_user_error(self) -> None:
        recipe = RecipeSchema.model_validate(_VALID_RECIPE)
        recipe.filters.append(PluginSpec(name="bogus"))
        with pytest.raises(UserError, match="unknown filter"):
            instantiate_pipeline(recipe)

    def test_unknown_scorer_raises_user_error(self) -> None:
        recipe = RecipeSchema.model_validate(_VALID_RECIPE)
        recipe.scorer = PluginSpec(name="bogus", config={"topics": []})
        with pytest.raises(UserError, match="unknown scorer"):
            instantiate_pipeline(recipe)

    def test_unknown_reporter_raises_user_error(self) -> None:
        recipe = RecipeSchema.model_validate(_VALID_RECIPE)
        recipe.reporters[0] = PluginSpec(name="bogus")
        with pytest.raises(UserError, match="unknown reporter"):
            instantiate_pipeline(recipe)

    def test_paths_expand_user_home(self, tmp_path: Path) -> None:
        recipe = RecipeSchema.model_validate(
            {
                "name": "x",
                "sources": [
                    {
                        "name": "arxiv",
                        "config": {"categories": ["cs.AI"]},
                    }
                ],
                "scorer": {
                    "name": "composite",
                    "config": {"topics": [{"name": "vlm", "keywords": ["x"]}]},
                },
                "reporters": [
                    {
                        "name": "markdown",
                        "config": {"output_dir": "~/some-dir"},
                    },
                ],
            }
        )
        pipeline = instantiate_pipeline(recipe)
        reporter = pipeline.reporters[0]
        assert isinstance(reporter, MarkdownReporter)
        assert "~" not in str(reporter.output_dir)
