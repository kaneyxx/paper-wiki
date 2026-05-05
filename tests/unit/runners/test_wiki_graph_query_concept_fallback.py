"""Co-occurrence fallback for ``--concepts-in-topic`` (Task 9.217).

The v0.4.x graph cache writes ``papers/<id> → concepts/<slug>`` edges
when a paper auto-ingest emits a typed-list ``related_concepts:``
frontmatter or a body wikilink ``[[concept-slug]]``. Real recipes
declare "topics" (e.g. ``vision-multimodal``) but the digest auto-ingest
persists them as ``Wiki/concepts/<slug>.md`` — they live under
``concepts/``, not ``topics/``. The original v0.4.0 query branch in
``wiki_graph_query.query()`` filters
``edge.src == topic_id and edge.dst.startswith("concepts/")`` — when
``topic_id`` resolves to ``concepts/<slug>``, the filter returns ``[]``
because the edges go INTO the concept, never OUT of it.

v0.4.8 Task 9.217 adds a co-occurrence fallback: when the resolved
target is in ``concepts/``, the runner finds papers linking to it,
collects all OTHER concepts those papers link to, dedupes, and
synthesizes ``concepts/<target> → concepts/<other>`` records of type
``builds_on``. The canonical ``topics/`` path is preserved unchanged
for forward-compat with hand-authored ``Wiki/topics/<slug>.md`` files.

Each test materialises a small typed-subdir vault with a precisely
controlled ``edges.jsonl`` so the assertions are deterministic.
"""

from __future__ import annotations

from pathlib import Path

from paperwiki.runners.wiki_graph_query import query

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_entity(
    vault: Path,
    *,
    subdir: str,
    slug: str,
    extra_frontmatter: str = "",
) -> None:
    """Write a minimal typed-subdir entity so ``walk_entities`` indexes it."""
    target = vault / "Wiki" / subdir / f"{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    body = f"---\nslug: {slug}\n{extra_frontmatter}---\n\n# {slug}\n"
    target.write_text(body, encoding="utf-8")


def _write_edges(vault: Path, edges: list[dict[str, str | float]]) -> None:
    """Write a controlled ``edges.jsonl`` (skips graph compile entirely)."""
    import json

    graph_dir = vault / "Wiki" / ".graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in edges)
    (graph_dir / "edges.jsonl").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1 — topic-shaped slug uses the canonical path (back-compat)
# ---------------------------------------------------------------------------


def test_topic_shaped_slug_uses_canonical_path(tmp_path: Path) -> None:
    """When the slug resolves to ``topics/<slug>``, return the literal
    ``topics/<slug> → concepts/<X>`` edges from edges.jsonl."""
    _make_entity(tmp_path, subdir="topics", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="vlm")
    _make_entity(tmp_path, subdir="concepts", slug="clip")
    _write_edges(
        tmp_path,
        [
            {
                "src": "topics/vision-multimodal",
                "dst": "concepts/vlm",
                "type": "builds_on",
                "weight": 1.0,
            },
            {
                "src": "topics/vision-multimodal",
                "dst": "concepts/clip",
                "type": "builds_on",
                "weight": 1.0,
            },
        ],
    )

    records = query(tmp_path, concepts_in_topic="vision-multimodal")

    assert len(records) == 2
    dsts = {r["dst"] for r in records}
    assert dsts == {"concepts/vlm", "concepts/clip"}
    # Canonical path: src is the topic itself.
    assert all(r["src"] == "topics/vision-multimodal" for r in records)


# ---------------------------------------------------------------------------
# Test 2 — concept-shaped slug uses co-occurrence fallback (the bug case)
# ---------------------------------------------------------------------------


