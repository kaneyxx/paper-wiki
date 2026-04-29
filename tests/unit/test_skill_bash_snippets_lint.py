"""Static lint for SKILL bash blocks and inline ``paperwiki.*`` module paths.

v0.3.36 D-9.36.2 + D-9.36.5 (plan §13.3 Phase 4). The fresh-user setup
trace exposed a class of bugs that all share the same root cause: the
SKILL prose ships imperative bash/Python snippets, Claude follows them
literally, and any drift between the snippet and the on-disk reality
causes a "red error -> self-correct -> green success" sequence in the
user's transcript. From a fresh-user perspective this looks
unprofessional even though the end state is correct.

The fix is a static lint that catches the whole class:

* **F1**: ``paperwiki.config.recipes`` (plural, no ``_migrations`` suffix).
  Real path is ``paperwiki.config.recipe`` (singular). Caused the
  v0.3.35 setup ``ModuleNotFoundError`` self-correction.
* **F2**: ``paperwiki.runners.wiki_ingest`` not followed by ``_plan``.
  Real path is ``paperwiki.runners.wiki_ingest_plan``. Caused the
  v0.3.34 trace bug.
* **F3**: ``CLAUDE_PLUGIN_ROOT=$(...)`` defensive resolver without a
  matching ``export``. Sweep introduced in v0.3.34 D-9.34.2 and
  hardened in v0.3.36 D-9.36.4.
* **F4**: ``bash -n`` parse failure on any fenced ``bash`` block.
  Catches actual syntax errors that would never run as a subprocess.
* **F5**: ``from paperwiki.config import RecipeSchema`` (without the
  ``.recipe.`` segment). Currently fails at import time;
  ``RecipeSchema`` lives at ``paperwiki.config.recipe.RecipeSchema``.

A region wrapped in ``<!-- skip-lint --> ... <!-- /skip-lint -->`` is
exempt from the substring/regex checks (F1/F2/F5). This lets SKILLs
cite a forbidden pattern in a Common Rationalizations table or Red
Flags entry as an anti-example without tripping the lint. The bash
parse check (F4) and the export sweep (F3) are not skip-able.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _REPO_ROOT / "skills"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Forbidden pattern catalogue (D-9.36.5)
# ---------------------------------------------------------------------------
#
# Each entry has:
#   - id: stable lookup key (string)
#   - regex: compiled regex; a match means the SKILL is broken
#   - description: short human-readable summary used in failure messages
#   - rationale: the "why" — usually a reference to the bug that motivated
#     the rule. Future contributors edit this dict to extend the lint.

FORBIDDEN_PATTERNS: dict[str, dict[str, object]] = {
    "F1": {
        "regex": re.compile(r"paperwiki\.config\.recipes(?!_)"),
        "description": "wrong module path `paperwiki.config.recipes`",
        "rationale": (
            "Real path is `paperwiki.config.recipe` (singular) for the "
            "schema/loader, or `paperwiki.config.recipe_migrations` for "
            "STALE_MARKERS. v0.3.35 setup smoke trace caught this as a "
            "ModuleNotFoundError self-correction."
        ),
    },
    "F2": {
        "regex": re.compile(r"\bpaperwiki\.runners\.wiki_ingest\b(?!_plan)"),
        "description": "wrong runner module `paperwiki.runners.wiki_ingest`",
        "rationale": (
            "Real path is `paperwiki.runners.wiki_ingest_plan`. v0.3.34 "
            "trace bug — the bare name doesn't exist."
        ),
    },
    "F5": {
        "regex": re.compile(r"from\s+paperwiki\.config\s+import\s+RecipeSchema\b"),
        "description": "missing `.recipe.` segment in RecipeSchema import",
        "rationale": (
            "RecipeSchema lives at `paperwiki.config.recipe.RecipeSchema` "
            "(singular). The package root does not re-export it, so "
            "`from paperwiki.config import RecipeSchema` raises ImportError."
        ),
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_skill_files() -> list[Path]:
    """Return every ``skills/*/SKILL.md`` file in the repo."""
    return sorted(_SKILLS_DIR.glob("*/SKILL.md"))


def _skill_ids() -> list[str]:
    """Stable parametrize ids: the skill directory name."""
    return [p.parent.name for p in _all_skill_files()]


_SKIP_LINT_RE = re.compile(
    r"<!--\s*skip-lint\s*-->.*?<!--\s*/skip-lint\s*-->",
    re.DOTALL,
)


def _strip_skip_lint_regions(body: str) -> str:
    """Remove ``<!-- skip-lint -->...<!-- /skip-lint -->`` regions.

    Single-line and multi-line forms are both supported. Used by the
    F1/F2/F5 substring/regex checks so SKILLs can cite a forbidden
    pattern as an anti-example in Common Rationalizations or Red
    Flags without tripping the lint.
    """
    return _SKIP_LINT_RE.sub("", body)


