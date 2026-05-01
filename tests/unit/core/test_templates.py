"""Unit tests for paperwiki.core.templates.

Templates render typed entity models (Concept / Topic / Person) into
Markdown strings suitable for writing to ``Wiki/{concepts,topics,people}/``
inside the user's vault.

Task 9.161 (Phase 2) tunes the frontmatter shape to Obsidian Properties
API: every rendered note carries ``tags`` / ``aliases`` / ``status`` /
``cssclasses`` / ``created`` / ``updated`` so the user's vault renders
cleanly in the Properties pane and Dataview queries can target the
fields directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml

from paperwiki.core.models import (
    Author,
    Concept,
    Paper,
    Person,
    Recommendation,
    ScoreBreakdown,
    Topic,
)
from paperwiki.core.templates import (
    render_concept,
    render_person,
    render_topic,
)

_FIXED_WHEN = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def _parse_frontmatter(rendered: str) -> dict[str, object]:
    """Extract the YAML frontmatter block as a dict for type assertions."""
    assert rendered.startswith("---\n"), "render must start with a YAML frontmatter block"
    end = rendered.index("\n---\n", 4)
    block = rendered[4:end]
    parsed = yaml.safe_load(block)
    assert isinstance(parsed, dict)
    return parsed


class TestRenderConcept:
    def test_minimal_concept_renders_h1_and_definition(self) -> None:
        concept = Concept(
            name="Transformer",
            definition="Attention-based neural architecture.",
        )
        rendered = render_concept(concept, when=_FIXED_WHEN)
        assert "# Transformer" in rendered
        assert "Attention-based neural architecture." in rendered

    def test_concept_frontmatter_carries_type_and_name(self) -> None:
        concept = Concept(name="Attention", definition="Weighted aggregation.")
        rendered = render_concept(concept, when=_FIXED_WHEN)
        fm = _parse_frontmatter(rendered)
        assert fm["type"] == "concept"
        assert fm["name"] == "Attention"

    def test_concept_with_papers_renders_wikilinks(self) -> None:
        concept = Concept(
            name="Transformer",
            definition="Attention-based architecture.",
            papers=["arxiv:1706.03762", "arxiv:1810.04805"],
        )
        rendered = render_concept(concept, when=_FIXED_WHEN)
        assert "[[arxiv:1706.03762]]" in rendered
        assert "[[arxiv:1810.04805]]" in rendered

    def test_concept_no_papers_omits_papers_section(self) -> None:
        concept = Concept(name="Attention", definition="x")
        rendered = render_concept(concept, when=_FIXED_WHEN)
        # Empty list → no Papers heading at all (avoids dangling section).
        assert "## Papers" not in rendered

    def test_concept_aliases_listed(self) -> None:
        concept = Concept(
            name="VLP",
            aliases=["vision-language pretraining", "VLP"],
            definition="x",
        )
        rendered = render_concept(concept, when=_FIXED_WHEN)
        assert "vision-language pretraining" in rendered

    def test_concept_emits_obsidian_properties_block(self) -> None:
        """Per task 9.161: every render carries the six Properties fields."""
        concept = Concept(
            name="Transformer",
            aliases=["self-attention"],
            definition="x",
            tags=["LLM", "cs.LG"],
        )
        rendered = render_concept(concept, when=_FIXED_WHEN)
        fm = _parse_frontmatter(rendered)
        assert isinstance(fm["tags"], list)
        # arXiv-style ``cs.LG`` becomes ``cs/lg`` so the tag pane nests cleanly.
        assert fm["tags"] == ["llm", "cs/lg"]
        assert isinstance(fm["aliases"], list)
        assert fm["aliases"] == ["self-attention"]
        assert isinstance(fm["status"], str)
        assert fm["status"] == "draft"
        assert isinstance(fm["cssclasses"], list)
        assert fm["cssclasses"] == []
        # ISO-8601 with timezone offset.
        assert isinstance(fm["created"], str)
        assert fm["created"].startswith("2026-05-01T12:00:00")
        assert isinstance(fm["updated"], str)
        assert fm["updated"].startswith("2026-05-01T12:00:00")


class TestRenderTopic:
    def test_minimal_topic_renders_h1_and_description(self) -> None:
        topic = Topic(
            name="Vision-Language Models",
            description="Multimodal foundation models.",
        )
        rendered = render_topic(topic, when=_FIXED_WHEN)
        assert "# Vision-Language Models" in rendered
        assert "Multimodal foundation models." in rendered

    def test_topic_frontmatter_carries_type(self) -> None:
        topic = Topic(name="VLMs", description="x")
        rendered = render_topic(topic, when=_FIXED_WHEN)
        fm = _parse_frontmatter(rendered)
        assert fm["type"] == "topic"

    def test_topic_with_concepts_renders_wikilinks(self) -> None:
        topic = Topic(
            name="VLMs",
            description="x",
            concepts=["transformer", "vision-language-pretraining"],
        )
        rendered = render_topic(topic, when=_FIXED_WHEN)
        assert "[[transformer]]" in rendered
        assert "[[vision-language-pretraining]]" in rendered

    def test_topic_with_sota_renders_recommendation_lines(self) -> None:
        rec = Recommendation(
            paper=Paper(
                canonical_id="arxiv:2506.13063",
                title="PRISM2",
                authors=[Author(name="George Shaikovski")],
                abstract="x",
                published_at=__import__("datetime").datetime(
                    2026, 4, 20, tzinfo=__import__("datetime").UTC
                ),
            ),
            score=ScoreBreakdown(relevance=0.9, composite=0.85),
        )
        topic = Topic(name="VLMs", description="x", sota=[rec])
        rendered = render_topic(topic, when=_FIXED_WHEN)
        assert "[[arxiv:2506.13063]]" in rendered
        assert "PRISM2" in rendered

    def test_topic_emits_obsidian_properties_block(self) -> None:
        topic = Topic(name="VLMs", description="x")
        rendered = render_topic(topic, when=_FIXED_WHEN)
        fm = _parse_frontmatter(rendered)
        assert set(["tags", "aliases", "status", "cssclasses", "created", "updated"]).issubset(
            fm.keys()
        )
        assert isinstance(fm["tags"], list)
        assert isinstance(fm["aliases"], list)
        assert isinstance(fm["cssclasses"], list)


class TestRenderPerson:
    def test_minimal_person_renders_h1(self) -> None:
        person = Person(name="Yann LeCun")
        rendered = render_person(person, when=_FIXED_WHEN)
        assert "# Yann LeCun" in rendered
        fm = _parse_frontmatter(rendered)
        assert fm["type"] == "person"

    def test_person_with_affiliation_in_frontmatter(self) -> None:
        person = Person(name="Yann LeCun", affiliation="Meta AI / NYU")
        rendered = render_person(person, when=_FIXED_WHEN)
        fm = _parse_frontmatter(rendered)
        assert fm["affiliation"] == "Meta AI / NYU"

    def test_person_no_affiliation_omits_field(self) -> None:
        person = Person(name="Yann LeCun")
        rendered = render_person(person, when=_FIXED_WHEN)
        fm = _parse_frontmatter(rendered)
        # Frontmatter must NOT contain a stray ``affiliation:`` key
        # (downstream tools would parse the literal ``None`` as an
        # affiliation string).
        assert "affiliation" not in fm

    def test_person_collaborators_render_wikilinks(self) -> None:
        person = Person(
            name="Yann LeCun",
            collaborators=["geoffrey-hinton", "yoshua-bengio"],
        )
        rendered = render_person(person, when=_FIXED_WHEN)
        assert "[[geoffrey-hinton]]" in rendered
        assert "[[yoshua-bengio]]" in rendered

    def test_person_papers_render_wikilinks(self) -> None:
        person = Person(
            name="Yoshua Bengio",
            papers=["arxiv:1409.0473"],
        )
        rendered = render_person(person, when=_FIXED_WHEN)
        assert "[[arxiv:1409.0473]]" in rendered

    def test_person_emits_obsidian_properties_block(self) -> None:
        person = Person(name="Yann LeCun", aliases=["yann"])
        rendered = render_person(person, when=_FIXED_WHEN)
        fm = _parse_frontmatter(rendered)
        assert set(["tags", "aliases", "status", "cssclasses", "created", "updated"]).issubset(
            fm.keys()
        )
        assert fm["aliases"] == ["yann"]


class TestTemplateOutputIsDeterministic:
    """Templates must produce byte-identical output for byte-identical input.

    This is required so wiki_compile_graph (task 9.157) can be idempotent
    on second-pass writes (acceptance criterion: same input ⇒ same bytes).
    """

    def test_concept_render_deterministic(self) -> None:
        concept = Concept(
            name="Transformer",
            aliases=["attn", "self-attention"],
            definition="x",
            tags=["arch", "neural"],
            papers=["arxiv:a", "arxiv:b"],
        )
        a = render_concept(concept, when=_FIXED_WHEN)
        b = render_concept(concept, when=_FIXED_WHEN)
        assert a == b

    def test_topic_render_deterministic(self) -> None:
        topic = Topic(name="x", description="y")
        assert render_topic(topic, when=_FIXED_WHEN) == render_topic(topic, when=_FIXED_WHEN)

    def test_person_render_deterministic(self) -> None:
        person = Person(name="x")
        assert render_person(person, when=_FIXED_WHEN) == render_person(person, when=_FIXED_WHEN)


class TestNoLLMImports:
    """Consensus plan iter-2 R11 / D-E enforcement.

    The 9.156 model + template layer must NOT import any LLM HTTP client.
    Auto-extraction (D-K) happens in the SKILL pass via Claude Code, not
    in Python. CI grep guard catches new imports in the v0.4.x runners.
    """

    def test_models_module_has_no_llm_client_imports(self) -> None:
        from pathlib import Path

        models_text = (
            Path(__file__)
            .parent.parent.parent.parent.joinpath("src/paperwiki/core/models.py")
            .read_text()
        )
        for forbidden in ("import anthropic", "import openai", "from anthropic", "from openai"):
            assert forbidden not in models_text, f"forbidden import: {forbidden}"

    def test_templates_module_has_no_llm_client_imports(self) -> None:
        from pathlib import Path

        templates_text = (
            Path(__file__)
            .parent.parent.parent.parent.joinpath("src/paperwiki/core/templates.py")
            .read_text()
        )
        for forbidden in ("import anthropic", "import openai", "from anthropic", "from openai"):
            assert forbidden not in templates_text, f"forbidden import: {forbidden}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