def test_concept_shaped_slug_uses_co_occurrence_fallback(tmp_path: Path) -> None:
    """Real recipes persist topics as ``concepts/`` — the fallback finds
    papers linking to the target and reports their other concepts."""
    _make_entity(tmp_path, subdir="concepts", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="vlm")
    _make_entity(tmp_path, subdir="concepts", slug="clip")
    _make_entity(tmp_path, subdir="concepts", slug="transformer")
    _make_entity(tmp_path, subdir="papers", slug="p1")
    _make_entity(tmp_path, subdir="papers", slug="p2")
    _write_edges(
        tmp_path,
        [
            # p1 links to vision-multimodal AND vlm AND clip
            {
                "src": "papers/p1",
                "dst": "concepts/vision-multimodal",
                "type": "builds_on",
                "weight": 1.0,
            },
            {"src": "papers/p1", "dst": "concepts/vlm", "type": "builds_on", "weight": 1.0},
            {"src": "papers/p1", "dst": "concepts/clip", "type": "builds_on", "weight": 1.0},
            # p2 links to vision-multimodal AND clip AND transformer
            {
                "src": "papers/p2",
                "dst": "concepts/vision-multimodal",
                "type": "builds_on",
                "weight": 1.0,
            },
            {"src": "papers/p2", "dst": "concepts/clip", "type": "builds_on", "weight": 1.0},
            {
                "src": "papers/p2",
                "dst": "concepts/transformer",
                "type": "builds_on",
                "weight": 1.0,
            },
        ],
    )

    records = query(tmp_path, concepts_in_topic="vision-multimodal")

    # Fallback synthesises edges with src = target concept, dst = each
    # co-occurring concept; deduped on (src, dst).
    dsts = {r["dst"] for r in records}
    assert dsts == {"concepts/vlm", "concepts/clip", "concepts/transformer"}
    # All edges originate from the target concept itself.
    assert all(r["src"] == "concepts/vision-multimodal" for r in records)
    # Dedupe: 3 distinct dsts, 3 records (clip appeared in both papers).
    assert len(records) == 3


# ---------------------------------------------------------------------------
# Test 3 — co-occurrence dedupes when two papers link to the same other concept
# ---------------------------------------------------------------------------


def test_co_occurrence_dedupes_when_two_papers_link_to_same_other_concept(
    tmp_path: Path,
) -> None:
    """One paper-pair both linking to clip → exactly one ``→ concepts/clip`` record."""
    _make_entity(tmp_path, subdir="concepts", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="clip")
    _make_entity(tmp_path, subdir="papers", slug="p1")
    _make_entity(tmp_path, subdir="papers", slug="p2")
    _write_edges(
        tmp_path,
        [
            {
                "src": "papers/p1",
                "dst": "concepts/vision-multimodal",
                "type": "builds_on",
                "weight": 1.0,
            },
            {"src": "papers/p1", "dst": "concepts/clip", "type": "builds_on", "weight": 1.0},
            {
                "src": "papers/p2",
                "dst": "concepts/vision-multimodal",
                "type": "builds_on",
                "weight": 1.0,
            },
            {"src": "papers/p2", "dst": "concepts/clip", "type": "builds_on", "weight": 1.0},
        ],
    )

    records = query(tmp_path, concepts_in_topic="vision-multimodal")

    # Two papers both link to clip — output has clip exactly once.
    clip_records = [r for r in records if r["dst"] == "concepts/clip"]
    assert len(clip_records) == 1


# ---------------------------------------------------------------------------
# Test 4 — target concept is not in its own results (self-loop suppression)
# ---------------------------------------------------------------------------


def test_target_concept_not_in_its_own_results(tmp_path: Path) -> None:
    """The target concept must never appear as ``dst`` in the result."""
    _make_entity(tmp_path, subdir="concepts", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="vlm")
    _make_entity(tmp_path, subdir="papers", slug="p1")
    _write_edges(
        tmp_path,
        [
            {
                "src": "papers/p1",
                "dst": "concepts/vision-multimodal",
                "type": "builds_on",
                "weight": 1.0,
            },
            {"src": "papers/p1", "dst": "concepts/vlm", "type": "builds_on", "weight": 1.0},
        ],
    )

    records = query(tmp_path, concepts_in_topic="vision-multimodal")

    dsts = {r["dst"] for r in records}
    assert "concepts/vision-multimodal" not in dsts
    assert dsts == {"concepts/vlm"}


