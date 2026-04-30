"""Canonical domain models for the paper-wiki pipeline.

These Pydantic models are the source-agnostic representation of every entity
that flows between pipeline stages. They validate aggressively at the
boundary so downstream stages (filters, scorers, reporters) can trust their
inputs without re-checking invariants.

Key invariants enforced here:

* :class:`Author` names and :class:`Paper` titles are non-empty after strip.
* :class:`Paper.canonical_id` is namespaced as ``<source>:<id>`` (e.g.
  ``"arxiv:2506.13063"``); the namespace is normalized to lowercase.
* :class:`Paper.published_at` and :class:`RunContext.target_date` are
  timezone-aware; naive datetimes are rejected to avoid local/UTC drift.
* :class:`ScoreBreakdown` axes are clamped to the closed interval ``[0, 1]``;
  composite scoring requires weights that sum to 1.

All models are mutable by default — pipeline stages may add or update
fields (notably :class:`RunContext.counters` and :class:`Paper.raw`).
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Default weights for :meth:`ScoreBreakdown.compute_composite`. Defined at
# module scope so they are introspectable by recipes and tests.
DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "relevance": 0.40,
    "novelty": 0.20,
    "momentum": 0.30,
    "rigor": 0.10,
}

_CANONICAL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*:[^\s]+$")
_WEIGHT_SUM_TOLERANCE = 1e-6


class Author(BaseModel):
    """A paper author.

    The ``affiliation`` is optional because many sources (notably the bare
    arXiv Atom feed) do not include it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=False)

    name: str = Field(min_length=1)
    affiliation: str | None = None


