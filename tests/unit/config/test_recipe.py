"""Unit tests for paperwiki.config.recipe."""

from __future__ import annotations

import logging
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

    def test_auto_ingest_top_defaults_to_zero(self) -> None:
        """Default behavior: no auto-ingest. The digest SKILL only chains
        wiki-ingest when the recipe explicitly opts in."""
        recipe = RecipeSchema.model_validate(_VALID_RECIPE)
        assert recipe.auto_ingest_top == 0

    def test_auto_ingest_top_accepts_positive_integers(self) -> None:
        recipe = RecipeSchema.model_validate({**_VALID_RECIPE, "auto_ingest_top": 3})
        assert recipe.auto_ingest_top == 3

    def test_auto_ingest_top_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="auto_ingest_top"):
            RecipeSchema.model_validate({**_VALID_RECIPE, "auto_ingest_top": -1})

    def test_auto_ingest_top_capped_at_top_k(self) -> None:
        """Logically a user cannot auto-ingest more papers than they
        actually rank into the top-K. Schema accepts up to 20 for
        future-proofing; SKILL clamps to ``min(auto_ingest_top, top_k)``."""
        # Schema-level upper bound is 20.
        recipe = RecipeSchema.model_validate({**_VALID_RECIPE, "auto_ingest_top": 20})
        assert recipe.auto_ingest_top == 20
        with pytest.raises(ValueError, match="auto_ingest_top"):
            RecipeSchema.model_validate({**_VALID_RECIPE, "auto_ingest_top": 21})


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

    def test_semantic_scholar_resolves_api_key_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recipes can name an env var instead of inlining the API key.

        Inline ``api_key: <hex>`` is brittle — it leaks into recipe
        files that may be shared, version-controlled, or pasted into
        tickets. ``api_key_env: PAPERWIKI_S2_API_KEY`` indirects through
        the env so the secret stays in ``~/.config/paper-wiki/secrets.env``
        (which lives outside the repo).
        """
        from paperwiki.plugins.sources.semantic_scholar import SemanticScholarSource

        monkeypatch.setenv("PAPERWIKI_S2_TEST_KEY", "the-real-key")

        recipe = RecipeSchema.model_validate(
            {
                **_VALID_RECIPE,
                "sources": [
                    {
                        "name": "semantic_scholar",
                        "config": {
                            "query": "vision-language",
                            "lookback_days": 7,
                            "api_key_env": "PAPERWIKI_S2_TEST_KEY",
                        },
                    }
                ],
            }
        )
        pipeline = instantiate_pipeline(recipe)
        source = pipeline.sources[0]
        assert isinstance(source, SemanticScholarSource)
        assert source.api_key == "the-real-key"

    def test_semantic_scholar_missing_env_var_raises_user_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Misconfigured env name surfaces a UserError, not silent ``None``."""
        monkeypatch.delenv("PAPERWIKI_S2_NOT_SET", raising=False)

        recipe = RecipeSchema.model_validate(
            {
                **_VALID_RECIPE,
                "sources": [
                    {
                        "name": "semantic_scholar",
                        "config": {
                            "query": "x",
                            "lookback_days": 7,
                            "api_key_env": "PAPERWIKI_S2_NOT_SET",
                        },
                    }
                ],
            }
        )
        with pytest.raises(UserError, match="PAPERWIKI_S2_NOT_SET"):
            instantiate_pipeline(recipe)

    # -----------------------------------------------------------------
    # v0.3.36 D-9.36.3 — graceful degradation for unset S2 key
    # -----------------------------------------------------------------
    #
    # Matrix coverage (api_key_env_optional x env-var presence):
    #   (True,  set)     -> resolves to the env value
    #   (True,  unset)   -> warning, api_key=None, source still constructs
    #   (False, set)     -> resolves to the env value (existing behavior)
    #   (False, unset)   -> raises UserError (backwards-compatible default)

    def test_s2_optional_flag_with_env_set_resolves_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from paperwiki.plugins.sources.semantic_scholar import SemanticScholarSource

        monkeypatch.setenv("PAPERWIKI_S2_OPT_KEY", "real-key-value")

        recipe = RecipeSchema.model_validate(
            {
                **_VALID_RECIPE,
                "sources": [
                    {
                        "name": "semantic_scholar",
                        "config": {
                            "query": "x",
                            "lookback_days": 7,
                            "api_key_env": "PAPERWIKI_S2_OPT_KEY",
                            "api_key_env_optional": True,
                        },
                    }
                ],
            }
        )
        pipeline = instantiate_pipeline(recipe)
        source = pipeline.sources[0]
        assert isinstance(source, SemanticScholarSource)
        assert source.api_key == "real-key-value"

    def test_s2_optional_flag_with_env_unset_warns_and_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``api_key_env_optional: true`` + unset env → warning + ``api_key=None``."""
        from paperwiki.plugins.sources.semantic_scholar import SemanticScholarSource

        monkeypatch.delenv("PAPERWIKI_S2_OPT_MISSING", raising=False)

        recipe = RecipeSchema.model_validate(
            {
                **_VALID_RECIPE,
                "sources": [
                    {
                        "name": "semantic_scholar",
                        "config": {
                            "query": "x",
                            "lookback_days": 7,
                            "api_key_env": "PAPERWIKI_S2_OPT_MISSING",
                            "api_key_env_optional": True,
                        },
                    }
                ],
            }
        )

        # loguru -> stdlib propagation: install a sink that mirrors into caplog.
        from loguru import logger

        handler_id = logger.add(
            lambda msg: caplog.records.append(  # type: ignore[arg-type]
                logging.LogRecord(
                    name="loguru",
                    level=logging.WARNING,
                    pathname="",
                    lineno=0,
                    msg=str(msg),
                    args=(),
                    exc_info=None,
                )
            ),
            level="WARNING",
            format="{message}",
        )
        try:
            pipeline = instantiate_pipeline(recipe)
        finally:
            logger.remove(handler_id)

        source = pipeline.sources[0]
        assert isinstance(source, SemanticScholarSource)
        assert source.api_key is None

        warning_messages = [r.getMessage() for r in caplog.records]
        assert any("rate-limited" in m or "1 req/s" in m for m in warning_messages), (
            f"expected a 'rate-limited' / '1 req/s' warning, got {warning_messages!r}"
        )

    def test_s2_optional_false_with_env_unset_still_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default (``api_key_env_optional: false``) keeps the loud-fail contract."""
        monkeypatch.delenv("PAPERWIKI_S2_REQUIRED", raising=False)

        recipe = RecipeSchema.model_validate(
            {
                **_VALID_RECIPE,
                "sources": [
                    {
                        "name": "semantic_scholar",
                        "config": {
                            "query": "x",
                            "lookback_days": 7,
                            "api_key_env": "PAPERWIKI_S2_REQUIRED",
                            "api_key_env_optional": False,
                        },
                    }
                ],
            }
        )
        with pytest.raises(UserError, match="PAPERWIKI_S2_REQUIRED"):
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
                            "since_days": 14,
                            "journal": "Nature",
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
        assert source.since_days == 14
        assert source.journal == "Nature"

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


