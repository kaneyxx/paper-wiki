"""Markdown templates for v0.4.x typed wiki entities.

Renders :class:`Concept` / :class:`Topic` / :class:`Person` instances into
Markdown strings ready to write to ``Wiki/{concepts,topics,people}/``
inside the user's vault. Templates are deterministic — same input
(including the ``when`` timestamp) produces byte-identical output, which
is required so :mod:`paperwiki.runners.wiki_compile_graph` (task 9.157)
can stay idempotent on second-pass writes.

Phase 2 (task 9.161, decision **D-D**) tunes the YAML frontmatter shape
to first-class Obsidian Properties: every render carries ``tags`` /
``aliases`` / ``status`` / ``cssclasses`` / ``created`` / ``updated`` so
the user's Properties pane and Dataview queries work without manual
glue. Type-specific fields (``type``, ``name``, ``definition``, …) live
above the Properties block but below the opening ``---``.

Why the templates live in Python rather than ``locales/en/templates/``
.md files: v0.4.0 surface is English-only (SPEC §7 boundary). Adding a
file-based template engine for one locale would be premature complexity.
``locales/`` becomes meaningful once the Chinese surface lands; at that
point we can extract the Markdown bodies to ``locales/<lang>/templates/``
and load them via :mod:`importlib.resources`. Until then, Python
functions keep the contract type-checked end-to-end (mypy --strict
catches template/model drift; a file-based engine would not).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from paperwiki.core.properties import build_properties_block

if TYPE_CHECKING:
    from datetime import datetime

    from paperwiki.core.models import Concept, Person, Topic


def _render_frontmatter(payload: dict[str, Any]) -> str:
    """Render a YAML frontmatter block with stable, Obsidian-friendly output.

    Uses block-style (``- item``) sequences for list values so the
    Properties pane in Obsidian 1.4+ renders them as first-class lists.
    Key order is preserved so callers control field ordering for
    determinism.
    """
    body = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"---\n{body}---\n"


def _wikilink_section(heading: str, targets: list[str]) -> str:
    """Render a ``## <heading>`` section with one ``- [[target]]`` per row.

    Returns ``""`` when ``targets`` is empty so callers can concatenate
    without producing dangling headings.
    """
    if not targets:
        return ""
    lines = [f"## {heading}", ""]
    lines.extend(f"- [[{target}]]" for target in targets)
    lines.append("")  # trailing blank line for clean Markdown
    return "\n".join(lines) + "\n"


def render_concept(concept: Concept, *, when: datetime) -> str:
    """Render a :class:`Concept` to Markdown with Obsidian Properties frontmatter.

    Frontmatter shape (per task 9.161, **D-D**)::

        ---
        type: concept
        name: <name>
        definition: <definition>
        tags: [...]
        aliases: [...]
        status: draft
        cssclasses: []
        created: <iso8601>
        updated: <iso8601>
        papers: [...]   # optional, only when non-empty
        ---

    The body keeps ``# <name>`` + definition text + optional aliases /
    papers wikilink sections so Obsidian's outline pane stays useful.
    """
    fm: dict[str, Any] = {
        "type": "concept",
        "name": concept.name,
        "definition": concept.definition,
    }
    fm.update(
        build_properties_block(
            when=when,
            tags=list(concept.tags),
            aliases=list(concept.aliases),
        )
    )
    if concept.papers:
        fm["papers"] = list(concept.papers)

    parts: list[str] = []
    parts.append(_render_frontmatter(fm))
    parts.append(f"# {concept.name}\n")
    parts.append(concept.definition)
    parts.append("")
    if concept.aliases:
        parts.append("## Aliases")
        parts.append("")
        parts.extend(f"- {alias}" for alias in concept.aliases)
        parts.append("")
    if concept.papers:
        parts.append(_wikilink_section("Papers", concept.papers).rstrip("\n"))
    return "\n".join(parts).rstrip() + "\n"


def render_topic(topic: Topic, *, when: datetime) -> str:
    """Render a :class:`Topic` to Markdown with Obsidian Properties frontmatter."""
    fm: dict[str, Any] = {
        "type": "topic",
        "name": topic.name,
        "description": topic.description,
    }
    fm.update(
        build_properties_block(
            when=when,
            tags=[],
            aliases=[],
        )
    )
    if topic.papers:
        fm["papers"] = list(topic.papers)
    if topic.concepts:
        fm["concepts"] = list(topic.concepts)

    parts: list[str] = []
    parts.append(_render_frontmatter(fm))
    parts.append(f"# {topic.name}\n")
    parts.append(topic.description)
    parts.append("")
    if topic.papers:
        parts.append(_wikilink_section("Papers", topic.papers).rstrip("\n"))
    if topic.concepts:
        parts.append(_wikilink_section("Related concepts", topic.concepts).rstrip("\n"))
    if topic.sota:
        parts.append("## State of the art")
        parts.append("")
        for rec in topic.sota:
            score = f"{rec.score.composite:.2f}"
            parts.append(f"- [[{rec.paper.canonical_id}]] ({score}) — {rec.paper.title}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_person(person: Person, *, when: datetime) -> str:
    """Render a :class:`Person` to Markdown with Obsidian Properties frontmatter.

    The ``affiliation`` field is intentionally omitted from frontmatter
    when ``None`` — emitting ``affiliation: null`` would let downstream
    tools parse the literal ``"None"`` string as an affiliation.
    """
    fm: dict[str, Any] = {
        "type": "person",
        "name": person.name,
    }
    if person.affiliation is not None:
        fm["affiliation"] = person.affiliation
    fm.update(
        build_properties_block(
            when=when,
            tags=[],
            aliases=list(person.aliases),
        )
    )
    if person.papers:
        fm["papers"] = list(person.papers)
    if person.collaborators:
        fm["collaborators"] = list(person.collaborators)

    parts: list[str] = []
    parts.append(_render_frontmatter(fm))
    parts.append(f"# {person.name}\n")
    if person.affiliation is not None:
        parts.append(f"**Affiliation**: {person.affiliation}")
        parts.append("")
    if person.aliases:
        parts.append("## Aliases")
        parts.append("")
        parts.extend(f"- {alias}" for alias in person.aliases)
        parts.append("")
    if person.papers:
        parts.append(_wikilink_section("Papers", person.papers).rstrip("\n"))
    if person.collaborators:
        parts.append(_wikilink_section("Collaborators", person.collaborators).rstrip("\n"))
    return "\n".join(parts).rstrip() + "\n"


__all__ = [
    "render_concept",
    "render_person",
    "render_topic",
]
