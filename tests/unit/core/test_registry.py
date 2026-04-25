"""Unit tests for paperwiki.core.registry.

The registry discovers plugins via Python's ``importlib.metadata``
entry-point mechanism. Tests substitute a fake entry-point loader so we
exercise the discovery logic without installing real packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from paperwiki.core import registry
from paperwiki.core.errors import PluginError

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class _FakeEntryPoint:
    """Minimal stand-in for :class:`importlib.metadata.EntryPoint`.

    We only need ``.name`` and ``.load()`` for the registry's contract.
    """

    name: str
    target: Any = None
    error: Exception | None = None
    load_calls: list[str] = field(default_factory=list)

    def load(self) -> Any:
        self.load_calls.append(self.name)
        if self.error is not None:
            raise self.error
        return self.target


class _DummySource:
    name = "dummy"


class _AnotherDummySource:
    name = "another"


def _fake_loader(eps: Iterable[_FakeEntryPoint]) -> registry.EntryPointsLoader:
    """Return an EntryPointsLoader that ignores ``group`` and returns ``eps``."""

    def loader(group: str) -> Iterable[_FakeEntryPoint]:
        # Behave like importlib.metadata.entry_points: filter by group.
        # In our fake we just hand back the prepared list regardless.
        del group
        return eps

    return loader  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Group constants
# ---------------------------------------------------------------------------


class TestGroupConstants:
    def test_group_constants_match_pyproject_namespacing(self) -> None:
        assert registry.SOURCES_GROUP == "paperwiki.sources"
        assert registry.FILTERS_GROUP == "paperwiki.filters"
        assert registry.SCORERS_GROUP == "paperwiki.scorers"
        assert registry.REPORTERS_GROUP == "paperwiki.reporters"


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------


class TestDiscoverPlugins:
    def test_returns_empty_dict_when_no_entry_points(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry, "_load_entry_points", _fake_loader([]))
        assert registry.discover_plugins(registry.SOURCES_GROUP) == {}

    def test_loads_classes_keyed_by_entry_point_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        eps = [
            _FakeEntryPoint(name="arxiv", target=_DummySource),
            _FakeEntryPoint(name="another", target=_AnotherDummySource),
        ]
        monkeypatch.setattr(registry, "_load_entry_points", _fake_loader(eps))

        result = registry.discover_plugins(registry.SOURCES_GROUP)

        assert result == {"arxiv": _DummySource, "another": _AnotherDummySource}

    def test_raises_plugin_error_when_load_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        eps = [
            _FakeEntryPoint(name="broken", error=ImportError("module not found")),
        ]
        monkeypatch.setattr(registry, "_load_entry_points", _fake_loader(eps))

        with pytest.raises(PluginError, match="broken") as excinfo:
            registry.discover_plugins(registry.SOURCES_GROUP)
        assert isinstance(excinfo.value.__cause__, ImportError)

    def test_real_entry_points_call_does_not_raise(self) -> None:
        # End-to-end smoke test: paperwiki has no plugins registered yet,
        # so this must succeed and return an empty mapping.
        result = registry.discover_plugins(registry.SOURCES_GROUP)
        assert result == {}
