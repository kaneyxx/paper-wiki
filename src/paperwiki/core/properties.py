"""Obsidian Properties API frontmatter helpers (task 9.161).

Per **D-D**, every Markdown file paper-wiki writes carries first-class
Obsidian Properties so the user's vault renders cleanly in the
Properties pane and Dataview queries work without manual glue.

The canonical Properties shape is six fields:

* ``tags`` — list of strings, lowercased and nested-tag-friendly
  (``cs.LG`` → ``cs/lg``; ``Foundation Model`` → ``foundation-model``).
* ``aliases`` — list of strings (Obsidian uses these to wire up
  ``[[wikilink]]`` aliases automatically).
* ``status`` — string (``draft`` / ``reviewed`` / ``stale``).
* ``cssclasses`` — list of strings (Obsidian scopes CSS rules to notes
  carrying any of these classes).
* ``created`` — ISO-8601 string with timezone offset.
* ``updated`` — ISO-8601 string with timezone offset.

Per the v0.4.x consensus plan iter-2 R12, **every emit site routes
through this module**: Concept / Topic / Person templates,
:class:`MarkdownReporter`, :class:`ObsidianReporter`, and
:class:`MarkdownWikiBackend`. The Properties migration helper (task
9.161 phase 2) reads existing typed-subdir notes and rewrites their
frontmatter through these same helpers so a vault built on v0.4.0-Phase-1
upgrades cleanly to v0.4.0-Phase-2.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Status alphabet (matches MarkdownWikiBackend's existing contract so
# wiki-lint's STATUS_MISMATCH rule keeps working unchanged).
DEFAULT_STATUS = "draft"
ALLOWED_STATUS = frozenset({"draft", "reviewed", "stale"})

# arXiv categories carry a single dot (``cs.LG``); Obsidian's tag pane
# treats ``/`` as the nesting separator. Convert to ``cs/lg`` so the
# user's tag pane groups by area without manual cleanup.
_DOTTED_CATEGORY_RE = re.compile(r"^([a-z][a-z0-9]*)\.([a-z0-9]+)$")
# Internal runs of whitespace collapse to a single hyphen so multi-word
# tags survive Obsidian's tag-name rules (``foundation model`` → ``foundation-model``).
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _normalize_one_tag(raw: str) -> str | None:
    """Normalize one tag value; return ``None`` if it's empty after strip."""
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    # ``cs.LG`` → ``cs/lg`` (only when the shape matches a category).
    match = _DOTTED_CATEGORY_RE.match(cleaned)
    if match is not None:
        cleaned = f"{match.group(1)}/{match.group(2)}"
    cleaned = _WHITESPACE_RUN_RE.sub("-", cleaned)
    return cleaned


def normalize_tags(tags: list[str]) -> list[str]:
    """Return ``tags`` lowercased, nested-tag-friendly, and de-duplicated.

    Order is preserved by first occurrence so the rendered frontmatter
    stays deterministic across runs (task 9.157 wiki_compile_graph
    relies on byte-identical output for idempotency).
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        normalized = _normalize_one_tag(raw)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def iso8601(when: datetime) -> str:
    """Return an ISO-8601 string with timezone offset.

    Naive datetimes are rejected so we never emit "looks-like-UTC but
    actually local" timestamps; the user's vault would silently drift
    across machines once it crosses a timezone boundary.
    """
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        msg = "iso8601() requires a timezone-aware datetime"
        raise ValueError(msg)
    return when.isoformat()


def build_properties_block(
    *,
    when: datetime,
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    status: str = DEFAULT_STATUS,
    cssclasses: list[str] | None = None,
    created: datetime | None = None,
) -> dict[str, Any]:
    """Build the canonical Obsidian Properties frontmatter dict.

    ``when`` is the timestamp written to ``updated`` (and to ``created``
    if no separate ``created`` is supplied — fresh notes have
    ``created == updated``).

    The returned dict is shape-only: callers feed it to ``yaml.safe_dump``
    or merge it into a larger frontmatter dict.
    """
    if status not in ALLOWED_STATUS:
        msg = f"status must be one of {sorted(ALLOWED_STATUS)}; got {status!r}"
        raise ValueError(msg)

    created_dt = created if created is not None else when
    return {
        "tags": normalize_tags(tags or []),
        "aliases": list(aliases or []),
        "status": status,
        "cssclasses": list(cssclasses or []),
        "created": iso8601(created_dt),
        "updated": iso8601(when),
    }


__all__ = [
    "ALLOWED_STATUS",
    "DEFAULT_STATUS",
    "build_properties_block",
    "iso8601",
    "normalize_tags",
]