# ---------------------------------------------------------------------------
# Test 5 — no papers linking to the target concept → empty result
# ---------------------------------------------------------------------------


def test_no_papers_linking_to_target_returns_empty(tmp_path: Path) -> None:
    """A concept with no inbound paper links is the leaf case — empty list."""
    _make_entity(tmp_path, subdir="concepts", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="vlm")
    _make_entity(tmp_path, subdir="papers", slug="p1")
    _write_edges(
        tmp_path,
        [
            # p1 doesn't link to vision-multimodal at all
            {"src": "papers/p1", "dst": "concepts/vlm", "type": "builds_on", "weight": 1.0},
        ],
    )

    records = query(tmp_path, concepts_in_topic="vision-multimodal")

    assert records == []


# ---------------------------------------------------------------------------
# Test 6 — topics/<slug> takes precedence when both topics/X.md and
# concepts/X.md exist (forward-compat for hand-authored topics)
# ---------------------------------------------------------------------------


def test_topics_subdir_takes_precedence_over_concepts_same_slug(tmp_path: Path) -> None:
    """When both ``topics/X.md`` and ``concepts/X.md`` exist, the resolver
    picks the topics one, and the canonical path runs (not the fallback)."""
    _make_entity(tmp_path, subdir="topics", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="vlm")
    _make_entity(tmp_path, subdir="concepts", slug="clip")
    _make_entity(tmp_path, subdir="papers", slug="p1")
    _write_edges(
        tmp_path,
        [
            # Canonical: topic → vlm (the only edge starting from topics/)
            {
                "src": "topics/vision-multimodal",
                "dst": "concepts/vlm",
                "type": "builds_on",
                "weight": 1.0,
            },
            # Fallback bait — lots of papers linking to concepts/vision-multimodal,
            # which the fallback would otherwise return.
            {
                "src": "papers/p1",
                "dst": "concepts/vision-multimodal",
                "type": "builds_on",
                "weight": 1.0,
            },
            {
                "src": "papers/p1",
                "dst": "concepts/clip",
                "type": "builds_on",
                "weight": 1.0,
            },
        ],
    )

    records = query(tmp_path, concepts_in_topic="vision-multimodal")

    # Canonical path wins: only the literal topics/ → concepts/vlm edge is returned.
    assert len(records) == 1
    assert records[0]["src"] == "topics/vision-multimodal"
    assert records[0]["dst"] == "concepts/vlm"


# ---------------------------------------------------------------------------
# Test 7 — output edge shape stable (JSON SKILL-pipe contract)
# ---------------------------------------------------------------------------


def test_fallback_output_shape_matches_canonical_path(tmp_path: Path) -> None:
    """JSON keys produced by the fallback path match the canonical path
    so downstream SKILLs treat both identically."""
    _make_entity(tmp_path, subdir="concepts", slug="vision-multimodal")
    _make_entity(tmp_path, subdir="concepts", slug="vlm")
    _make_entity(tmp_path, subdir="papers", slug="p1")
    _write_edges(
        tmp_path,
        [
            {
                "src": "papers/p1",
                "dst": "concepts/vision-multimodal",
                "type": "builds_on",
                "weight": 1.0,
            },
            {"src": "papers/p1", "dst": "concepts/vlm", "type": "builds_on", "weight": 1.0},
        ],
    )

    records = query(tmp_path, concepts_in_topic="vision-multimodal")

    assert len(records) == 1
    record = records[0]
    assert set(record.keys()) == {"src", "dst", "type", "weight"}
    assert isinstance(record["weight"], float)
