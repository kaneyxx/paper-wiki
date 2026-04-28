"""Regression tests for SKILL.md files vs. v0.3.34 contract.

The v0.3.34 release sweeps every legacy ``${CLAUDE_PLUGIN_ROOT}/.venv/...``
reference out of ``skills/*/SKILL.md`` and converges every runner
invocation on the ``paperwiki <subcommand>`` shim. These tests pin the
contract so nobody re-introduces the v0.3.28 patterns.

The four invariants per :ref:`D-9.34.4` (tasks/plan.md §12.2):

1. **No naked legacy venv references.** Pattern
   ``${CLAUDE_PLUGIN_ROOT}/.venv/`` must not appear in any SKILL.
2. **No phantom ``--fold-citations`` flag.** The flag was prose-only and
   never implemented; it must not appear in any SKILL.
3. **digest Step 7b explicit-flag pin.** ``skills/digest/SKILL.md`` must
   reference the literal ``paperwiki wiki-ingest`` invocation with
   ``--auto-bootstrap`` (no ``--fold-citations``).
4. **wiki-ingest CLI signature pin.** Parse the runner module via AST
   and assert ``--fold-citations`` is NOT in the accepted Typer flag set
   — catches the inverse drift (someone re-adds the flag to the runner
   without updating the SKILLs, or vice-versa).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _REPO_ROOT / "skills"


def _all_skill_files() -> list[Path]:
    """Return every ``skills/*/SKILL.md`` file in the repo."""
    return sorted(_SKILLS_DIR.glob("*/SKILL.md"))


def _skill_ids() -> list[str]:
    """Stable parametrize ids: the skill directory name."""
    return [p.parent.name for p in _all_skill_files()]


# ---------------------------------------------------------------------------
# Invariant 1: legacy venv reference sweep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_path", _all_skill_files(), ids=_skill_ids())
def test_no_legacy_venv_python_invocation(skill_path: Path) -> None:
    """SKILL must not invoke ``${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.``.

    v0.3.29 centralised the venv to ``${PAPERWIKI_HOME}/venv/`` and
    introduced the ``paperwiki <subcommand>`` shim. SKILLs that still
    invoke the per-version venv directly will fail for end-users
    without a developer clone of the repo.
    """
    body = skill_path.read_text(encoding="utf-8")
    legacy = "${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners."
    assert legacy not in body, (
        f"{skill_path.relative_to(_REPO_ROOT)} still uses the legacy "
        f"per-version venv invocation. Replace with `paperwiki <subcommand>`."
    )


@pytest.mark.parametrize("skill_path", _all_skill_files(), ids=_skill_ids())
def test_no_legacy_venv_paperwiki_fallback(skill_path: Path) -> None:
    """SKILL must not reference ``${CLAUDE_PLUGIN_ROOT}/.venv/bin/paperwiki``.

    The flavour-C fallback (status / update / uninstall) has been
    superseded by the defensive ``export PATH="$HOME/.local/bin:$PATH"``
    guard. The fallback path no longer exists past v0.3.29.
    """
    body = skill_path.read_text(encoding="utf-8")
    legacy = "${CLAUDE_PLUGIN_ROOT}/.venv/bin/paperwiki"
    assert legacy not in body, (
        f"{skill_path.relative_to(_REPO_ROOT)} still references the "
        f"legacy per-version paperwiki binary. Drop the fallback and "
        f"rely on the ~/.local/bin/paperwiki shim instead."
    )


@pytest.mark.parametrize("skill_path", _all_skill_files(), ids=_skill_ids())
def test_no_legacy_venv_installed_stamp(skill_path: Path) -> None:
    """SKILL must not check ``${CLAUDE_PLUGIN_ROOT}/.venv/.installed``.

    v0.3.29+: the readiness gate is "the shim runs at all". The stamp
    is internal to ``hooks/ensure-env.sh`` and not user-visible.
    """
    body = skill_path.read_text(encoding="utf-8")
    legacy = "${CLAUDE_PLUGIN_ROOT}/.venv/.installed"
    assert legacy not in body, (
        f"{skill_path.relative_to(_REPO_ROOT)} still checks the legacy "
        f".installed stamp. Use `paperwiki status` (or trust the shim) "
        f"as the readiness gate instead."
    )


# ---------------------------------------------------------------------------
# Invariant 2: phantom --fold-citations flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_path", _all_skill_files(), ids=_skill_ids())
def test_no_fold_citations_flag(skill_path: Path) -> None:
    """SKILL must not pass the ``--fold-citations`` flag.

    The flag was documented in the digest SKILL since v0.3.13 but was
    NEVER added to ``paperwiki.runners.wiki_ingest_plan``. Citation
    folding is implicit when ``--auto-bootstrap`` is set.
    """
    body = skill_path.read_text(encoding="utf-8")
    assert "--fold-citations" not in body, (
        f"{skill_path.relative_to(_REPO_ROOT)} references the phantom "
        f"`--fold-citations` flag. The flag was never implemented in "
        f"`paperwiki.runners.wiki_ingest_plan`; citation folding runs "
        f"unconditionally inside the `--auto-bootstrap` path."
    )


