"""Recipe schema and instantiator for the paper-wiki pipeline.

A recipe is a YAML file that names plugins by registry key and supplies
their constructor configs. Loading a recipe gives you a
:class:`RecipeSchema`; passing that to :func:`instantiate_pipeline` gives
you a fully-wired :class:`paperwiki.core.pipeline.Pipeline` ready to run.

The instantiator only knows about built-in plugins for now. External
plugin support (via entry points discovered through
:mod:`paperwiki.core.registry`) is a follow-up — once landed it slots in
here without changing the runner CLI.

Plugin configs go through light type coercion at the boundary so YAML
strings can map cleanly to ``Path`` and :class:`Topic`. Unknown plugin
names raise :class:`UserError` with the offending key in the message,
giving recipe authors immediate feedback.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from paperwiki.core.errors import UserError
from paperwiki.core.pipeline import Pipeline
from paperwiki.plugins.filters.dedup import DedupFilter, MarkdownVaultKeyLoader
from paperwiki.plugins.filters.recency import RecencyFilter
from paperwiki.plugins.filters.relevance import RelevanceFilter, Topic
from paperwiki.plugins.reporters.markdown import MarkdownReporter
from paperwiki.plugins.reporters.obsidian import ObsidianReporter
from paperwiki.plugins.scorers.composite import CompositeScorer
from paperwiki.plugins.sources.arxiv import ArxivSource
from paperwiki.plugins.sources.paperclip import PaperclipSource
from paperwiki.plugins.sources.semantic_scholar import SemanticScholarSource

if TYPE_CHECKING:
    from paperwiki.core.protocols import Filter, Reporter, Scorer, Source


class PluginSpec(BaseModel):
    """One plugin entry in a recipe: name + free-form config dict."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class RecipeSchema(BaseModel):
    """Top-level recipe definition.

    ``filters`` defaults to an empty list (a pipeline with no filters
    is legitimate during development). ``sources`` and ``reporters`` are
    required and must each contain at least one entry — see
    :class:`Pipeline` for the same constraint at construction time.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    sources: list[PluginSpec] = Field(min_length=1)
    filters: list[PluginSpec] = Field(default_factory=list)
    scorer: PluginSpec
    reporters: list[PluginSpec] = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1)


def load_recipe(path: Path) -> RecipeSchema:
    """Read and validate a YAML recipe file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"failed to read recipe {path}: {exc}"
        raise UserError(msg) from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"recipe {path} is not valid YAML: {exc}"
        raise UserError(msg) from exc

    if not isinstance(data, dict):
        msg = f"recipe {path} must be a YAML mapping at top level"
        raise UserError(msg)

    try:
        return RecipeSchema.model_validate(data)
    except ValidationError as exc:
        msg = f"recipe {path} has invalid schema: {exc}"
        raise UserError(msg) from exc


def instantiate_pipeline(recipe: RecipeSchema) -> Pipeline:
    """Build a fully-wired :class:`Pipeline` from a recipe."""
    sources = [_build_source(s) for s in recipe.sources]
    filters = [_build_filter(f) for f in recipe.filters]
    scorer = _build_scorer(recipe.scorer)
    reporters = [_build_reporter(r) for r in recipe.reporters]
    return Pipeline(
        sources=sources,
        filters=filters,
        scorer=scorer,
        reporters=reporters,
    )


# ---------------------------------------------------------------------------
# Per-stage builders
# ---------------------------------------------------------------------------


def _build_source(spec: PluginSpec) -> Source:
    if spec.name == "arxiv":
        return ArxivSource(**spec.config)
    if spec.name == "semantic_scholar":
        return SemanticScholarSource(**spec.config)
    if spec.name == "paperclip":
        return PaperclipSource(**spec.config)
    msg = f"unknown source plugin: {spec.name!r}"
    raise UserError(msg)


def _build_filter(spec: PluginSpec) -> Filter:
    if spec.name == "recency":
        return RecencyFilter(**spec.config)
    if spec.name == "relevance":
        topics = _topics_from_config(spec.config.get("topics", []))
        return RelevanceFilter(topics=topics)
    if spec.name == "dedup":
        loaders = [
            MarkdownVaultKeyLoader(root=_expand(p)) for p in spec.config.get("vault_paths", [])
        ]
        return DedupFilter(loaders=loaders)
    msg = f"unknown filter plugin: {spec.name!r}"
    raise UserError(msg)


def _build_scorer(spec: PluginSpec) -> Scorer:
    if spec.name == "composite":
        config = dict(spec.config)
        topics = _topics_from_config(config.pop("topics", []))
        return CompositeScorer(topics=topics, **config)
    msg = f"unknown scorer plugin: {spec.name!r}"
    raise UserError(msg)


def _build_reporter(spec: PluginSpec) -> Reporter:
    if spec.name == "markdown":
        config = dict(spec.config)
        if "output_dir" in config:
            config["output_dir"] = _expand(config["output_dir"])
        return MarkdownReporter(**config)
    if spec.name == "obsidian":
        config = dict(spec.config)
        if "vault_path" in config:
            config["vault_path"] = _expand(config["vault_path"])
        return ObsidianReporter(**config)
    msg = f"unknown reporter plugin: {spec.name!r}"
    raise UserError(msg)


def _topics_from_config(items: list[Any]) -> list[Topic]:
    """Coerce list of dicts (or already-Topic objects) into ``list[Topic]``."""
    result: list[Topic] = []
    for item in items:
        if isinstance(item, Topic):
            result.append(item)
        elif isinstance(item, dict):
            result.append(Topic(**item))
        else:
            msg = f"topic entry must be a mapping, got {type(item).__name__}"
            raise UserError(msg)
    return result


def _expand(value: str | Path) -> Path:
    """Expand ``~`` and resolve to an absolute :class:`Path`."""
    return Path(value).expanduser()


__all__ = [
    "PluginSpec",
    "RecipeSchema",
    "instantiate_pipeline",
    "load_recipe",
]
