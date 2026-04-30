"""Unit tests for paperwiki.core.templates.

Templates render typed entity models (Concept / Topic / Person) into
Markdown strings suitable for writing to ``Wiki/{concepts,topics,people}/``
inside the user's vault. Templates live in ``paperwiki.locales.en.templates``
as ``.md`` files using stdlib ``string.Template`` ``$placeholder`` syntax
(chosen so the literal Markdown braces ``{}`` don't conflict with the
template engine).

Phase 2 (task 9.161) will tune the frontmatter shape to Obsidian
Properties API. v0.4.x v0.4.0 ships the minimal contract.
"""

from __future__ import annotations

import pytest

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


class TestRenderConcept:
    def test_minimal_concept_renders_h1_and_definition(self) -> None:
        concept = Concept(
            name="Transformer",
            definition="Attention-based neural architecture.",
        )
        rendered = render_concept(concept)
        assert "# Transformer" in rendered
        assert "Attention-based neural architecture." in rendered

    def test_concept_frontmatter_carries_type_and_name(self) -> None:
        concept = Concept(name="Attention", definition="Weighted aggregation.")
        rendered = render_concept(concept)
        # YAML frontmatter starts and ends with ``---``.
        assert rendered.startswith("---\n")
        assert "type: concept" in rendered
        assert "name: Attention" in rendered

    def test_concept_with_papers_renders_wikilinks(self) -> None:
        concept = Concept(
            name="Transformer",
            definition="Attention-based architecture.",
            papers=["arxiv:1706.03762", "arxiv:1810.04805"],
        )
        rendered = render_concept(concept)
        assert "[[arxiv:1706.03762]]" in rendered
        assert "[[arxiv:1810.04805]]" in rendered

    def test_concept_no_papers_omits_papers_section(self) -> None:
        concept = Concept(name="Attention", definition="x")
        rendered = render_concept(concept)
        # Empty list → no Papers heading at all (avoids dangling section).
        assert "## Papers" not in rendered

    def test_concept_aliases_listed(self) -> None:
        concept = Concept(
            name="VLP",
            aliases=["vision-language pretraining", "VLP"],
            definition="x",
        )
        rendered = render_concept(concept)
        assert "vision-language pretraining" in rendered


class TestRenderTopic:
    def test_minimal_topic_renders_h1_and_description(self) -> None:
        topic = Topic(
            name="Vision-Language Models",
            description="Multimodal foundation models.",
        )
        rendered = render_topic(topic)
        assert "# Vision-Language Models" in rendered
        assert "Multimodal foundation models." in rendered

    def test_topic_frontmatter_carries_type(self) -> None:
        topic = Topic(name="VLMs", description="x")
        rendered = render_topic(topic)
        assert rendered.startswith("---\n")
        assert "type: topic" in rendered

    def test_topic_with_concepts_renders_wikilinks(self) -> None:
        topic = Topic(
            name="VLMs",
            description="x",
            concepts=["transformer", "vision-language-pretraining"],
        )
        rendered = render_topic(topic)
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
        rendered = render_topic(topic)
        assert "[[arxiv:2506.13063]]" in rendered
        assert "PRISM2" in rendered


class TestRenderPerson:
    def test_minimal_person_renders_h1(self) -> None:
        person = Person(name="Yann LeCun")
        rendered = render_person(person)
        assert "# Yann LeCun" in rendered
        assert "type: person" in rendered

    def test_person_with_affiliation_in_frontmatter(self) -> None:
        person = Person(name="Yann LeCun", affiliation="Meta AI / NYU")
        rendered = render_person(person)
        assert "affiliation: Meta AI / NYU" in rendered

    def test_person_no_affiliation_omits_field(self) -> None:
        person = Person(name="Yann LeCun")
        rendered = render_person(person)
        # Frontmatter must NOT contain a stray ``affiliation:`` key
        # (downstream tools would parse the literal "None" as an
        # affiliation string).
        assert "affiliation:" not in rendered

    def test_person_collaborators_render_wikilinks(self) -> None:
        person = Person(
            name="Yann LeCun",
            collaborators=["geoffrey-hinton", "yoshua-bengio"],
        )
        rendered = render_person(person)
        assert "[[geoffrey-hinton]]" in rendered
        assert "[[yoshua-bengio]]" in rendered

    def test_person_papers_render_wikilinks(self) -> None:
        person = Person(
            name="Yoshua Bengio",
            papers=["arxiv:1409.0473"],
        )
        rendered = render_person(person)
        assert "[[arxiv:1409.0473]]" in rendered


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
        a = render_concept(concept)
        b = render_concept(concept)
        assert a == b

    def test_topic_render_deterministic(self) -> None:
        topic = Topic(name="x", description="y")
        assert render_topic(topic) == render_topic(topic)

    def test_person_render_deterministic(self) -> None:
        person = Person(name="x")
        assert render_person(person) == render_person(person)


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