# ---------------------------------------------------------------------------
# Invariant 3: digest Step 7b explicit-flag pin
# ---------------------------------------------------------------------------


def test_digest_step_7b_uses_explicit_paperwiki_wiki_ingest() -> None:
    """``skills/digest/SKILL.md`` Step 7b must call ``paperwiki wiki-ingest``.

    The slash-command form ``/paper-wiki:wiki-ingest <id>`` inside a
    parent SKILL bash block forces Claude to translate it to a runner,
    which has historically gone wrong. The explicit shim invocation
    collapses the indirection.
    """
    body = (_SKILLS_DIR / "digest" / "SKILL.md").read_text(encoding="utf-8")
    assert "paperwiki wiki-ingest" in body, (
        "skills/digest/SKILL.md must use the explicit "
        "`paperwiki wiki-ingest <vault> <id> --auto-bootstrap` form in "
        "Step 7b — not the slash-command chain."
    )
    assert "--auto-bootstrap" in body, (
        "skills/digest/SKILL.md Step 7b must pass `--auto-bootstrap` for citation folding."
    )


# ---------------------------------------------------------------------------
# Invariant 4: wiki-ingest CLI signature pin (AST-based)
# ---------------------------------------------------------------------------


def _typer_option_names_from_ast(source_path: Path, func_name: str) -> set[str]:
    """Return the set of long-form Typer option names for ``func_name`` in *source_path*.

    Walks the AST of ``source_path``, finds the function definition
    matching ``func_name``, and extracts every ``--<name>`` literal
    from the ``typer.Option(...)`` calls in the parameter defaults.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return _scan_function_typer_options(node)
    msg = f"function {func_name!r} not found in {source_path}"
    raise AssertionError(msg)


def _scan_function_typer_options(func_node: ast.FunctionDef) -> set[str]:
    """Walk a function's args and return every ``--<flag>`` Typer literal."""
    flags: set[str] = set()
    for arg in func_node.args.args:
        annotation = arg.annotation
        if not isinstance(annotation, ast.Subscript):
            continue
        # Annotated[T, typer.Option(...)] — the call is the second slice element.
        slice_node = annotation.slice
        if isinstance(slice_node, ast.Tuple):
            for elt in slice_node.elts[1:]:
                flags.update(_extract_dash_flags(elt))
        else:  # py-3.8 single-element form, defensive
            flags.update(_extract_dash_flags(slice_node))
    return flags


def _extract_dash_flags(node: ast.AST) -> set[str]:
    """From a ``typer.Option(...)`` ast.Call, return its ``--<name>`` literals."""
    if not isinstance(node, ast.Call):
        return set()
    flags: set[str] = set()
    for child in node.args:
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value.startswith("--")
        ):
            flags.add(child.value)
    return flags


def test_wiki_ingest_cli_does_not_accept_fold_citations() -> None:
    """``paperwiki.runners.wiki_ingest_plan.main`` has no ``--fold-citations``.

    Inverse-drift guard for invariant 2: if someone re-adds the flag to
    the runner, this test fails so the SKILLs and the runner stay in
    sync — either both have it, or both don't. v0.3.34 ships with
    neither (citation folding is implicit).
    """
    runner = _REPO_ROOT / "src" / "paperwiki" / "runners" / "wiki_ingest_plan.py"
    flags = _typer_option_names_from_ast(runner, "main")
    assert "--fold-citations" not in flags, (
        "paperwiki.runners.wiki_ingest_plan accepts `--fold-citations`; "
        "either drop the flag or update the SKILLs to pass it again "
        "(see tests/unit/test_skills_md_no_legacy_venv.py)."
    )


# ---------------------------------------------------------------------------
# Invariant 5: SKILLs that shell out to paperwiki use the shim form
# ---------------------------------------------------------------------------


_SHIM_USING_SKILLS = (
    "digest",
    "wiki-ingest",
    "wiki-lint",
    "wiki-compile",
    "wiki-query",
    "extract-images",
    "migrate-recipe",
    "migrate-sources",
    "bio-search",
    "status",
    "update",
    "uninstall",
    "setup",
)


@pytest.mark.parametrize("skill_name", _SHIM_USING_SKILLS)
def test_skill_uses_paperwiki_shim_invocation(skill_name: str) -> None:
    """Each runner-invoking SKILL must reference the ``paperwiki <X>`` shim.

    The literal substring ``paperwiki `` (with trailing space) followed
    by a known subcommand is required at least once. ``analyze`` is
    excluded — it doesn't shell out to a runner directly.
    """
    body = (_SKILLS_DIR / skill_name / "SKILL.md").read_text(encoding="utf-8")
    accepted_subcommands = (
        "digest",
        "wiki-ingest",
        "wiki-lint",
        "wiki-compile",
        "wiki-query",
        "extract-images",
        "migrate-recipe",
        "migrate-sources",
        "diagnostics",
        "gc-archive",
        "gc-bak",
        "where",
        "update",
        "status",
        "uninstall",
    )
    matches = [sub for sub in accepted_subcommands if f"paperwiki {sub}" in body]
    assert matches, (
        f"skills/{skill_name}/SKILL.md does not reference any "
        f"`paperwiki <subcommand>` invocation. Did the v0.3.34 sweep "
        f"miss this file?"
    )
