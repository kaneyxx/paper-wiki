"""Built-in source plugins.

Sources fetch candidate :class:`~paperwiki.core.models.Paper` objects from
external systems. Each source must satisfy
:class:`~paperwiki.core.protocols.Source`.
"""

from __future__ import annotations

from paperwiki.plugins.sources.arxiv import ArxivSource

__all__ = ["ArxivSource"]
