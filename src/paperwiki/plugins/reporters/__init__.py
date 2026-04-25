"""Built-in reporter plugins."""

from __future__ import annotations

from paperwiki.plugins.reporters.markdown import MarkdownReporter
from paperwiki.plugins.reporters.obsidian import ObsidianReporter

__all__ = ["MarkdownReporter", "ObsidianReporter"]