class Paper(BaseModel):
    """A canonical, source-agnostic paper record.

    The ``raw`` field carries source-specific extras (e.g. arXiv categories
    that did not map to a canonical category) so plugins can read them
    without re-parsing the original API response.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=False)

    canonical_id: str
    title: str = Field(min_length=1)
    authors: list[Author] = Field(min_length=1)
    abstract: str = Field(min_length=1)
    published_at: datetime
    categories: list[str] = Field(default_factory=list)
    pdf_url: str | None = None
    landing_url: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("canonical_id")
    @classmethod
    def _validate_canonical_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "canonical_id must be non-empty"
            raise ValueError(msg)
        # Lowercase the namespace before the colon while preserving the id
        # portion verbatim (case can be meaningful for some sources).
        if ":" in normalized:
            head, rest = normalized.split(":", 1)
            normalized = f"{head.lower()}:{rest}"
        if not _CANONICAL_ID_PATTERN.match(normalized):
            msg = f"canonical_id must be namespaced as '<source>:<id>', got {value!r}"
            raise ValueError(msg)
        return normalized

    @field_validator("title", "abstract")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "value must not be blank"
            raise ValueError(msg)
        return value

    @field_validator("published_at")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            msg = "published_at must be timezone-aware"
            raise ValueError(msg)
        return value


class ScoreBreakdown(BaseModel):
    """Per-axis recommendation score, each in ``[0, 1]``.

    ``composite`` is the weighted aggregate; it can be filled in by a scorer
    plugin or computed via :meth:`compute_composite`.
    """

    model_config = ConfigDict(frozen=False)

    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty: float = Field(default=0.0, ge=0.0, le=1.0)
    momentum: float = Field(default=0.0, ge=0.0, le=1.0)
    rigor: float = Field(default=0.0, ge=0.0, le=1.0)
    composite: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: dict[str, str] = Field(default_factory=dict)

    def compute_composite(self, weights: dict[str, float] | None = None) -> float:
        """Return a weighted aggregate of the four axes.

        The default weights live in :data:`DEFAULT_SCORE_WEIGHTS`. Custom
        weights must cover all four axes and sum to 1 (with a small
        tolerance to allow floating-point inputs).
        """
        applied = weights if weights is not None else DEFAULT_SCORE_WEIGHTS
        required = {"relevance", "novelty", "momentum", "rigor"}
        missing = required - applied.keys()
        if missing:
            msg = f"weights missing axes: {sorted(missing)}"
            raise ValueError(msg)
        total = sum(applied[axis] for axis in required)
        if not math.isclose(total, 1.0, abs_tol=_WEIGHT_SUM_TOLERANCE):
            msg = f"weights must sum to 1, got {total!r}"
            raise ValueError(msg)
        return (
            self.relevance * applied["relevance"]
            + self.novelty * applied["novelty"]
            + self.momentum * applied["momentum"]
            + self.rigor * applied["rigor"]
        )


class Recommendation(BaseModel):
    """A scored, justified pairing of a :class:`Paper` and its score."""

    model_config = ConfigDict(frozen=False)

    paper: Paper
    score: ScoreBreakdown
    matched_topics: list[str] = Field(default_factory=list)
    rationale: str | None = None


class RunContext(BaseModel):
    """Mutable per-run context threaded through every pipeline stage.

    Stages append observability counters via :meth:`increment` so the
    runner can report stats (papers seen, dropped by filter, etc.) at the
    end of a run.
    """

    model_config = ConfigDict(frozen=False)

    target_date: datetime
    config_snapshot: dict[str, Any]
    counters: dict[str, int] = Field(default_factory=dict)

    @field_validator("target_date")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            msg = "target_date must be timezone-aware"
            raise ValueError(msg)
        return value

    def increment(self, key: str, by: int = 1) -> None:
        """Atomically increment a named counter by ``by`` (default 1)."""
        self.counters[key] = self.counters.get(key, 0) + by


# ---------------------------------------------------------------------------
# v0.4.x knowledge graph layer (task 9.156, decision D-L).
#
# ``EdgeType`` is a closed enum at write-time: ``wiki_compile_graph`` (task
# 9.157) only emits canonical values. At read-time the :class:`Edge` model
# accepts unknown string values verbatim and logs a single ``loguru.warning``
# so future on-disk graph data with new edge classes (e.g. shipped by a
# v0.5+ patch, or hand-edited by a power user) round-trips cleanly without
# data loss. ``EdgeType.EXTENSION`` plus the optional ``Edge.subtype``
# field is the forward-compat hook reserved for adding new edge classes
# without enum churn (consensus plan iter-2 R12 / Scenario 7).
# ---------------------------------------------------------------------------


class EdgeType(StrEnum):
    """Canonical wiki-graph edge type (closed enum at write-time).

    Readers preserve unknown values verbatim; only Python emitters are
    constrained to these. Extending the enum in a future paperwiki version
    must keep existing values stable so on-disk graph data stays valid.
    """

    BUILDS_ON = "builds_on"
    IMPROVES_ON = "improves_on"
    SAME_PROBLEM_AS = "same_problem_as"
    CITES = "cites"
    CONTRADICTS = "contradicts"
    # Reserved forward-compat hook: pair with :attr:`Edge.subtype` to add
    # new edge classes in a future minor version without enum churn.
    EXTENSION = "extension"


class Edge(BaseModel):
    """A typed directed edge in the wiki knowledge graph.

    The ``src`` and ``dst`` fields are wikilink targets (slug-like strings,
    e.g. ``"arxiv:2401.00001"`` or ``"concepts/transformer"``); resolving
    them to specific files is the responsibility of
    ``paperwiki.runners.wiki_compile_graph`` (task 9.157).

    Edges are read with a tolerant ``EdgeType | str`` union: the type field
    coerces known canonical strings to the enum and preserves unknown
    strings verbatim (with a one-shot ``loguru.warning``) so on-disk
    ``edges.jsonl`` from a future paperwiki version round-trips without
    data loss.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=False)

    src: str = Field(min_length=1)
    dst: str = Field(min_length=1)
    type: EdgeType | str
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: str | None = None
    # Required when ``type == EdgeType.EXTENSION``; carries the user-defined
    # subtype string. Reserved for v0.5+ migration path.
    subtype: str | None = None

    @field_validator("src", "dst")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "value must not be blank"
            raise ValueError(msg)
        return value

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_or_preserve_type(cls, value: Any) -> EdgeType | str:
        # Already an EdgeType instance — passthrough.
        if isinstance(value, EdgeType):
            return value
        # String input: try to coerce to the canonical enum; if it fails,
        # preserve verbatim so future on-disk values round-trip cleanly.
        if isinstance(value, str):
            try:
                return EdgeType(value)
            except ValueError:
                logger.warning(
                    "edge.type.unknown",
                    value=value,
                    note="preserved verbatim; expected canonical EdgeType",
                )
                return value
        msg = f"type must be EdgeType or str, got {type(value).__name__}"
        raise ValueError(msg)


__all__ = [
    "DEFAULT_SCORE_WEIGHTS",
    "Author",
    "Edge",
    "EdgeType",
    "Paper",
    "Recommendation",
    "RunContext",
    "ScoreBreakdown",
]
