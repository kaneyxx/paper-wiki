"""Unit tests for ``RecipeSchemaError`` (Task 9.181 / D-W).

When a recipe still uses pre-v0.4 scorer axes (``keyword/category/recency``),
``paperwiki digest`` must:

1. Raise a distinguishable exception type (``RecipeSchemaError``) — not a
   generic ``UserError``, so SKILLs / CLI wrappers can disambiguate
   "user typed bad YAML" from "user is on an old schema and needs to
   run migrate-recipe."
2. Surface a literal ``/paper-wiki:migrate-recipe <path>`` action hint
   in the error message — the SKILL slash-form, not the bare
   ``paperwiki migrate-recipe`` CLI form, so SKILL pipes route correctly.
3. Exit with code ``2`` (``RECIPE_STALE``) — distinct from the generic
   ``UserError`` exit ``1``.
4. Never silently substitute v0.4 default weights (the SKILL session
   that did this in v0.4.0 lost the user's intent).

These tests pin all four bullets from ``tasks/todo.md::Task 9.181``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

_VALID_BODY_TMPL = """\
name: stale-recipe
sources:
  - name: arxiv
    config:
      categories: [cs.AI]
      lookback_days: 1
filters: []
scorer:
  name: composite
  config:
    topics:
      - name: vlm
        keywords: [foundation model]
    weights:
{weights}
reporters:
  - name: markdown
    config:
      output_dir: {output_dir}
