"""Unit tests for v0.4 schema mapping + D-Y round-trip stamp (Task 9.190).

The mapping function takes pre-v0.4 scorer weights
(``keyword``/``category``/``recency``) and emits v0.4 weights
(``relevance``/``novelty``/``momentum``/``rigor``) that preserve
the user's intent. The function is pure — no I/O, no side effects —
so we can pin every formula leaf in unit tests.

D-Y round-trip stamp: running ``migrate-recipe`` on a recipe already
at the v0.4 schema is a body-no-op, but appends (or replaces) a
``# round-trip stamp YYYY-MM-DD vX.Y.Z`` line at the top of the YAML.
This makes "did the user opt into the current schema?" auditable via
comment scan rather than schema diffing.

Mapping rule (locked in plan §3.5.3 Step 2):

* ``relevance = clip(keyword + 0.5 * category, 0.4, 0.85)``
* ``novelty = 0.10`` (default — conservative for "user never opted in")
* ``rigor = 0.05`` (default — same rationale)
* ``momentum = max(0, 1 - relevance - novelty - rigor)`` (absorbs the residual)
* ``recency`` axis silently discarded (now a filter, not a scorer axis;
  the recipe's existing ``recency`` filter block is preserved by the
  caller).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Pure mapping function
# ---------------------------------------------------------------------------


def test_map_keyword_dominant_recipe_row1() -> None:
    """Plan §3.5.3 row 1: keyword=0.5 / category=0.3 / recency=0.2."""
    from paperwiki.runners.migrate_recipe import map_pre_v04_to_v04_weights

    out = map_pre_v04_to_v04_weights({"keyword": 0.5, "category": 0.3, "recency": 0.2})
    assert out == {
        "relevance": 0.65,
        "novelty": 0.10,
        "momentum": 0.20,
        "rigor": 0.05,
    }


def test_map_keyword_extreme_recipe_row2() -> None:
    """High-keyword recipe: relevance saturates close to ceiling."""
    from paperwiki.runners.migrate_recipe import map_pre_v04_to_v04_weights

    out = map_pre_v04_to_v04_weights({"keyword": 0.7, "category": 0.2, "recency": 0.1})
    # relevance = 0.7 + 0.5*0.2 = 0.80
    # residual = 0.20; novelty=0.10, rigor=0.05 → momentum = 0.05
    assert out == {
        "relevance": 0.80,
        "novelty": 0.10,
        "momentum": 0.05,
        "rigor": 0.05,
    }


def test_map_balanced_recipe_row3() -> None:
    """Category-leaning recipe: relevance below 0.5 still meets the floor."""
    from paperwiki.runners.migrate_recipe import map_pre_v04_to_v04_weights

    out = map_pre_v04_to_v04_weights({"keyword": 0.3, "category": 0.4, "recency": 0.3})
    # relevance = 0.3 + 0.5*0.4 = 0.50
    # residual = 0.50; novelty=0.10, rigor=0.05 → momentum = 0.35
    assert out == {
        "relevance": 0.50,
        "novelty": 0.10,
        "momentum": 0.35,
        "rigor": 0.05,
    }


def test_map_relevance_clipped_at_floor() -> None:
    """All-zero input still gives relevance ≥ 0.4 so the recipe scores anything."""
    from paperwiki.runners.migrate_recipe import map_pre_v04_to_v04_weights

    out = map_pre_v04_to_v04_weights({"keyword": 0.0, "category": 0.0, "recency": 0.0})
    assert out["relevance"] == 0.4


def test_map_relevance_clipped_at_ceiling() -> None:
    """Maxed-out input is clipped at the 0.85 ceiling so other axes get mass."""
    from paperwiki.runners.migrate_recipe import map_pre_v04_to_v04_weights

    out = map_pre_v04_to_v04_weights({"keyword": 1.0, "category": 1.0, "recency": 0.0})
    assert out["relevance"] == 0.85


def test_map_recency_silently_discarded() -> None:
    """The ``recency`` input axis must not appear in the output dict."""
    from paperwiki.runners.migrate_recipe import map_pre_v04_to_v04_weights

    out = map_pre_v04_to_v04_weights({"keyword": 0.5, "category": 0.3, "recency": 0.2})
    assert "recency" not in out


def test_map_axes_sum_to_one() -> None:
    """All four output axes must sum to 1.0 (within float tolerance) so the
    composite scorer doesn't silently amplify or suppress scores."""
    from paperwiki.runners.migrate_recipe import map_pre_v04_to_v04_weights

    for inputs in [
        {"keyword": 0.5, "category": 0.3, "recency": 0.2},
        {"keyword": 0.7, "category": 0.2, "recency": 0.1},
        {"keyword": 0.3, "category": 0.4, "recency": 0.3},
        {"keyword": 0.0, "category": 0.0, "recency": 1.0},
    ]:
        out = map_pre_v04_to_v04_weights(inputs)
        total = sum(out.values())
        assert abs(total - 1.0) < 1e-9, f"axes must sum to 1.0; got {total} for {inputs}"


# ---------------------------------------------------------------------------
# D-Y round-trip stamp
# ---------------------------------------------------------------------------


def test_stamp_round_trip_prepends_when_no_stamp_present(tmp_path: Path) -> None:
    """A clean recipe gains a stamp line at file start; body is unchanged."""
    from paperwiki.runners.migrate_recipe import stamp_round_trip

    recipe = tmp_path / "clean.yaml"
    body = "name: test\nscorer:\n  config:\n    weights:\n      relevance: 0.65\n"
    recipe.write_text(body, encoding="utf-8")

    stamp_round_trip(recipe)

    text = recipe.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert re.match(r"^# round-trip stamp \d{4}-\d{2}-\d{2} v\d+\.\d+\.\d+$", lines[0])
    # Body remains byte-identical after the stamp line.
    assert "\n".join(lines[1:]) + "\n" == body


