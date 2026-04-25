"""Built-in filter plugins.

Filters drop or transform papers in the pipeline stream. Each filter
satisfies :class:`paperwiki.core.protocols.Filter`.
"""

from __future__ import annotations

from paperwiki.plugins.filters.recency import RecencyFilter
from paperwiki.plugins.filters.relevance import RelevanceFilter, Topic

__all__ = ["RecencyFilter", "RelevanceFilter", "Topic"]
