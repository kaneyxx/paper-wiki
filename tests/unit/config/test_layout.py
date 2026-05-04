"""Tests for paperwiki.config.layout default subdir constants.

Task 9.184 (D-T + D-Z) introduces ``PAPERS_SUBDIR = "papers"`` and
``LEGACY_PAPERS_SUBDIR = "sources"``, deletes the unused
``SOURCES_SUBDIR`` constant (Q1 ratified — vault root ``Sources/``
was never written by any runner), and applies the **D-Z anti-hardcode
rule**: any module that writes to a vault subdir imports the path
constant from this module rather than declaring its own. The two
guard tests below pin the rule so the v0.5.0 cleanup window stays
auditable.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from paperwiki.config import layout


def test_friendly_defaults_no_numeric_prefixes() -> None:
    """Defaults must not carry Johnny.Decimal / PARA numeric prefixes."""
    assert layout.DAILY_SUBDIR == "Daily"
    assert layout.PAPERS_SUBDIR == "papers"
    assert layout.WIKI_SUBDIR == "Wiki"
    for value in (layout.DAILY_SUBDIR, layout.PAPERS_SUBDIR, layout.WIKI_SUBDIR):
        assert not value[0].isdigit(), f"unexpected numeric prefix: {value!r}"
        assert "_" not in value, f"unexpected underscore: {value!r}"


def test_constants_are_simple_strings() -> None:
    for value in (layout.DAILY_SUBDIR, layout.PAPERS_SUBDIR, layout.WIKI_SUBDIR):
        assert isinstance(value, str)
        assert value.strip() == value


def test_papers_subdir_is_canonical_v04_target() -> None:
    """v0.4.2 D-T: ``Wiki/papers/`` is the canonical per-paper subdir.

    The legacy v0.3.x layout wrote to ``Wiki/sources/``; the read-only
    back-compat name lives in ``LEGACY_PAPERS_SUBDIR`` for one
    release (drops in v0.5.0).
    """
    assert layout.PAPERS_SUBDIR == "papers"
    assert layout.LEGACY_PAPERS_SUBDIR == "sources"
    # The two names must be different — same value would defeat the
    # whole purpose of the read-fallback shim.
    assert layout.PAPERS_SUBDIR != layout.LEGACY_PAPERS_SUBDIR


def test_legacy_papers_subdir_exported_in_all() -> None:
    """``LEGACY_PAPERS_SUBDIR`` must be in ``__all__`` so v0.5.0
    cleanup can grep for the name and delete every reference.
    """
    assert "LEGACY_PAPERS_SUBDIR" in layout.__all__
    assert "PAPERS_SUBDIR" in layout.__all__


def test_sources_subdir_constant_removed() -> None:
    """Q1 ratified: vault root ``Sources/`` (capital S) was never
    written by any runner. The constant is deleted in 9.184; this
    test pins the deletion so a future revival raises immediately.
    """
    assert not hasattr(layout, "SOURCES_SUBDIR"), (
        "SOURCES_SUBDIR was deleted in Task 9.184 (D-T). If you need "
        "the legacy v0.3.x subdir name, use LEGACY_PAPERS_SUBDIR "
        "instead — it's the read-only back-compat name with a "
        "scheduled v0.5.0 deletion target."
    )


def test_d_z_no_hardcoded_subdir_paths_in_backends() -> None:
    """D-Z anti-hardcode rule: backend modules import the path
    constants from ``paperwiki.config.layout`` rather than declaring
    their own.

    The guard is intentionally narrow — it only catches *path-context*
    string literals, not arbitrary ``"sources"``-shaped string usages
    such as YAML frontmatter schema keys (which are user-facing field
    names that must remain stable for back-compat across releases).
    Two patterns are flagged:

    * ``_<NAME>_DIRNAME = "<dir>"`` — the original sin from v0.4.0
      (``markdown_wiki.py:48``).
    * ``/ "<dir>"`` or ``/ '<dir>'`` — :class:`pathlib.Path`
      concatenation with a forbidden literal.
    """
    repo_root = Path(__file__).resolve().parents[3]
    backends_root = repo_root / "src" / "paperwiki" / "plugins" / "backends"
    assert backends_root.is_dir(), f"expected dir not found: {backends_root}"

    forbidden = {"sources", "papers", "concepts", "topics", "people"}
    alt = "|".join(forbidden)
    dirname_re = re.compile(r"_[A-Z_]*_DIRNAME\s*=\s*['\"](" + alt + r")['\"]")
    path_concat_re = re.compile(r"/\s*['\"](" + alt + r")['\"]")

    offenders: list[tuple[Path, int, str]] = []
    for module in backends_root.rglob("*.py"):
        for line_no, raw in enumerate(module.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = raw.strip()
            if stripped.startswith("#"):
                continue
            if dirname_re.search(raw) or path_concat_re.search(raw):
                offenders.append((module, line_no, raw.rstrip()))

    if offenders:
        formatted = "\n".join(f"  {path}:{ln}  {text}" for path, ln, text in offenders)
        pytest.fail(
            "D-Z anti-hardcode rule violation — backend modules must import "
            "subdir constants from paperwiki.config.layout instead of literal "
            f"path strings:\n{formatted}"
        )