def test_stamp_round_trip_replaces_existing_stamp(tmp_path: Path) -> None:
    """Re-stamping a recipe that already has a stamp replaces (not stacks)."""
    from paperwiki.runners.migrate_recipe import stamp_round_trip

    recipe = tmp_path / "stamped.yaml"
    recipe.write_text(
        "# round-trip stamp 2025-01-01 v0.0.1\nname: test\nscorer: {}\n",
        encoding="utf-8",
    )

    stamp_round_trip(recipe)

    text = recipe.read_text(encoding="utf-8")
    stamps = re.findall(
        r"^# round-trip stamp \d{4}-\d{2}-\d{2} v\d+\.\d+\.\d+$",
        text,
        re.MULTILINE,
    )
    assert len(stamps) == 1, f"expected exactly 1 stamp, got {len(stamps)}"
    assert "2025-01-01 v0.0.1" not in text


def test_stamp_round_trip_uses_current_paperwiki_version(tmp_path: Path) -> None:
    """The stamp line embeds ``paperwiki.__version__`` verbatim."""
    from paperwiki import __version__
    from paperwiki.runners.migrate_recipe import stamp_round_trip

    recipe = tmp_path / "x.yaml"
    recipe.write_text("name: x\n", encoding="utf-8")

    stamp_round_trip(recipe)

    assert f"v{__version__}" in recipe.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Migration integration: pre-v04 recipe → bak + mapping + stamp
# ---------------------------------------------------------------------------


def test_migrate_pre_v04_recipe_applies_mapping_and_creates_bak(tmp_path: Path) -> None:
    """A recipe with ``keyword/category/recency`` weights gets:

    * a byte-identical backup at ``<recipe>.pre-v04.bak``
    * the mapping applied to the in-place recipe (relevance/novelty/.. axes)
    * a round-trip stamp prepended
    """
    import yaml

    from paperwiki.runners.migrate_recipe import migrate_recipe_file

    recipe = tmp_path / "stale.yaml"
    body = (
        "name: legacy-recipe\n"
        "scorer:\n"
        "  name: composite\n"
        "  config:\n"
        "    weights:\n"
        "      keyword: 0.5\n"
        "      category: 0.3\n"
        "      recency: 0.2\n"
    )
    recipe.write_text(body, encoding="utf-8")
    original_bytes = recipe.read_bytes()

    report = migrate_recipe_file(recipe)

    # Backup byte-identical to original.
    bak = recipe.with_name(recipe.name + ".pre-v04.bak")
    assert bak.is_file()
    assert bak.read_bytes() == original_bytes

    # Migrated recipe has new axes, no legacy axes.
    text = recipe.read_text(encoding="utf-8")
    assert text.startswith("# round-trip stamp ")
    parsed = yaml.safe_load(re.sub(r"^#.*\n", "", text, count=1))
    weights = parsed["scorer"]["config"]["weights"]
    assert "keyword" not in weights
    assert "category" not in weights
    assert "recency" not in weights
    assert weights["relevance"] == 0.65
    assert weights["novelty"] == 0.10
    assert weights["momentum"] == 0.20
    assert weights["rigor"] == 0.05

    # Report acknowledges the schema migration.
    assert report.backup_path == str(bak)


def test_migrate_v04_recipe_is_body_no_op_with_stamp(tmp_path: Path) -> None:
    """A recipe already at v0.4 schema gains a stamp but body is unchanged."""
    from paperwiki.runners.migrate_recipe import migrate_recipe_file

    recipe = tmp_path / "v04.yaml"
    body = (
        "name: already-v04\n"
        "scorer:\n"
        "  name: composite\n"
        "  config:\n"
        "    weights:\n"
        "      relevance: 0.65\n"
        "      novelty: 0.10\n"
        "      momentum: 0.20\n"
        "      rigor: 0.05\n"
    )
    recipe.write_text(body, encoding="utf-8")

    migrate_recipe_file(recipe)

    text = recipe.read_text(encoding="utf-8")
    # Stamp is at line 1.
    assert text.startswith("# round-trip stamp ")
    # Body (after stamp) is byte-identical to the original.
    assert text[text.index("\n") + 1 :] == body
    # No backup created — body didn't actually change.
    bak = recipe.with_name(recipe.name + ".pre-v04.bak")
    assert not bak.exists()


def test_migrate_pre_v04_refuses_when_bak_already_exists(tmp_path: Path) -> None:
    """Pre-existing ``.pre-v04.bak`` blocks re-migration with an actionable error."""
    from paperwiki.core.errors import UserError
    from paperwiki.runners.migrate_recipe import migrate_recipe_file

    recipe = tmp_path / "stale.yaml"
    body = (
        "name: legacy\n"
        "scorer:\n  config:\n    weights:\n"
        "      keyword: 0.5\n      category: 0.3\n      recency: 0.2\n"
    )
    recipe.write_text(body, encoding="utf-8")
    bak = recipe.with_name(recipe.name + ".pre-v04.bak")
    bak.write_text("stale backup\n", encoding="utf-8")

    with pytest.raises(UserError) as exc_info:
        migrate_recipe_file(recipe)

    assert "pre-v04.bak" in str(exc_info.value)
