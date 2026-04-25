"""Recency filter — drops papers published before a sliding window.

The window is anchored at ``ctx.target_date`` and extends ``max_days``
days into the past. Anything older is dropped; anything newer (including
future-dated papers, which arXiv occasionally produces under timezone
drift) passes through.

This is the simplest filter and exists primarily to keep the digest
focused on a configurable horizon — daily, weekly, or quarterly recipes
just vary ``max_days``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from paperwiki.core.models import Paper, RunContext


class RecencyFilter:
    """Drop papers older than ``max_days`` relative to ``ctx.target_date``."""

    name = "recency"

    def __init__(self, max_days: int) -> None:
        if max_days <= 0:
            msg = "max_days must be positive"
            raise ValueError(msg)
        self.max_days = max_days

    async def apply(
        self,
        papers: AsyncIterator[Paper],
        ctx: RunContext,
    ) -> AsyncIterator[Paper]:
        cutoff = ctx.target_date - timedelta(days=self.max_days)
        async for paper in papers:
            if paper.published_at >= cutoff:
                yield paper
            else:
                ctx.increment("filter.recency.dropped")


__all__ = ["RecencyFilter"]
