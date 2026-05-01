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

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from loguru import logger
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


class ObsidianFlags(BaseModel):
    """Vault-wide Obsidian rendering switches (task 9.162, decision **D-N**).

    These flags are applied uniformly across all reporters and backends so
    a vault stays internally consistent — turning off ``callouts`` for
    one slot and leaving it on for another would create jarring style
    drift in the user's vault.
    """

    model_config = ConfigDict(extra="forbid")

    # ``> [!abstract]`` / ``> [!note]`` / ``> [!warning]`` callouts in
    # digest + analyze output (per **D-N**, default-on; the
    # ``sources-only`` recipe ships with this off so plain-Markdown
    # consumers don't see Obsidian-only syntax).
    callouts: bool = True


# Defaults file shipped with the plugin / co-located with user recipes.
# Per **D-N**, ``recipes/_defaults.yaml`` carries vault-wide overrides
# that apply to every recipe in the same directory; per-recipe values
# always win.
DEFAULTS_FILENAME = "_defaults.yaml"


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
    # Auto-chain ``/paper-wiki:wiki-ingest`` for the top-N papers right
    # after the digest writes. ``0`` (the default) means no chaining —
    # the user invokes wiki-ingest manually per-paper. The hard upper
    # bound of 20 prevents pathological "ingest the entire feed" runs
    # that would burn Claude time. The digest SKILL clamps to
    # ``min(auto_ingest_top, top_k)`` at runtime.
    auto_ingest_top: int = Field(default=0, ge=0, le=20)
    # Vault-wide Obsidian rendering flags (task 9.162, **D-N**). Defaults
    # come from ``recipes/_defaults.yaml`` (if present) and the
    # :class:`ObsidianFlags` field defaults; per-recipe values override.
    obsidian: ObsidianFlags = Field(default_factory=ObsidianFlags)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file and assert it's a mapping at the top level."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"failed to read {path}: {exc}"
        raise UserError(msg) from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"{path} is not valid YAML: {exc}"
        raise UserError(msg) from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = f"{path} must be a YAML mapping at top level"
        raise UserError(msg)
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict that's ``base`` with ``override`` layered on top.

    Nested dicts merge recursively; non-dict values from ``override`` win
    outright. Used for ``_defaults.yaml`` ⊕ per-recipe resolution.
    """
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_defaults(recipe_dir: Path) -> dict[str, Any]:
    """Load ``recipe_dir/_defaults.yaml`` (if any) into a plain dict."""
    defaults_path = recipe_dir / DEFAULTS_FILENAME
    if not defaults_path.is_file():
        return {}
    return _load_yaml_mapping(defaults_path)


def load_recipe(path: Path) -> RecipeSchema:
    """Read and validate a YAML recipe file.

    Per **D-N**: layers ``<recipe_dir>/_defaults.yaml`` (if any) under
    the per-recipe values before validating, so vault-wide flags like
    ``obsidian.callouts`` can be set once for an entire recipe family.
    Loading the defaults file directly is rejected because it lacks the
    required ``name`` / ``sources`` / ``scorer`` / ``reporters`` keys.
    """
    if path.name == DEFAULTS_FILENAME:
        msg = (
            f"{path} is a defaults file, not a recipe; load a sibling recipe to inherit its values"
        )
        raise UserError(msg)

    data = _load_yaml_mapping(path)
    defaults = _load_defaults(path.parent)
    merged = _deep_merge(defaults, data)

    try:
        return RecipeSchema.model_validate(merged)
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
        return SemanticScholarSource(**_resolve_s2_secrets(spec.config))
    if spec.name == "paperclip":
        return PaperclipSource(**spec.config)
    msg = f"unknown source plugin: {spec.name!r}"
    raise UserError(msg)


def _resolve_s2_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``api_key_env`` indirection for the semantic_scholar source.

    Recipe authors are encouraged to keep their S2 API key out of
    version-controlled YAML by referencing an env var instead:

    .. code-block:: yaml

        - name: semantic_scholar
          config:
            api_key_env: PAPERWIKI_S2_API_KEY
            api_key_env_optional: true   # optional, default false

    The env var is resolved at pipeline-build time. By default a missing
    env var raises :class:`UserError` so misconfiguration is loud, not
    silent. Recipes that opt into ``api_key_env_optional: true`` get
    graceful degradation instead — when the env var is unset, the source
    is built with ``api_key=None`` (public S2 endpoint at ~1 req/s) and
    a ``logger.warning`` records the rate-limit downgrade. The starter
    recipes shipped by the setup wizard set this flag so a fresh-install
    user without a key still has a working pipeline (D-9.36.3).
    """
    config = dict(config)
    env_name = config.pop("api_key_env", None)
    optional = bool(config.pop("api_key_env_optional", False))
    if env_name is None:
        return config
    if "api_key" in config:
        msg = (
            "semantic_scholar source: ``api_key`` and ``api_key_env`` are "
            "mutually exclusive. Pick one."
        )
        raise UserError(msg)
    value = os.environ.get(env_name)
    if not value:
        if optional:
            logger.warning(
                "semantic_scholar: S2 API key absent (env var {env_name!r} "
                "unset); rate-limited to ~1 req/s. Populate "
                "~/.config/paper-wiki/secrets.env to enable the 100 req/s rate.",
                env_name=env_name,
            )
            config["api_key"] = None
            return config
        msg = (
            f"semantic_scholar source: env var {env_name!r} is unset or "
            "empty. Either export it (e.g. via "
            "`source ~/.config/paper-wiki/secrets.env`) or set "
            "``api_key`` inline."
        )
        raise UserError(msg)
    config["api_key"] = value
    return config


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
    "DEFAULTS_FILENAME",
    "ObsidianFlags",
    "PluginSpec",
    "RecipeSchema",
    "instantiate_pipeline",
    "load_recipe",
]
