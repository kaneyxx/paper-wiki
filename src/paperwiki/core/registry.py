"""Plugin registry — entry-point discovery for paper-wiki.

External plugins register themselves via Python entry points under one of
four groups:

================== ============================================
Group              Plugin role
================== ============================================
``paperwiki.sources``    :class:`~paperwiki.core.protocols.Source`
``paperwiki.filters``    :class:`~paperwiki.core.protocols.Filter`
``paperwiki.scorers``    :class:`~paperwiki.core.protocols.Scorer`
``paperwiki.reporters``  :class:`~paperwiki.core.protocols.Reporter`
================== ============================================

A plugin author publishes a class implementing the appropriate protocol
and registers it in their package's ``pyproject.toml``::

    [project.entry-points."paperwiki.sources"]
    biorxiv = "my_package.biorxiv:BioRxivSource"

After a ``pip install`` of that package, paper-wiki discovers it
automatically; no fork is required.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Protocol

from paperwiki.core.errors import PluginError

if TYPE_CHECKING:
    from collections.abc import Iterable

# Group constants — single source of truth for the entry-point namespace.
SOURCES_GROUP = "paperwiki.sources"
FILTERS_GROUP = "paperwiki.filters"
SCORERS_GROUP = "paperwiki.scorers"
REPORTERS_GROUP = "paperwiki.reporters"


class _EntryPointLike(Protocol):
    """Protocol for the slice of ``importlib.metadata.EntryPoint`` we use."""

    name: str

    def load(self) -> Any: ...


# Type alias for an entry-point loader (test-friendly indirection).
EntryPointsLoader = "Callable[[str], Iterable[_EntryPointLike]]"


def _load_entry_points(group: str) -> Iterable[_EntryPointLike]:
    """Return the entry points registered under ``group``.

    Wrapping :func:`importlib.metadata.entry_points` here gives tests a
    single attribute to monkeypatch.
    """
    return entry_points(group=group)


def discover_plugins(group: str) -> dict[str, type]:
    """Discover and load every plugin registered under ``group``.

    Returns a mapping of entry-point name to the loaded class. If any
    entry point fails to load, raises :class:`PluginError` with the
    underlying exception attached as the cause.
    """
    discovered: dict[str, type] = {}
    for ep in _load_entry_points(group):
        try:
            plugin = ep.load()
        except Exception as exc:
            msg = f"failed to load plugin {ep.name!r} from group {group!r}: {exc}"
            raise PluginError(msg) from exc
        discovered[ep.name] = plugin
    return discovered


__all__ = [
    "FILTERS_GROUP",
    "REPORTERS_GROUP",
    "SCORERS_GROUP",
    "SOURCES_GROUP",
    "EntryPointsLoader",
    "discover_plugins",
]