top_k: 5
"""


def _write_stale_recipe(tmp_path: Path, *, weights_block: str) -> Path:
    """Render a recipe at ``tmp_path/r.yaml`` with the given weights block.

    The weights block is YAML-indented inline because the schema check
    happens *during* YAML→model validation, so the test's stale weights
    must exist as a real ``weights: {...}`` key under ``scorer.config``.
    """
    output_dir = tmp_path / "out"
    recipe_path = tmp_path / "r.yaml"
    recipe_path.write_text(
        _VALID_BODY_TMPL.format(weights=weights_block, output_dir=output_dir),
        encoding="utf-8",
    )
    return recipe_path


# ---------------------------------------------------------------------------
# Bullet 1: distinguishable exception type
# ---------------------------------------------------------------------------


def test_pre_v04_weights_raise_recipe_schema_error(tmp_path: Path) -> None:
    """A recipe with ``keyword/category/recency`` weights raises the
    dedicated ``RecipeSchemaError`` rather than a generic ``UserError``."""
    from paperwiki.config.recipe import RecipeSchemaError, load_recipe

    recipe_path = _write_stale_recipe(
        tmp_path,
        weights_block="      keyword: 0.5\n      category: 0.3\n      recency: 0.2",
    )

    with pytest.raises(RecipeSchemaError):
        load_recipe(recipe_path)


def test_recipe_schema_error_is_a_user_error_subclass() -> None:
    """``RecipeSchemaError`` subclasses ``UserError`` so existing
    ``except UserError:`` handlers still catch it (back-compat); the
    type can be narrowed when the runner wants more-specific UX."""
    from paperwiki.config.recipe import RecipeSchemaError
    from paperwiki.core.errors import UserError

    assert issubclass(RecipeSchemaError, UserError)


def test_recipe_schema_error_exit_code_is_two() -> None:
    """Exit code 2 is reserved for ``RECIPE_STALE`` per the plan, distinct
    from the generic ``UserError`` exit code 1 — so a SKILL pipe can
    detect "needs migrate-recipe" without parsing the message text."""
    from paperwiki.config.recipe import RecipeSchemaError

    assert RecipeSchemaError.exit_code == 2


# ---------------------------------------------------------------------------
# Bullet 2: literal /paper-wiki:migrate-recipe <path> hint in message
# ---------------------------------------------------------------------------


def test_error_message_includes_skill_form_migrate_hint(tmp_path: Path) -> None:
    """The message text uses the SKILL slash-prefixed form so SKILL pipes
    treat it as an actionable command, not a CLI-form recipe-author tip.

    The path passed to ``load_recipe`` round-trips into the message.
    """
    from paperwiki.config.recipe import RecipeSchemaError, load_recipe

    recipe_path = _write_stale_recipe(
        tmp_path,
        weights_block="      keyword: 0.5\n      category: 0.3\n      recency: 0.2",
    )

    with pytest.raises(RecipeSchemaError) as exc_info:
        load_recipe(recipe_path)

    message = str(exc_info.value)
    assert "/paper-wiki:migrate-recipe" in message, (
        "error must include the slash-prefixed SKILL form so SKILL pipes "
        "auto-route the action; CLI form ``paperwiki migrate-recipe`` is "
        "explicitly insufficient per D-W companion criterion"
    )
    assert str(recipe_path) in message, (
        "error must echo the recipe path so the user can copy-paste the "
        "migrate-recipe command without reconstructing the path"
    )


def test_error_message_calls_out_pre_v04_schema(tmp_path: Path) -> None:
    """Message text states what's wrong (pre-v0.4 schema), not just the
    fix, so users grasp why migrate-recipe is the action."""
    from paperwiki.config.recipe import RecipeSchemaError, load_recipe

    recipe_path = _write_stale_recipe(
        tmp_path,
        weights_block="      keyword: 0.7\n      category: 0.2\n      recency: 0.1",
    )

    with pytest.raises(RecipeSchemaError) as exc_info:
        load_recipe(recipe_path)

    message = str(exc_info.value).lower()
    assert "pre-v0.4" in message or "v0.4" in message


# ---------------------------------------------------------------------------
# Bullet 3: CLI exit code 2 (subprocess test)
# ---------------------------------------------------------------------------


def test_digest_cli_exits_two_on_stale_recipe(tmp_path: Path) -> None:
    """``paperwiki digest <stale-recipe>`` exits with code 2 (RECIPE_STALE).

    Use ``CliRunner`` (in-process) rather than a real subprocess because
    pytest fixtures don't survive ``subprocess.run``. The exit-code path
    runs through the same ``raise typer.Exit(exc.exit_code)`` regardless.
    """
    from paperwiki.runners import digest as digest_runner

    recipe_path = _write_stale_recipe(
        tmp_path,
        weights_block="      keyword: 0.5\n      category: 0.3\n      recency: 0.2",
    )

    runner = CliRunner()
    result = runner.invoke(digest_runner.app, [str(recipe_path)])

    assert result.exit_code == 2, (
        f"stale recipe should exit 2 (RECIPE_STALE), got {result.exit_code}\n"
        f"output:\n{result.output}"
    )


# ---------------------------------------------------------------------------
# Bullet 4: SKILL contract (no silent defaults)
# ---------------------------------------------------------------------------


def test_digest_skill_has_when_this_fails_section_referencing_migrate_recipe() -> None:
    """``skills/digest/SKILL.md`` must document the migrate-recipe escape
    hatch in a "When this fails" stanza so SKILL operators don't invent
    default weights to "fix" the error (which loses the user's intent)."""
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parents[3]
    skill_md = repo_root / "skills" / "digest" / "SKILL.md"
    body = skill_md.read_text(encoding="utf-8")

    # The literal SKILL hint that must appear so the SKILL pipe routes
    # the command back through the slash form.
    assert "/paper-wiki:migrate-recipe" in body, (
        "digest SKILL.md must reference /paper-wiki:migrate-recipe in its "
        "failure-mode docs — the recipe-stale path is otherwise invisible "
        "to SKILL operators"
    )
    # And a "When this fails" or equivalent header that gates the
    # do-not-invent-defaults rule.
    body_lower = body.lower()
    assert "when this fails" in body_lower or (
        "schema" in body_lower and "default" in body_lower
    ), (
        "digest SKILL.md must include a 'When this fails' stanza (or "
        "schema-specific guidance) that forbids inventing default weights"
    )


# ---------------------------------------------------------------------------
# Negative tests: current schema is untouched
# ---------------------------------------------------------------------------


def test_current_schema_weights_do_not_raise(tmp_path: Path) -> None:
    """A recipe with v0.4 axes (``relevance/novelty/momentum/rigor``)
    loads cleanly — the schema check must not flag-positive on healthy
    recipes."""
    from paperwiki.config.recipe import load_recipe

    recipe_path = _write_stale_recipe(
        tmp_path,
        weights_block=(
            "      relevance: 0.4\n      novelty: 0.2\n      momentum: 0.3\n      rigor: 0.1"
        ),
    )

    # Should load without raising (sanity: result.scorer.config has weights).
    recipe = load_recipe(recipe_path)
    assert recipe.scorer.name == "composite"


def test_recipe_without_weights_block_is_unaffected(tmp_path: Path) -> None:
    """Recipes that don't define ``weights`` at all (using the v0.4
    defaults from ``DEFAULT_SCORE_WEIGHTS``) load fine — the schema
    check only fires when stale axes are explicitly present."""
    from paperwiki.config.recipe import load_recipe

    output_dir = tmp_path / "out"
    recipe_path = tmp_path / "r.yaml"
    recipe_path.write_text(
        f"""\
name: no-weights
sources:
  - name: arxiv
    config:
      categories: [cs.AI]
      lookback_days: 1
filters: []
scorer:
  name: composite
  config:
    topics:
      - name: vlm
        keywords: [foundation model]
reporters:
  - name: markdown
    config:
      output_dir: {output_dir}
top_k: 5
""",
        encoding="utf-8",
    )

    recipe = load_recipe(recipe_path)
    assert recipe.scorer.name == "composite"
