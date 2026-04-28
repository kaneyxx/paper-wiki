"""Static-text checks pinning the v0.3.33 digest SKILL Step 1 hardening.

Background (v0.3.33): the v0.3.32 SKILL described recipe resolution as
prose, which let Claude run ``ls recipes/`` with a cwd that drifted into
the plugin cache directory and pick a bundled starter recipe instead of
the user's personal recipe at ``~/.config/paper-wiki/recipes/``.

These tests pin the explicit-bash replacement so future edits cannot
silently regress to ambiguous prose.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = REPO_ROOT / "skills" / "digest" / "SKILL.md"


def test_digest_skill_step1_uses_explicit_config_root_resolution() -> None:
    """Step 1 must contain the absolute-path bash snippet, not prose."""
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert 'CONFIG_ROOT="${PAPERWIKI_HOME:-' in body, (
        "SKILL.md Step 1 must define CONFIG_ROOT using the "
        "PAPERWIKI_HOME -> PAPERWIKI_CONFIG_DIR -> ~/.config/paper-wiki "
        "precedence chain so personal recipes always resolve regardless of cwd"
    )


def test_digest_skill_step1_personal_recipe_first() -> None:
    """Personal recipe at $CONFIG_ROOT/recipes/ must take precedence over bundled."""
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "$CONFIG_ROOT/recipes/$name.yaml" in body, (
        "SKILL.md Step 1 must check $CONFIG_ROOT/recipes/$name.yaml first "
        "(personal recipe before bundled fallback)"
    )
    assert "CLAUDE_PLUGIN_ROOT/recipes/$name.yaml" in body, (
        "SKILL.md Step 1 must fall back to ${CLAUDE_PLUGIN_ROOT}/recipes/ "
        "only when no personal recipe exists"
    )


def test_digest_skill_step1_maps_weekly_and_biomedical_aliases() -> None:
    """Case mapping for `weekly` and `bio|biomedical` must be present."""
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "weekly-deep-dive" in body
    assert "biomedical-weekly" in body
    assert "bio|biomedical" in body, (
        "SKILL.md Step 1 must include the `bio|biomedical) name=biomedical-weekly` "
        "case-statement alias mapping"
    )


def test_digest_skill_step1_mandates_visibility_echo() -> None:
    """The `echo "Using recipe: $RECIPE"` line must be in Step 1 for visibility."""
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert 'echo "Using recipe: $RECIPE"' in body, (
        "SKILL.md Step 1 must echo the resolved recipe path so the user "
        "can see which recipe was actually picked (the smoking gun for v0.3.32)"
    )


def test_digest_skill_step1_forbids_ls_find_cd_in_lead() -> None:
    """The lead paragraph for Step 1 must explicitly forbid `ls`, `find`, `cd`."""
    body = SKILL_PATH.read_text(encoding="utf-8")
    # Locate the Step 1 lead paragraph (between "1. **Locate the recipe.**" and
    # the first opening fenced bash block).
    step1_marker = "1. **Locate the recipe.**"
    bash_marker = "```bash"
    assert step1_marker in body, "Step 1 header missing"
    lead_start = body.index(step1_marker)
    bash_start = body.index(bash_marker, lead_start)
    lead = body[lead_start:bash_start]
    # All three forbidden tools must be named in the lead so Claude reads them
    # before executing.
    assert "ls" in lead, "Step 1 lead must forbid `ls`"
    assert "find" in lead, "Step 1 lead must forbid `find`"
    assert "cd" in lead, "Step 1 lead must forbid `cd`"
    assert "relative paths" in lead, "Step 1 lead must forbid relative paths"


def test_digest_skill_no_naked_ls_recipes_instruction() -> None:
    """Process steps must not contain a naked `ls recipes/` instruction.

    `ls recipes/` is allowed in the Common Rationalizations table (where it
    is quoted as an anti-pattern) and in the Red Flags list (where it is
    cited as a STOP signal). It must NOT appear as an instruction in the
    Process steps.
    """
    body = SKILL_PATH.read_text(encoding="utf-8")
    process_marker = "## Process"
    rationalizations_marker = "## Common Rationalizations"
    process_start = body.index(process_marker)
    process_end = body.index(rationalizations_marker)
    process_block = body[process_start:process_end]
    assert "ls recipes/" not in process_block, (
        "The Process section must not contain a `ls recipes/` instruction "
        "(that's the v0.3.32 bug — `ls` lands in the plugin starter dir). "
        "It is permitted only inside the Rationalizations / Red Flags blocks."
    )


def test_digest_skill_step4_invokes_recipe_variable() -> None:
    """Step 4 must invoke the runner with `$RECIPE` (the variable from Step 1).

    Using a `<recipe-path>` placeholder lets Claude substitute its own guess.
    Using `$RECIPE` makes the dependency on Step 1 explicit.
    """
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert '"$RECIPE"' in body, (
        'Step 4 must invoke the digest runner with `"$RECIPE"` so the '
        "recipe path comes from Step 1's bash resolution, not Claude's guess"
    )


def test_digest_skill_rationalizations_warns_about_ls() -> None:
    """A rationalizations row must call out `ls recipes/` as an anti-pattern."""
    body = SKILL_PATH.read_text(encoding="utf-8")
    rationalizations_marker = "## Common Rationalizations"
    red_flags_marker = "## Red Flags"
    rat_start = body.index(rationalizations_marker)
    rat_end = body.index(red_flags_marker)
    rat_block = body[rat_start:rat_end]
    assert "ls recipes/" in rat_block, (
        "Common Rationalizations must include an `ls recipes/` row warning "
        "that it lands in the plugin starter directory"
    )


def test_digest_skill_red_flags_includes_ls_recipes_stop_signal() -> None:
    """Red Flags must include a STOP signal for `ls recipes/`, `cd`, relative paths."""
    body = SKILL_PATH.read_text(encoding="utf-8")
    red_flags_marker = "## Red Flags"
    verification_marker = "## Verification"
    rf_start = body.index(red_flags_marker)
    rf_end = body.index(verification_marker)
    rf_block = body[rf_start:rf_end]
    # The bullet should mention at least one of the forbidden patterns and the
    # word STOP / Re-read so Claude treats it as an interrupt.
    assert "ls recipes/" in rf_block, "Red Flags must include an `ls recipes/` STOP signal"
    assert "STOP" in rf_block, (
        "Red Flags must use STOP capitalized so the bullet reads as an interrupt"
    )
