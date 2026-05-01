"""Regression guard for Obsidian-style image embeds (task 9.165).

Per **D-D**, paper-wiki targets Obsidian as a first-class deployment
surface. That means image embeds use the Obsidian wikilink shape
(``![[image.png|width]]``) instead of CommonMark
(``![alt](path)``) — the wikilink form survives vault sync, supports
the ``|width`` size hint, and shows up correctly in Obsidian's
preview, graph view, and "linked mentions" pane.

The acceptance contract for v0.4.x:

* All reporters that emit images use the Obsidian wikilink shape.
* ``extract_paper_images`` writes wikilinks for both the per-figure
  embed and the manifest at ``Wiki/sources/<id>/images/index.md``.
* The plain ``markdown`` reporter emits NO images at all (it stays
  vault-agnostic; users on plain Markdown viewers don't get embeds).

This test enforces the contract by scanning every Python source that
*could* emit an image and asserting:
1. CommonMark ``![alt](path)`` substrings never appear in literal
   strings (code that writes those bytes is the regression we're
   guarding against).
2. Every f-string emitting ``![[...]]`` is co-located in a module
   that explicitly targets Obsidian.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Modules that legitimately emit image embeds. Anything outside this
# allowlist must NOT contain ``![[`` patterns.
OBSIDIAN_TARGETED_MODULES = frozenset(
    {
        "src/paperwiki/plugins/reporters/obsidian.py",
        "src/paperwiki/runners/extract_paper_images.py",
    }
)

# Files we must avoid altogether for image emits (legacy CommonMark).
FORBIDDEN_PATTERNS = (
    # CommonMark image syntax embedded in an f-string or string literal.
    # Catches ``f"![alt](path/to/img.png)"`` and similar.
    re.compile(r'(?:f?["\'])!\[[^\]]*\]\(\s*[^)\s]+\.\w{2,4}\s*\)'),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_commonmark_image_emit_in_source() -> None:
    """No source file under ``src/`` may write CommonMark image syntax to disk.

    This catches the regression where a contributor swaps an Obsidian
    wikilink embed for a CommonMark one, e.g. when porting a snippet
    from non-Obsidian docs.
    """
    src_root = REPO_ROOT / "src" / "paperwiki"
    offenders: list[tuple[Path, str]] = []
    for path in src_root.rglob("*.py"):
        text = _read(path)
        for pattern in FORBIDDEN_PATTERNS:
            offenders.extend((path, match.group(0)) for match in pattern.finditer(text))

    assert not offenders, (
        "CommonMark image syntax leaked into source — paper-wiki targets "
        f"Obsidian wikilinks (![[...]]) per task 9.165. Offenders: "
        f"{[(str(p.relative_to(REPO_ROOT)), s) for p, s in offenders]}"
    )


def test_wikilink_image_embeds_only_in_obsidian_targeted_modules() -> None:
    """``![[<file>]]`` embeds may only originate in Obsidian-targeted modules.

    This protects the ``markdown`` reporter (vault-agnostic) and any
    future plain-Markdown surface from accidentally inheriting the
    Obsidian-only wikilink shape.
    """
    src_root = REPO_ROOT / "src" / "paperwiki"
    # Only flag wikilink embeds that look like an actual emit — i.e.
    # appear inside an f-string or string literal (single/double quote
    # immediately preceding ``![[``). Doc-comments / docstrings that
    # *describe* the syntax don't count as emits.
    pattern = re.compile(r'(?:f?["\'])!\[\[[^\]]+\]\]')
    offenders: list[Path] = []
    for path in src_root.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in OBSIDIAN_TARGETED_MODULES:
            continue
        text = _read(path)
        if pattern.search(text):
            offenders.append(path)
    assert not offenders, (
        "Obsidian wikilink image embeds leaked into a non-Obsidian module: "
        f"{[str(p.relative_to(REPO_ROOT)) for p in offenders]}. "
        f"Only {sorted(OBSIDIAN_TARGETED_MODULES)} may emit ``![[...]]``."
    )


def test_obsidian_reporter_image_uses_width_hint() -> None:
    """Obsidian wikilinks for figures carry a ``|<width>`` hint so Obsidian
    renders them at a sensible inline width (not the full original
    resolution, which can blow out a digest)."""
    obsidian_src = _read(REPO_ROOT / "src/paperwiki/plugins/reporters/obsidian.py")
    # The teaser embed must include ``|<digits>`` after the image name.
    assert re.search(r"!\[\[[^\]]+\|\d+\]\]", obsidian_src), (
        "obsidian reporter teaser must use width-hinted wikilink: "
        "``![[<id>/images/<name>|<width>]]``"
    )


def test_extract_paper_images_uses_width_hint() -> None:
    """Same width-hint contract for the ``extract-images`` runner."""
    runner_src = _read(REPO_ROOT / "src/paperwiki/runners/extract_paper_images.py")
    assert re.search(r"!\[\[[^\]]+\|\d+\]\]", runner_src), (
        "extract_paper_images must use width-hinted wikilink: ``![[<id>/images/<name>|<width>]]``"
    )
