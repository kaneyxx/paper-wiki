"""Error hierarchy for paper-wiki.

Every failure inside the pipeline raises one of the four classes below so
the runner can map it to a stable exit code without inspecting the
message. The mapping is:

================== ============= ===============================================
Exception          ``exit_code`` Meaning
================== ============= ===============================================
:class:`UserError`              1 The user supplied bad input or config.
:class:`IntegrationError`       2 An external service (HTTP, API) failed.
:class:`PluginError`            2 A plugin violated its contract.
:class:`PaperWikiError`         2 Catch-all base; defaults to system-style.
================== ============= ===============================================

We deliberately avoid the name ``SystemError`` because it is a Python
builtin; ``IntegrationError`` and ``PluginError`` together cover what
that would have meant.
"""

from __future__ import annotations


class PaperWikiError(Exception):
    """Root of the paper-wiki exception hierarchy.

    Carries an ``exit_code`` class attribute so callers (in particular
    the runner CLIs) can translate any subclass into a process exit code
    without ``isinstance`` chains.
    """

    exit_code: int = 2


class UserError(PaperWikiError):
    """The user supplied bad input or configuration.

    Examples: missing ``vault_path``, malformed recipe YAML, an unknown
    plugin name in a recipe. The runner exits with code 1 to signal the
    failure is recoverable by the user without bug fixes.
    """

    exit_code: int = 1


class IntegrationError(PaperWikiError):
    """An external service the plugin depends on failed.

    Examples: arXiv API timeout, Semantic Scholar 429 rate limit,
    network unreachable, schema change in an upstream response.
    """

    exit_code: int = 2


class PluginError(PaperWikiError):
    """A plugin violated its contract.

    Examples: a registered plugin does not satisfy the declared
    :class:`~paperwiki.core.protocols.Source` protocol; a custom scorer
    returned ``None`` instead of an iterator of recommendations.
    """

    exit_code: int = 2


__all__ = [
    "IntegrationError",
    "PaperWikiError",
    "PluginError",
    "UserError",
]
