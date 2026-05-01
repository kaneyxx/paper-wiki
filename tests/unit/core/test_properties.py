"""Unit tests for ``paperwiki.core.properties`` (task 9.161).

Per the v0.4.x consensus plan §9.161 (decision **D-D**), all generated
frontmatter must be first-class Obsidian Properties API:

* ``tags`` — list of strings, lowercased + nested-tag-friendly
  (``paper/llm`` not ``Paper/LLM``).
* ``aliases`` — list of strings.
* ``status`` — string (one of ``draft``/``reviewed``/``stale`` for the
  wiki entries; reporters use ``draft`` by default).
* ``cssclasses`` — list of strings (Obsidian uses this to scope CSS
  rules to specific notes).
* ``created`` / ``updated`` — ISO-8601 strings *with timezone*.

This module owns the canonical helpers so all five emit sites (Concept
/ Topic / Person templates + markdown reporter + obsidian reporter +
markdown_wiki paper + markdown_wiki concept) stay in sync.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest


class TestNormalizeTags:
    def test_lowercases_and_strips_whitespace(self) -> None:
        from paperwiki.core.properties import normalize_tags

        assert normalize_tags(["LLM", " Foundation Model ", "ViT"]) == [
            "llm",
            "foundation-model",
            "vit",
        ]

    def test_converts_arxiv_categories_to_nested_tags(self) -> None:
        from paperwiki.core.properties import normalize_tags

        # arXiv categories like ``cs.LG`` map to nested ``cs/lg`` so
        # Obsidian's tag pane groups them under ``cs/``.
        assert normalize_tags(["cs.LG", "cs.CV", "stat.ML"]) == [
            "cs/lg",
            "cs/cv",
            "stat/ml",
        ]

    def test_preserves_existing_nested_tags(self) -> None:
        from paperwiki.core.properties import normalize_tags

        assert normalize_tags(["paper/llm", "Wiki/Concept"]) == [
            "paper/llm",
            "wiki/concept",
        ]

    def test_drops_empty_and_whitespace_only_entries(self) -> None:
        from paperwiki.core.properties import normalize_tags

        assert normalize_tags(["", "  ", "valid"]) == ["valid"]

    def test_deduplicates_after_normalization(self) -> None:
        from paperwiki.core.properties import normalize_tags

        # ``LLM`` and ``llm`` collapse to the same tag.
        assert normalize_tags(["LLM", "llm", "LLM"]) == ["llm"]

    def test_replaces_internal_whitespace_with_hyphens(self) -> None:
        from paperwiki.core.properties import normalize_tags

        assert normalize_tags(["foundation model"]) == ["foundation-model"]


class TestIso8601:
    def test_emits_utc_z_suffix(self) -> None:
        from paperwiki.core.properties import iso8601

        when = datetime(2026, 5, 1, 12, 30, 45, tzinfo=UTC)
        assert iso8601(when) == "2026-05-01T12:30:45+00:00"

    def test_preserves_offset_for_non_utc(self) -> None:
        from paperwiki.core.properties import iso8601

        tz = timezone(timedelta(hours=8))
        when = datetime(2026, 5, 1, 20, 30, 45, tzinfo=tz)
        assert iso8601(when) == "2026-05-01T20:30:45+08:00"

    def test_rejects_naive_datetimes(self) -> None:
        from paperwiki.core.properties import iso8601

        with pytest.raises(ValueError, match="timezone"):
            iso8601(datetime(2026, 5, 1, 12, 0, 0))  # noqa: DTZ001 — intentional


class TestPropertiesBlock:
    def test_default_block_has_all_six_fields(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=when)
        # Per acceptance criteria: tags, aliases, status, cssclasses,
        # created, updated.
        assert set(block.keys()) == {
            "tags",
            "aliases",
            "status",
            "cssclasses",
            "created",
            "updated",
        }

    def test_default_block_yaml_types(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=when)
        assert isinstance(block["tags"], list)
        assert isinstance(block["aliases"], list)
        assert isinstance(block["status"], str)
        assert isinstance(block["cssclasses"], list)
        assert isinstance(block["created"], str)
        assert isinstance(block["updated"], str)

    def test_passing_tags_normalizes_them(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(
            tags=["LLM", "cs.LG"],
            when=when,
        )
        assert block["tags"] == ["llm", "cs/lg"]

    def test_default_status_is_draft(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=when)
        assert block["status"] == "draft"

    def test_status_override(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=when, status="reviewed")
        assert block["status"] == "reviewed"

    def test_aliases_passthrough(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=when, aliases=["alt-name", "shortname"])
        assert block["aliases"] == ["alt-name", "shortname"]

    def test_cssclasses_passthrough(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=when, cssclasses=["paper-card"])
        assert block["cssclasses"] == ["paper-card"]

    def test_created_and_updated_use_iso_8601_with_timezone(self) -> None:
        from paperwiki.core.properties import build_properties_block

        when = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=when)
        # ISO-8601 includes the offset; Obsidian renders it as a Date type.
        assert block["created"].endswith("+00:00")
        assert block["updated"].endswith("+00:00")

    def test_updated_can_differ_from_created(self) -> None:
        from paperwiki.core.properties import build_properties_block

        created = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        updated = datetime(2026, 5, 2, 15, 0, 0, tzinfo=UTC)
        block = build_properties_block(when=updated, created=created)
        assert block["created"].startswith("2026-05-01")
        assert block["updated"].startswith("2026-05-02")
