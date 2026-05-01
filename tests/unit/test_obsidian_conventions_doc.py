"""Smoke test for ``references/obsidian-conventions.md`` (task 9.164).

The doc explains the Obsidian-side conventions paper-wiki targets:
Properties API frontmatter (task 9.161 / **D-D**), callout shapes
(task 9.162 / **D-N**), Templater integration (task 9.164), and the
``Wiki/.graph/`` sidecar directory (task 9.157 / **D-B**).

We can't run an Obsidian vault in pytest, so this test verifies the
doc's *contract*: it mentions every frontmatter field paper-wiki
emits, every recipe flag we expose, and the canonical Templater
helpers.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "references" / "obsidian-conventions.md"


def test_doc_exists() -> None:
    assert DOC_PATH.is_file(), (
        f"references/obsidian-conventions.md must ship with v0.4.x "
        f"(task 9.164 acceptance); expected at {DOC_PATH}"
    )


def test_doc_covers_recipe_flags() -> None:
    """Both recipe flags introduced in v0.4.x Phase 2 must be documented."""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "obsidian.callouts" in text, "doc must explain task 9.162 callouts flag"
    assert "obsidian.templater" in text, "doc must explain task 9.164 templater flag"


def test_doc_covers_canonical_templater_helpers() -> None:
    """Doc must show the Templater helpers paper-wiki uses + suggests."""
    text = DOC_PATH.read_text(encoding="utf-8")
    # Date / file family — the variables paper-wiki actually wraps.
    assert "tp.file" in text or "tp.date" in text, (
        "task 9.164 acceptance: doc must demonstrate Templater date/file helpers"
    )


def test_doc_covers_properties_block() -> None:
    """Properties API frontmatter (task 9.161) is the foundation of the
    Obsidian conventions; the doc must document every field."""
    text = DOC_PATH.read_text(encoding="utf-8")
    for field in ("tags", "aliases", "status", "cssclasses", "created", "updated"):
        assert field in text, f"doc must document Properties field {field!r}"
