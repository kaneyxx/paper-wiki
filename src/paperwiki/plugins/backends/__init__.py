"""Built-in wiki backend plugins.

Backends implement :class:`paperwiki.core.protocols.WikiBackend` and
provide the persistence layer for the wiki feature: per-paper source
summaries plus synthesized concept articles. A backend is the I/O half
of the wiki story; SKILLs (driven by Claude) supply the synthesized
prose that backends write.
"""

from __future__ import annotations

from paperwiki.plugins.backends.markdown_wiki import (
    ConceptSummary,
    MarkdownWikiBackend,
    SourceSummary,
)

__all__ = [
    "ConceptSummary",
    "MarkdownWikiBackend",
    "SourceSummary",
]
