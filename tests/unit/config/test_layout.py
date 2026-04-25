"""Tests for paperwiki.config.layout default subdir constants."""

from __future__ import annotations

from paperwiki.config import layout


def test_friendly_defaults_no_numeric_prefixes() -> None:
    """Defaults must not carry Johnny.Decimal / PARA numeric prefixes."""
    assert layout.DAILY_SUBDIR == "Daily"
    assert layout.SOURCES_SUBDIR == "Sources"
    assert layout.WIKI_SUBDIR == "Wiki"
    for value in (layout.DAILY_SUBDIR, layout.SOURCES_SUBDIR, layout.WIKI_SUBDIR):
        assert not value[0].isdigit(), f"unexpected numeric prefix: {value!r}"
        assert "_" not in value, f"unexpected underscore: {value!r}"


def test_constants_are_simple_strings() -> None:
    for value in (layout.DAILY_SUBDIR, layout.SOURCES_SUBDIR, layout.WIKI_SUBDIR):
        assert isinstance(value, str)
        assert value.strip() == value