# ---------------------------------------------------------------------------
# v0.3.37 D-9.37.2 — package-root re-exports
# ---------------------------------------------------------------------------
#
# The setup smoke trace from v0.3.35 showed Claude reaching for
# `from paperwiki.config import RecipeSchema` (no `.recipe.` segment),
# which historically raised ImportError because `__init__.py` was an
# empty stub. v0.3.37 re-exports `RecipeSchema` and `load_recipe` at
# the package root so the user's mental model matches reality. The
# replacement for the v0.3.36 F5 forbidden-pattern lint (D-9.37.3) is
# this positive-import smoke test — if the re-export ever breaks, the
# test catches it.


class TestPackageRootReExports:
    def test_recipe_schema_importable_from_package_root(self) -> None:
        from paperwiki.config import RecipeSchema as PackageRoot

        assert PackageRoot is RecipeSchema, (
            "paperwiki.config.RecipeSchema must be the same object as "
            "paperwiki.config.recipe.RecipeSchema (re-export, not a copy)."
        )
        assert hasattr(PackageRoot, "model_validate"), (
            "Re-exported RecipeSchema must still be a pydantic BaseModel."
        )

    def test_load_recipe_importable_from_package_root(self) -> None:
        from paperwiki.config import load_recipe as package_root_load

        assert package_root_load is load_recipe, (
            "paperwiki.config.load_recipe must be the same object as "
            "paperwiki.config.recipe.load_recipe (re-export, not a copy)."
        )
        assert callable(package_root_load)

    def test_dunder_all_advertises_the_re_exports(self) -> None:
        import paperwiki.config as config_pkg

        assert hasattr(config_pkg, "__all__"), (
            "paperwiki.config must declare __all__ so `from paperwiki.config "
            "import *` lands the documented surface."
        )
        assert set(config_pkg.__all__) == {"RecipeSchema", "load_recipe"}, (
            f"__all__ should contain exactly the re-exports per D-9.37.2; "
            f"got {config_pkg.__all__!r}"
        )
