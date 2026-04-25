"""Built-in filter plugins.

Filters drop or transform papers in the pipeline stream. Each filter
satisfies :class:`paperwiki.core.protocols.Filter`.
"""

from __future__ import annotations

from paperwiki.plugins.filters.recency import RecencyFilter

__all__ = ["RecencyFilter"]
