"""Markdown templates for v0.4.x typed wiki entities.

Renders :class:`Concept` / :class:`Topic` / :class:`Person` instances into
Markdown strings ready to write to ``Wiki/{concepts,topics,people}/``
inside the user's vault. Templates are deterministic — same input produces
byte-identical output, which is required so :mod:`paperwiki.runners.wiki_compile_graph`
(task 9.157) can stay idempotent on second-pass writes.

Phase 2 (task 9.161) will tune the YAML frontmatter shape for Obsidian
Properties API (D-D); v0.4.0 ships the minimal contract expected by
9.157 + 9.159.

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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paperwiki.core.models import Concept, Person, Topic


def _yaml_string_list(values: list[str]) -> str:
    """Render a list of strings as a YAML flow-style sequence.

    >>> _yaml_string_list([])
    '[]'
    >>> _yaml_string_list(["a", "b"])
    '[a, b]'
    """
    if not values:
        return "[]"
    # Quote individually only when the value contains a YAML-special
    # character; bare scalars round-trip cleanly otherwise.
    rendered: list[str] = []
    for v in values:
        if any(ch in v for ch in ":#,[]{}&*!|>'\"%@`\n"):
            quoted = v.replace("\\", "\\\\").replace('"', '\\"')
            rendered.append(f'"{quoted}"')
        else:
            rendered.append(v)
    return "[" + ", ".join(rendered) + "]"


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


def render_concept(concept: Concept) -> str:
    """Render a :class:`Concept` to Markdown.

    Output structure:

    ```
    ---
    type: concept
    name: <name>
    aliases: <yaml flow seq>
    tags: <yaml flow seq>
    ---

    # <name>

    <definition>

    [optional ## Aliases]
    [optional ## Papers]
    ```
    """
    parts: list[str] = []
    parts.append("---")
    parts.append("type: concept")
    parts.append(f"name: {concept.name}")
    parts.append(f"aliases: {_yaml_string_list(concept.aliases)}")
    parts.append(f"tags: {_yaml_string_list(concept.tags)}")
    parts.append("---")
    parts.append("")
    parts.append(f"# {concept.name}")
    parts.append("")
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


def render_topic(topic: Topic) -> str:
    """Render a :class:`Topic` to Markdown."""
    parts: list[str] = []
    parts.append("---")
    parts.append("type: topic")
    parts.append(f"name: {topic.name}")
    parts.append("---")
    parts.append("")
    parts.append(f"# {topic.name}")
    parts.append("")
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


def render_person(person: Person) -> str:
    """Render a :class:`Person` to Markdown.

    The ``affiliation`` field is intentionally omitted from frontmatter
    when ``None`` — emitting ``affiliation: null`` would let downstream
    tools parse the literal ``"None"`` string as an affiliation.
    """
    parts: list[str] = []
    parts.append("---")
    parts.append("type: person")
    parts.append(f"name: {person.name}")
    parts.append(f"aliases: {_yaml_string_list(person.aliases)}")
    if person.affiliation is not None:
        parts.append(f"affiliation: {person.affiliation}")
    parts.append("---")
    parts.append("")
    parts.append(f"# {person.name}")
    parts.append("")
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