_BASH_FENCE_RE = re.compile(
    r"^(?P<indent>[ \t]*)```bash[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^(?P=indent)```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


def _extract_bash_blocks(body: str) -> list[str]:
    """Extract every fenced ```bash block, dedenting to the fence's indent.

    The dedent step matters because some SKILLs wrap bash blocks
    inside numbered lists (e.g. ``digest`` Step 1), and the fence
    itself sits at 3-space indent. Stripping that uniform indent
    prevents the ``bash -n`` step from tripping on stray indented
    content that's syntactically fine in shell but cosmetically
    indented in markdown.
    """
    blocks: list[str] = []
    for match in _BASH_FENCE_RE.finditer(body):
        block_text = match.group("body")
        indent = match.group("indent")
        if indent:
            dedented_lines: list[str] = []
            for line in block_text.split("\n"):
                if line.startswith(indent):
                    dedented_lines.append(line[len(indent) :])
                else:
                    dedented_lines.append(line)
            block_text = "\n".join(dedented_lines)
        blocks.append(block_text)
    return blocks


# SKILLs document command shapes with `<placeholder>` tokens (e.g.
# ``paperwiki wiki-ingest <vault> <id>``). Bash parses bare ``<word>``
# as input redirection, so a verbatim ``bash -n`` would flag these as
# syntax errors even though the prose intent is clear. Preprocess by
# wrapping each placeholder in double quotes — same visual, but bash
# parses it as a string literal. The substitution is non-destructive
# (it does not touch redirection operators like ``< file`` or
# ``<<EOF``, both of which need whitespace before the ``<``).
_PLACEHOLDER_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_./-]*)>")


def _quote_placeholders(snippet: str) -> str:
    """Wrap ``<placeholder>`` tokens in double quotes for ``bash -n``."""
    return _PLACEHOLDER_RE.sub(r'"<\1>"', snippet)


_CLAUDE_ASSIGN_RE = re.compile(r"CLAUDE_PLUGIN_ROOT=\$\(")
_EXPORT_CLAUDE_RE = re.compile(r"\bexport\s+CLAUDE_PLUGIN_ROOT\b")
_F3_WINDOW = 12  # Lines after the assignment to scan for a matching `export`.


def _check_claude_plugin_root_exports(body: str) -> list[tuple[int, str]]:
    """Return ``[(lineno, line)]`` for every ``CLAUDE_PLUGIN_ROOT=$(`` site
    that lacks a matching ``export``.

    A site is considered well-formed if either:

    * the assignment line itself contains ``export `` (inline form
      ``export CLAUDE_PLUGIN_ROOT=$(...)``), OR
    * a separate ``export CLAUDE_PLUGIN_ROOT`` line appears within
      the next ``_F3_WINDOW`` lines.

    Both are acceptable per D-9.36.4. Either form ensures child
    shells inherit the resolved root.
    """
    lines = body.split("\n")
    offenders: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if not _CLAUDE_ASSIGN_RE.search(line):
            continue
        if _EXPORT_CLAUDE_RE.search(line):
            continue
        window_end = min(idx + _F3_WINDOW + 1, len(lines))
        if any(_EXPORT_CLAUDE_RE.search(later) for later in lines[idx + 1 : window_end]):
            continue
        offenders.append((idx + 1, line.rstrip()))
    return offenders


# ---------------------------------------------------------------------------
# Tests over real SKILLs
# ---------------------------------------------------------------------------


_BASH_AVAILABLE = shutil.which("bash") is not None


