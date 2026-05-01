"""Smoke test for ``references/dataview-recipes.md`` (task 9.163).

The doc ships at least 5 copy-paste Dataview snippets that target the
canonical paper-wiki frontmatter fields (``tags`` / ``aliases`` /
``status`` / ``created`` / ``updated`` etc.). We can't actually run
Dataview in pytest (it's an Obsidian-side JS interpreter), so we verify
the next-best invariant: every frontmatter field name a recipe relies
on is one that paper-wiki actually emits — preventing the doc from
drifting silently after a schema change.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATAVIEW_RECIPES_PATH = REPO_ROOT / "references" / "dataview-recipes.md"

# Fields that paper-wiki guarantees as part of the Phase-2 frontmatter
# contract (tasks 9.161 + 9.156). Keep this list in sync with
# ``paperwiki.core.properties`` and ``MarkdownWikiBackend.upsert_paper``;
# any Dataview recipe in the doc that uses a field not on this list is a
# documentation bug.
EMITTED_FIELDS = frozenset(
    {
        # Properties block (9.161 / D-D)
        "tags",
        "aliases",
        "status",
        "cssclasses",
        "created",
        "updated",
        # Per-paper additions (markdown_wiki.py)
        "canonical_id",
        "title",
        "confidence",
        "domain",
        "published_at",
        "landing_url",
        "pdf_url",
        "citation_count",
        "score_breakdown",
        "related_concepts",
        "last_synthesized",
        # Typed-entity fields (9.156)
        "type",
        "name",
        "definition",
        "description",
        "papers",
        "concepts",
        "collaborators",
        "affiliation",
        # Dataview implicit
        "file",
    }
)


def _extract_dataview_blocks(text: str) -> list[str]:
    """Pull every ```dataview / ```dataviewjs fenced block out of the doc."""
    pattern = re.compile(r"```dataview(?:js)?\n(.*?)```", re.DOTALL)
    return [m.group(1) for m in pattern.finditer(text)]


def test_doc_exists() -> None:
    assert DATAVIEW_RECIPES_PATH.is_file(), (
        f"references/dataview-recipes.md must ship with v0.4.x (task 9.163); "
        f"expected at {DATAVIEW_RECIPES_PATH}"
    )


def test_doc_has_at_least_five_recipes() -> None:
    text = DATAVIEW_RECIPES_PATH.read_text(encoding="utf-8")
    blocks = _extract_dataview_blocks(text)
    assert len(blocks) >= 5, (
        f"task 9.163 acceptance: at least 5 working Dataview recipes; found {len(blocks)}"
    )


def test_doc_references_only_emitted_fields() -> None:
    """Every ``frontmatter.<name>`` (or ``WHERE <name>`` / ``FROM <name>``)
    reference in the doc must point at a field paper-wiki actually emits."""
    text = DATAVIEW_RECIPES_PATH.read_text(encoding="utf-8")
    blocks = _extract_dataview_blocks(text)

    # Identifiers that look like frontmatter field references in
    # Dataview's DQL: occurs after ``WHERE`` / ``SORT`` / ``GROUP BY`` /
    # column lists, or as ``frontmatter.<field>`` in dataviewjs.
    pattern = re.compile(r"\bfrontmatter\.([a-zA-Z_]+)\b|\b([a-z_]+)\s*(?:as|,|\)|$)")
    referenced: set[str] = set()
    for block in blocks:
        for match in pattern.finditer(block):
            for group in match.groups():
                if group is not None:
                    referenced.add(group)

    # The pattern is intentionally liberal — it catches a lot of false
    # positives (DQL keywords, table column aliases, etc.). We only
    # complain about names that look like frontmatter fields and aren't
    # in the emitted set.
    suspect = {
        name
        for name in referenced
        # Filter out DQL keywords, single-letter aliases, etc.
        if len(name) > 2
        and name not in EMITTED_FIELDS
        and name
        not in {
            # DQL keywords / common words / dataviewjs identifiers
            "table",
            "list",
            "from",
            "where",
            "sort",
            "group",
            "asc",
            "desc",
            "limit",
            "flatten",
            "and",
            "not",
            "null",
            "true",
            "false",
            "rows",
            "length",
            "month",
            "year",
            "date",
            "today",
            "now",
            "pages",
            "dv",
            "page",
            "for",
            "let",
            "const",
            "var",
            "function",
            "return",
            "this",
            "data",
            "row",
            "key",
            "value",
            "string",
            "number",
            "filter",
            "map",
            "format",
            "header",
            "split",
            "match",
            # DQL duration / link / outlink helpers
            "days",
            "link",
            "outlinks",
            "inlinks",
            "dur",
            "dateformat",
            "contains",
        }
    }
    assert not suspect, (
        f"references/dataview-recipes.md uses fields paper-wiki does not "
        f"emit: {sorted(suspect)}. Either update the doc or extend the "
        f"emitted-field allowlist if these are valid additions."
    )
