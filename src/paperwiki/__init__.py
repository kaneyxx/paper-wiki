"""paper-wiki — personal research wiki builder for Claude Code.

This package is the backing implementation for the paper-wiki Claude Code
plugin. It is **not** intended for direct import by end users; SKILLs invoke
its runners via ``python -m paperwiki.runners.<name>``.

The plugin protocol exposed through ``paperwiki.core.protocols`` is marked
``@experimental`` until v1.0.
"""

from __future__ import annotations

__version__ = "0.3.43"

__all__ = ["__version__"]