@pytest.mark.skipif(not _BASH_AVAILABLE, reason="bash binary not on PATH")
@pytest.mark.parametrize("skill_path", _all_skill_files(), ids=_skill_ids())
def test_bash_blocks_parse(skill_path: Path, tmp_path: Path) -> None:
    """F4: every fenced ```bash block parses with ``bash -n`` (syntax-only)."""
    body = skill_path.read_text(encoding="utf-8")
    blocks = _extract_bash_blocks(body)
    for index, block in enumerate(blocks):
        snippet_path = tmp_path / f"{skill_path.parent.name}_{index}.sh"
        snippet_path.write_text(_quote_placeholders(block), encoding="utf-8")
        proc = subprocess.run(
            ["bash", "-n", str(snippet_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            f"{skill_path.relative_to(_REPO_ROOT)} bash block #{index} "
            f"failed `bash -n`:\n"
            f"--- block ---\n{block}\n"
            f"--- stderr ---\n{proc.stderr}"
        )


@pytest.mark.parametrize(
    ("skill_path", "pattern_id"),
    [
        (skill_path, pattern_id)
        for skill_path in _all_skill_files()
        for pattern_id in FORBIDDEN_PATTERNS
    ],
    ids=[
        f"{skill_path.parent.name}-{pattern_id}"
        for skill_path in _all_skill_files()
        for pattern_id in FORBIDDEN_PATTERNS
    ],
)
def test_no_forbidden_module_paths(skill_path: Path, pattern_id: str) -> None:
    """F1, F2, F5: forbidden module-path substrings/regexes never appear.

    Skip-lint regions are stripped first so anti-example citations in
    Common Rationalizations don't trip this check.
    """
    body = _strip_skip_lint_regions(skill_path.read_text(encoding="utf-8"))
    pattern = FORBIDDEN_PATTERNS[pattern_id]
    regex: re.Pattern[str] = pattern["regex"]  # type: ignore[assignment]
    description = pattern["description"]
    rationale = pattern["rationale"]
    match = regex.search(body)
    assert match is None, (
        f"{skill_path.relative_to(_REPO_ROOT)} contains forbidden pattern "
        f"`{pattern_id}` ({description}) at offset {match.start() if match else -1!r}: "
        f"`{match.group(0) if match else '?'}`. Rationale: {rationale}\n"
        f"If this is an intentional anti-example, wrap it in "
        f"<!-- skip-lint --> ... <!-- /skip-lint --> markers."
    )


@pytest.mark.parametrize("skill_path", _all_skill_files(), ids=_skill_ids())
def test_claude_plugin_root_always_exported(skill_path: Path) -> None:
    """F3: every ``CLAUDE_PLUGIN_ROOT=$(...)`` assignment must be exported.

    Either inline (``export CLAUDE_PLUGIN_ROOT=$(...)``) or via a
    separate ``export CLAUDE_PLUGIN_ROOT`` line within 12 lines.
    Catches the v0.3.34 D-9.34.2 sweep regression — child shells
    that need the var get an empty value otherwise, and ensure-env.sh
    exits with "CLAUDE_PLUGIN_ROOT must be set by Claude Code".
    """
    body = skill_path.read_text(encoding="utf-8")
    offenders = _check_claude_plugin_root_exports(body)
    assert not offenders, (
        f"{skill_path.relative_to(_REPO_ROOT)} has bare "
        f"`CLAUDE_PLUGIN_ROOT=$(` assignment(s) without a matching "
        f"`export CLAUDE_PLUGIN_ROOT` within {_F3_WINDOW} lines:\n"
        + "\n".join(f"  line {ln}: {text}" for ln, text in offenders)
    )


# ---------------------------------------------------------------------------
# Tests over the synthetic ``bad_skill.md`` fixture (negative path)
# ---------------------------------------------------------------------------


_BAD_FIXTURE = _FIXTURES_DIR / "bad_skill.md"


def test_fixture_exists() -> None:
    assert _BAD_FIXTURE.is_file(), (
        f"missing fixture {_BAD_FIXTURE}; the lint test needs a synthetic "
        f"bad-skill file to exercise its detection logic."
    )


def test_fixture_trips_F1_F2_F5() -> None:  # noqa: N802 — IDs match the rule names.
    body = _strip_skip_lint_regions(_BAD_FIXTURE.read_text(encoding="utf-8"))
    for pattern_id in ("F1", "F2", "F5"):
        regex: re.Pattern[str] = FORBIDDEN_PATTERNS[pattern_id]["regex"]  # type: ignore[assignment]
        assert regex.search(body) is not None, (
            f"fixture {_BAD_FIXTURE.name} should contain forbidden pattern "
            f"{pattern_id} but the regex did not match — fixture has drifted."
        )


def test_fixture_trips_F3() -> None:  # noqa: N802 — ID matches the rule name.
    offenders = _check_claude_plugin_root_exports(_BAD_FIXTURE.read_text(encoding="utf-8"))
    assert offenders, (
        f"fixture {_BAD_FIXTURE.name} should contain a bare "
        f"CLAUDE_PLUGIN_ROOT=$(...) assignment to exercise the F3 check."
    )


@pytest.mark.skipif(not _BASH_AVAILABLE, reason="bash binary not on PATH")
def test_fixture_trips_F4(tmp_path: Path) -> None:  # noqa: N802 — ID matches the rule name.
    body = _BAD_FIXTURE.read_text(encoding="utf-8")
    blocks = _extract_bash_blocks(body)
    failed = 0
    for index, block in enumerate(blocks):
        snippet_path = tmp_path / f"bad_{index}.sh"
        snippet_path.write_text(_quote_placeholders(block), encoding="utf-8")
        proc = subprocess.run(
            ["bash", "-n", str(snippet_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            failed += 1
    assert failed >= 1, (
        f"fixture {_BAD_FIXTURE.name} should contain at least one bash "
        f"block that fails `bash -n` to exercise the F4 check."
    )


def test_skip_lint_marker_strips_anti_examples() -> None:
    """A forbidden pattern wrapped in skip-lint markers is exempt."""
    body = (
        "Plain prose with `paperwiki.config.recipes` would normally trip F1.\n"
        "<!-- skip-lint -->\n"
        "But this paragraph mentions `paperwiki.config.recipes` as an anti-\n"
        "example for documentation purposes.\n"
        "<!-- /skip-lint -->\n"
        "Tail prose with no offenders.\n"
    )
    stripped = _strip_skip_lint_regions(body)
    f1_regex: re.Pattern[str] = FORBIDDEN_PATTERNS["F1"]["regex"]  # type: ignore[assignment]
    # The marker only protects the wrapped span; the leading-line citation
    # remains visible to the regex (as it should — we want SKILLs to either
    # remove offenders entirely or wrap them explicitly).
    matches = f1_regex.findall(stripped)
    assert len(matches) == 1, (
        f"skip-lint should strip exactly one citation; got {matches!r}. "
        f"Either the regex is wrong or _strip_skip_lint_regions is broken."
    )
