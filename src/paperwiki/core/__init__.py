"""paper-wiki core domain — models, protocols, pipeline, registry, errors.

This package is the stable plumbing the rest of paper-wiki builds on. The
public surface is re-exported here so plugin authors can write::

    from paperwiki.core import Paper, Source

without depending on internal module paths.
"""

from __future__ import annotations

from paperwiki.core.models import (
    DEFAULT_SCORE_WEIGHTS,
    Author,
    Paper,
    Recommendation,
    RunContext,
    ScoreBreakdown,
)

__all__ = [
    "DEFAULT_SCORE_WEIGHTS",
    "Author",
    "Paper",
    "Recommendation",
    "RunContext",
    "ScoreBreakdown",
]
