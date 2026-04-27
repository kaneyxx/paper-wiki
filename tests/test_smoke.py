"""Smoke tests for paper-wiki Phase 0 scaffolding.

These tests verify the plugin manifest, marketplace listing, hooks
configuration, baseline SKILL, slash command, and Python package basics
are all present and structurally sound. They are the absolute minimum
that must pass before any feature work begins.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Python package
# ---------------------------------------------------------------------------


def test_version_string_is_semver_like() -> None:
    """``paperwiki.__version__`` exists and looks like SemVer."""
    from paperwiki import __version__

    assert re.match(r"^\d+\.\d+\.\d+(?:[-+].+)?$", __version__), __version__


# ---------------------------------------------------------------------------
# Plugin manifest
# ---------------------------------------------------------------------------


def test_plugin_manifest_is_valid_json() -> None:
    """``.claude-plugin/plugin.json`` is parseable and well-formed."""
    manifest = REPO_ROOT / ".claude-plugin" / "plugin.json"
    assert manifest.is_file(), manifest

    data = json.loads(manifest.read_text(encoding="utf-8"))

    assert data["name"] == "paper-wiki"
    assert data["version"] == "0.3.8"
    assert data["license"] == "GPL-3.0"
    assert data["commands"] == "./.claude/commands"
    assert data["repository"].endswith("/paper-wiki")
    assert data["homepage"].endswith("/paper-wiki")


def test_marketplace_manifest_lists_paper_wiki() -> None:
    """``.claude-plugin/marketplace.json`` exposes paper-wiki as an installable plugin."""
    manifest = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    assert manifest.is_file(), manifest

    data = json.loads(manifest.read_text(encoding="utf-8"))

    plugins = data["plugins"]
    assert isinstance(plugins, list), "plugins must be a list"
    assert plugins, "plugins list must be non-empty"

    names = [p["name"] for p in plugins]
    assert "paper-wiki" in names

    paper_wiki = next(p for p in plugins if p["name"] == "paper-wiki")
    assert paper_wiki["source"]["source"] == "github"
    assert paper_wiki["source"]["repo"] == "kaneyxx/paper-wiki"


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def test_hooks_register_session_start() -> None:
    """``hooks/hooks.json`` declares a SessionStart hook for venv bootstrap."""
    manifest = REPO_ROOT / "hooks" / "hooks.json"
    assert manifest.is_file(), manifest

    data = json.loads(manifest.read_text(encoding="utf-8"))

    session_starts = data["hooks"]["SessionStart"]
    assert session_starts, "SessionStart must declare at least one hook"

    first = session_starts[0]["hooks"][0]
    assert first["type"] == "command"
    assert "${CLAUDE_PLUGIN_ROOT}" in first["command"]
    assert "ensure-env.sh" in first["command"]


def test_ensure_env_script_is_executable() -> None:
    """``hooks/ensure-env.sh`` exists, is executable on POSIX, and references uv."""
    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    assert script.is_file(), script

    if os.name == "posix":
        assert os.access(script, os.X_OK), "ensure-env.sh must be executable on POSIX"

    body = script.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body
    assert "CLAUDE_PLUGIN_ROOT" in body
    # Must prefer uv but fall back to stdlib venv.
    assert "uv venv" in body
    assert "python3 -m venv" in body


# ---------------------------------------------------------------------------
# SKILL & slash command
# ---------------------------------------------------------------------------


SKILL_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Parse a Markdown file's YAML-style frontmatter into a flat dict."""
    text = path.read_text(encoding="utf-8")
    match = SKILL_FRONTMATTER_RE.match(text)
    assert match, f"{path} is missing frontmatter"

    body = match.group(1)
    fields: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in body.splitlines():
        if not raw_line.strip():
            continue
        if raw_line.startswith(" ") and current_key:
            fields[current_key] += " " + raw_line.strip()
            continue
        key, _, value = raw_line.partition(":")
        current_key = key.strip()
        fields[current_key] = value.strip()
    return fields


_ALL_SKILLS = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
_ALL_SLASH_COMMANDS = sorted((REPO_ROOT / ".claude" / "commands").glob("*.md"))


@pytest.mark.parametrize("skill_path", _ALL_SKILLS, ids=lambda p: p.parent.name)
def test_skill_has_required_frontmatter(skill_path: Path) -> None:
    """Every ``skills/<name>/SKILL.md`` declares ``name`` + ``description``."""
    fields = _read_frontmatter(skill_path)

    assert fields.get("name") == skill_path.parent.name, (
        f"frontmatter name must match directory: {skill_path}"
    )
    assert fields.get("description"), f"description is required: {skill_path}"
    assert "Use when" in fields["description"], (
        f"description must list trigger conditions: {skill_path}"
    )


@pytest.mark.parametrize("skill_path", _ALL_SKILLS, ids=lambda p: p.parent.name)
def test_skill_has_six_section_anatomy(skill_path: Path) -> None:
    """Every SKILL follows the six-section anatomy from SPEC.md §4."""
    body = skill_path.read_text(encoding="utf-8")

    required_sections = (
        "## Overview",
        "## When to Use",
        "## Process",
        "## Common Rationalizations",
        "## Red Flags",
        "## Verification",
    )
    for section in required_sections:
        assert section in body, f"missing section {section!r}: {skill_path}"


@pytest.mark.parametrize("cmd_path", _ALL_SLASH_COMMANDS, ids=lambda p: p.stem)
def test_slash_command_has_description(cmd_path: Path) -> None:
    """Every ``.claude/commands/<name>.md`` declares ``description``."""
    fields = _read_frontmatter(cmd_path)
    assert fields.get("description"), f"slash command must have a description: {cmd_path}"


# ---------------------------------------------------------------------------
# SKILL content invariants (Phase 6.3 — wiki integration)
# ---------------------------------------------------------------------------


def test_digest_skill_describes_auto_ingest_top_chaining() -> None:
    """When ``auto_ingest_top`` is set, the digest SKILL must auto-chain
    ``/paper-wiki:wiki-ingest`` for the top-N papers — pin the contract."""
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    assert "auto_ingest_top" in body, "digest SKILL must reference the auto_ingest_top recipe field"
    assert "/paper-wiki:wiki-ingest" in body, (
        "digest SKILL must call out the chained wiki-ingest invocation"
    )


def test_digest_skill_resolves_personal_recipes_and_sources_secrets() -> None:
    """Daily flow ergonomics: SKILL must look in ~/.config/paper-wiki/recipes
    first and source ~/.config/paper-wiki/secrets.env before the runner."""
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    assert "~/.config/paper-wiki/recipes" in body, (
        "digest SKILL must check the personal-recipes dir before bundled templates"
    )
    assert "~/.config/paper-wiki/secrets.env" in body, (
        "digest SKILL must source the secrets file so api_key_env resolves"
    )


def test_bundled_assets_are_english_only() -> None:
    """Per project rule: bundled SKILLs / recipes / docs ship English-only.

    Chinese (and other CJK) examples belong under ``locales/zh/`` (TBD),
    never inlined in trigger phrases or prompt copy. This guard catches
    accidental leaks during development. Code blocks and the user's
    ``~/.config/paper-wiki/`` files are out of scope — the rule is for
    things that ship in the plugin tarball.
    """
    cjk = re.compile(r"[　-〿一-鿿＀-￯]")
    bundled_roots = ("src", "skills", "recipes", "docs")
    bundled_files = ("README.md", "SPEC.md", "CLAUDE.md", "AGENTS.md")
    suffixes = {".py", ".md", ".yaml", ".yml", ".toml"}

    leaks: list[tuple[str, str]] = []
    for root_name in bundled_roots:
        root = REPO_ROOT / root_name
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                text = path.read_text(encoding="utf-8")
                hits = cjk.findall(text)
                if hits:
                    leaks.append((str(path.relative_to(REPO_ROOT)), "".join(hits[:5])))
    for name in bundled_files:
        path = REPO_ROOT / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            hits = cjk.findall(text)
            if hits:
                leaks.append((name, "".join(hits[:5])))

    assert not leaks, "bundled assets must be English-only; CJK leaked in:\n  " + "\n  ".join(
        f"{p}: {sample!r}" for p, sample in leaks
    )


def test_setup_skill_walks_first_run_wizard() -> None:
    """First-run UX: the setup SKILL must lead users through a five-question
    wizard that produces a personal recipe + secrets file. Pin the contract
    so this UX cannot quietly regress to the env-check-only version."""
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    # The five wizard questions are visible in the SKILL.
    for marker in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        assert marker in body, f"setup SKILL must include wizard {marker}"
    # The two output files are named so the SKILL writes the right paths.
    assert "~/.config/paper-wiki/recipes/daily.yaml" in body, (
        "setup SKILL must write the personal recipe to the canonical path"
    )
    assert "~/.config/paper-wiki/secrets.env" in body, (
        "setup SKILL must store API keys in the gitignored secrets file"
    )
    # The auto-ingest knob is offered as a wizard question, not an
    # afterthought — it's the single biggest daily-experience lever.
    assert "auto_ingest_top" in body, (
        "setup SKILL's wizard must capture auto_ingest_top during onboarding"
    )


def test_setup_skill_invokes_askuserquestion_for_choice_points() -> None:
    """setup SKILL must use AskUserQuestion at every branch (>= 7 calls)."""
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    count = body.count("AskUserQuestion")
    assert count >= 7, (
        f"setup SKILL must call AskUserQuestion at least 7 times (found {count}); "
        "one per branch: already-configured, edit-one-piece, Q1 vault, Q2 topics, "
        "Q3 S2 key, Q4 auto-ingest, Q5 paperclip, final confirmation"
    )


def test_setup_skill_documents_branch_options_for_already_configured() -> None:
    """setup SKILL's already-configured branch must document all 4 options."""
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    for expected in (
        "Keep current config",
        "Reconfigure from scratch",
        "Edit one piece",
        "Cancel",
    ):
        assert expected in body, (
            f"setup SKILL already-configured branch must list option: {expected!r}"
        )


def test_analyze_skill_writes_to_sources_subdir() -> None:
    """The analyze SKILL must direct writes into the canonical ``Sources/``."""
    body = (REPO_ROOT / "skills" / "analyze" / "SKILL.md").read_text(encoding="utf-8")
    # The friendly default lives at the top level of the vault, not under
    # the legacy ``{paper_subdir}`` placeholder. Both forms are accepted.
    assert "Sources/" in body or "/Sources/" in body, (
        "analyze SKILL must reference the Sources/ subdir per Phase 6.1 layout"
    )
    # The legacy placeholder must be gone — it's misleading now.
    assert "{paper_subdir}" not in body, (
        "analyze SKILL still references the legacy {paper_subdir} placeholder"
    )


def test_analyze_skill_hands_off_to_wiki_ingest() -> None:
    """After writing the source, analyze must call /paper-wiki:wiki-ingest."""
    body = (REPO_ROOT / "skills" / "analyze" / "SKILL.md").read_text(encoding="utf-8")
    assert "/paper-wiki:wiki-ingest" in body, (
        "analyze SKILL must hand off to /paper-wiki:wiki-ingest after writing"
    )


# ---------------------------------------------------------------------------
# SKILL content invariants (Phase 7.1 — paperclip MCP wiring)
# ---------------------------------------------------------------------------


def test_setup_skill_surfaces_paperclip_mcp_status() -> None:
    """setup SKILL must consult diagnostics' mcp_servers for paperclip."""
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    assert "paperclip" in body, "setup SKILL must mention paperclip"
    assert "mcp_servers" in body, "setup SKILL must reference the diagnostics ``mcp_servers`` field"


def test_setup_skill_documents_registration_command_without_running() -> None:
    """setup SKILL must show the registration command but not auto-run it."""
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    # The command itself appears verbatim so users can copy it.
    assert "claude mcp add" in body, "setup SKILL must show the registration command"
    assert "paperclip.gxl.ai/mcp" in body, "setup SKILL must show the paperclip MCP URL"
    # Auth is sensitive — the SKILL must explicitly *not* run the command.
    assert "do not auto-run" in body.lower() or "without auto-running" in body.lower(), (
        "setup SKILL must explicitly not auto-run the registration command"
    )


def test_paperclip_setup_doc_exists() -> None:
    """docs/paperclip-setup.md walks users through MCP registration + auth."""
    doc = REPO_ROOT / "docs" / "paperclip-setup.md"
    assert doc.is_file(), "docs/paperclip-setup.md must exist"
    body = doc.read_text(encoding="utf-8")
    # The full registration command appears verbatim.
    assert "claude mcp add --transport http paperclip" in body
    assert "paperclip.gxl.ai/mcp" in body
    # Auth step + tier guidance are present (link to upstream, not duplicated).
    assert "paperclip login" in body
    assert "https://gxl.ai/blog/paperclip" in body or "paperclip.gxl.ai" in body
    # Stance: optional opt-in, never required.
    assert "optional" in body.lower()


def test_bio_search_skill_documents_mcp_dependency_and_fallback() -> None:
    """bio-search SKILL must explain the paperclip MCP requirement + fallback."""
    skill = REPO_ROOT / "skills" / "bio-search" / "SKILL.md"
    assert skill.is_file(), "skills/bio-search/SKILL.md must exist"
    body = skill.read_text(encoding="utf-8")
    # Trigger keywords: biomedical research vocabulary.
    assert "biomedical" in body.lower()
    assert "biorxiv" in body.lower() or "pubmed" in body.lower()
    # Hard dependency on paperclip MCP must be called out explicitly.
    assert "paperclip" in body.lower()
    assert "mcp" in body.lower()
    # Graceful fallback when paperclip MCP isn't registered.
    assert "docs/paperclip-setup.md" in body or "/paper-wiki:setup" in body, (
        "bio-search SKILL must point users at setup docs when MCP is missing"
    )


def test_bio_search_slash_command_exists() -> None:
    """`.claude/commands/bio-search.md` registers the slash command."""
    cmd = REPO_ROOT / ".claude" / "commands" / "bio-search.md"
    assert cmd.is_file(), ".claude/commands/bio-search.md must exist"


def test_readme_documents_bio_search_as_optional() -> None:
    """README must surface bio-search in Quick Start as an optional advanced feature."""
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "/paper-wiki:bio-search" in body, (
        "README must list /paper-wiki:bio-search in Quick Start"
    )
    # Position it as optional / opt-in rather than a default surface.
    assert "paperclip" in body, "README must mention paperclip dependency"
    assert "optional" in body.lower(), (
        "README must position bio-search as optional, not a default surface"
    )


def test_readme_lists_all_shipped_skills() -> None:
    """Every SKILL under skills/ must be documented in README."""
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for skill_dir in (REPO_ROOT / "skills").iterdir():
        if not skill_dir.is_dir():
            continue
        slash_command = f"/paper-wiki:{skill_dir.name}"
        assert slash_command in body, f"README must document the {slash_command} SKILL"


def test_readme_uses_correct_slash_command_namespace() -> None:
    """README must use /paper-wiki: namespace throughout — never /paperwiki:."""
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    import re

    stale = re.findall(r"/paperwiki:\w+", body)
    assert not stale, (
        f"README contains {len(stale)} stale /paperwiki: reference(s); "
        f"all must use /paper-wiki: instead. Found: {stale}"
    )


def test_readme_documents_s2_api_key_setup() -> None:
    """S2 API-key indirection is the most common first-run friction."""
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "PAPERWIKI_S2_API_KEY" in body, "README must document the S2 API key env var name"
    assert "api_key_env" in body, "README must show the recipe-side indirection"
    assert "secrets.env" in body or "secrets.toml" in body, (
        "README must point users at a secure storage location for the key"
    )


def test_readme_documents_personal_recipe_directory() -> None:
    """Users need to know recipes ship as templates and personal recipes live elsewhere."""
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "~/.config/paper-wiki" in body, (
        "README must point users at the personal recipe / config dir"
    )


# ---------------------------------------------------------------------------
# Top-level project files
# ---------------------------------------------------------------------------


def test_pyproject_declares_paper_wiki() -> None:
    """``pyproject.toml`` exists and declares the project as ``paper-wiki``."""
    pyproject = REPO_ROOT / "pyproject.toml"
    assert pyproject.is_file()

    body = pyproject.read_text(encoding="utf-8")
    assert 'name = "paper-wiki"' in body
    assert 'requires-python = ">=3.11"' in body
    # Must NOT depend on forbidden libs.
    for forbidden in ("requests", "argparse"):
        # crude check — we accept the word inside docstrings/comments only via
        # an explicit dependency declaration line check instead.
        assert f'"{forbidden}>=' not in body
        assert f'"{forbidden}=' not in body


def test_required_top_level_files_exist() -> None:
    """Phase 0 deliverables are all present in the repo root."""
    expected = [
        "LICENSE",
        "README.md",
        "SPEC.md",
        "CLAUDE.md",
        "AGENTS.md",
        "CITATION.cff",
        "pyproject.toml",
        ".gitignore",
    ]
    for name in expected:
        path = REPO_ROOT / name
        assert path.is_file(), f"missing top-level file: {name}"


# ---------------------------------------------------------------------------
# AskUserQuestion schema compliance (v0.3.4)
# ---------------------------------------------------------------------------


def test_setup_skill_specifies_header_for_every_askuserquestion() -> None:
    """Every AskUserQuestion call in the setup SKILL must specify a header field.

    The header field is REQUIRED by the AskUserQuestion schema (max 12 chars).
    Omitting it causes Claude Code to truncate the question text into a garbage
    chip label (e.g. "Custom kw"). We pin at least 8 occurrences — one per branch.
    """
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    header_count = body.count("header:")
    assert header_count >= 8, (
        f"setup SKILL must specify 'header:' at least 8 times (one per branch), "
        f"found {header_count}. Missing header causes garbage chip labels in the UI."
    )


def test_setup_skill_uses_multiselect_for_topics() -> None:
    """The topics question (Q2/Branch 4) must use multiSelect: true.

    Using repeated single-select prompts to fake multi-select violates the
    AskUserQuestion API. The correct approach is multiSelect: true so users
    can select multiple themes in a single interaction.
    """
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    # Verify multiSelect: true appears in the SKILL (topics question)
    assert "multiSelect: true" in body, (
        "setup SKILL must use 'multiSelect: true' for the topics question (Q2/Branch 4); "
        "re-prompting until 'Done' fakes multi-select and violates the schema."
    )
    # Verify the topics section specifically contains multiSelect: true
    # by checking that it appears near the Topics / Q2 context
    topics_section_start = body.find("Q2")
    topics_section_end = body.find("Q3", topics_section_start)
    topics_section = body[topics_section_start:topics_section_end]
    assert "multiSelect: true" in topics_section, (
        "setup SKILL's Q2 (topics) section must specify 'multiSelect: true'; "
        "found it elsewhere but not in the topics branch."
    )


def test_setup_skill_does_not_add_manual_other_or_cancel() -> None:
    """setup SKILL must NOT manually add 'Other' or 'Cancel' options.

    The AskUserQuestion schema documentation states: 'There should be no Other
    option, that will be provided automatically' and Cancel is similarly
    auto-provided. Manually adding these produces duplicate options and schema
    violations that cause UI bugs.
    """
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")

    # Check for manual "Other (specify..." option labels — the old pattern
    assert "Other (specify" not in body, (
        "setup SKILL must NOT add a manual 'Other (specify...)' option; "
        "Claude Code injects 'Other' automatically per the AskUserQuestion schema."
    )

    # Check that no option label is literally just "Cancel" — it should not
    # appear as a label value in option definitions. Prose mentions of the word
    # "Cancel" (describing auto-provided behavior) are fine.
    # We look for the pattern used in option definitions: 'label: "Cancel"'
    import re

    cancel_label_pattern = re.compile(r'label:\s*["\']?Cancel["\']?', re.IGNORECASE)
    assert not cancel_label_pattern.search(body), (
        "setup SKILL must NOT add a manual Cancel option label in AskUserQuestion calls; "
        "Claude Code injects Cancel automatically."
    )


# ---------------------------------------------------------------------------
# Namespace regression (9.6)
# ---------------------------------------------------------------------------


def test_no_stale_paperwiki_namespace() -> None:
    """No file in src/, skills/, recipes/, docs/, SPEC.md, or .claude/commands/
    may contain the legacy ``/paperwiki:`` prefix.

    The correct namespace is ``/paper-wiki:`` (with a hyphen). The stale form
    fails at runtime because the Claude Code plugin is registered as
    ``paper-wiki``, not ``paperwiki``.

    CHANGELOG.md is exempt — historical entries describe old reality.
    tests/test_smoke.py is exempt — this test necessarily references the
    bad pattern as a literal string.
    tasks/ is exempt — plan files rewrite the namespace as part of editing
    history.
    .claude/worktrees/ is exempt — sandboxed worktrees may have stale state
    during active development.
    """
    import re

    bad_pattern = re.compile(r"/paperwiki:\w+")

    scan_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "skills",
        REPO_ROOT / "recipes",
        REPO_ROOT / "docs",
        REPO_ROOT / "SPEC.md",
        REPO_ROOT / ".claude" / "commands",
    ]

    skip_dirs = {".venv", "node_modules", "__pycache__", ".git", "worktrees"}

    hits: list[str] = []
    for root in scan_roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))

        for path in paths:
            # Skip non-files and directories we should not descend into
            if not path.is_file():
                continue
            # Skip any path component that is an excluded dir
            if any(part in skip_dirs for part in path.parts):
                continue
            # Skip this test file itself (it references the bad pattern as a literal)
            if path.resolve() == Path(__file__).resolve():
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for lineno, line in enumerate(text.splitlines(), start=1):
                if bad_pattern.search(line):
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not hits, (
        f"Found {len(hits)} stale /paperwiki: reference(s) — use /paper-wiki: instead.\n"
        + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# Task 9.7 — auto-bootstrap mode (v0.3.7)
# ---------------------------------------------------------------------------


def test_wiki_ingest_skill_describes_auto_bootstrap_mode() -> None:
    """wiki-ingest SKILL.md must document the --auto-bootstrap flag, the
    auto_created: true frontmatter sentinel, the sentinel body string, and
    the stub-then-update two-step flow."""
    body = (REPO_ROOT / "skills" / "wiki-ingest" / "SKILL.md").read_text(encoding="utf-8")

    assert "--auto-bootstrap" in body, "wiki-ingest SKILL.md must mention the --auto-bootstrap flag"
    assert "auto_created: true" in body, (
        "wiki-ingest SKILL.md must document the auto_created: true frontmatter sentinel"
    )
    assert "Auto-created during digest auto-ingest" in body, (
        "wiki-ingest SKILL.md must include the sentinel body string "
        "'Auto-created during digest auto-ingest'"
    )
    # Verify the two-step stub-then-update flow is documented
    assert "stub" in body.lower(), (
        "wiki-ingest SKILL.md must describe the stub step in the two-step flow"
    )
    assert "update" in body.lower(), (
        "wiki-ingest SKILL.md must describe the update step in the two-step flow"
    )


def test_digest_skill_passes_auto_bootstrap_to_wiki_ingest() -> None:
    """digest SKILL.md Process step 7 (auto-chain wiki-ingest) must pass
    --auto-bootstrap when invoking /paper-wiki:wiki-ingest."""
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")

    assert "--auto-bootstrap" in body, (
        "digest SKILL.md must mention --auto-bootstrap near the auto-chained "
        "/paper-wiki:wiki-ingest invocation"
    )
    # Both the flag and the command should appear in the same document
    assert "/paper-wiki:wiki-ingest" in body, (
        "digest SKILL.md must reference /paper-wiki:wiki-ingest"
    )


def test_wiki_lint_skill_surfaces_auto_created_stubs() -> None:
    """wiki-lint SKILL.md must mention auto_created: true and a dedicated
    'Needs review' bucket / category for auto-created stubs."""
    body = (REPO_ROOT / "skills" / "wiki-lint" / "SKILL.md").read_text(encoding="utf-8")

    assert "auto_created: true" in body, (
        "wiki-lint SKILL.md must mention the auto_created: true frontmatter sentinel"
    )
    assert "needs review" in body.lower(), (
        "wiki-lint SKILL.md must describe a 'Needs review' bucket for auto-created stubs"
    )


# ---------------------------------------------------------------------------
# Task 9.3 — Today's Overview synthesis (v0.3.7)
# ---------------------------------------------------------------------------


def test_digest_skill_describes_overview_synthesis() -> None:
    """digest SKILL.md must document the Today's Overview synthesis step with:
    - reference to the overview-slot marker
    - Today's Overview callout context
    - instruction to read the digest file from disk
    - instruction to write back (replace the marker)
    - #N cite-marker requirement
    - 60-200 word target length
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")

    assert "paper-wiki:overview-slot" in body, (
        "digest SKILL.md must reference the 'paper-wiki:overview-slot' marker "
        "(the slot to replace in the Today's Overview callout)"
    )
    assert "Today's Overview" in body, (
        "digest SKILL.md must mention 'Today's Overview' callout context"
    )
    # Must instruct to read the digest file after the runner finishes
    assert "read" in body.lower(), (
        "digest SKILL.md must instruct to read the digest file from disk after the runner finishes"
    )
    # Must instruct to write back / replace the marker
    assert "replace" in body.lower(), (
        "digest SKILL.md must instruct to replace the marker with synthesized prose"
    )
    assert "#N" in body, (
        "digest SKILL.md must document the #N cite-marker requirement (every claim cites a paper)"
    )
    # Check for 60-200 word target length
    assert "60" in body, (
        "digest SKILL.md must specify the 60-word minimum target length for the overview"
    )
    assert "200" in body, (
        "digest SKILL.md must specify the 200-word maximum target length for the overview"
    )


# ---------------------------------------------------------------------------
# Task 9.8 — Standard upgrade flow (OMC-style, v0.3.8)
# ---------------------------------------------------------------------------


def test_plugin_manifest_declares_skills_directory() -> None:
    """``plugin.json`` must declare the ``"skills"`` field pointing to ``./skills/``.

    Without this declaration the Claude Code plugin loader cannot locate SKILL
    files after install, causing the "already installed globally but Unknown
    command" failure mode. OMC's plugin.json carries this field; paper-wiki
    must too.
    """
    manifest = REPO_ROOT / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))

    assert "skills" in data, (
        "plugin.json must have a 'skills' field so Claude Code can locate SKILL files. "
        "Without it, /plugin install leaves metadata in an inconsistent state."
    )
    skills_value: str = data["skills"]
    assert skills_value.startswith("./skills"), (
        f"plugin.json 'skills' must point at the ./skills/ directory, got: {skills_value!r}"
    )


def test_readme_documents_standard_upgrade_flow() -> None:
    """README must document the standard /plugin uninstall + /plugin install upgrade flow.

    Users need to know the canonical upgrade path (uninstall + reinstall + fresh session)
    and must be warned not to use ``claude -c`` after an upgrade.
    """
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "/plugin uninstall paper-wiki@paper-wiki" in body, (
        "README must document '/plugin uninstall paper-wiki@paper-wiki' as part of the "
        "standard upgrade flow"
    )
    assert "/plugin install paper-wiki@paper-wiki" in body, (
        "README must document '/plugin install paper-wiki@paper-wiki' as part of the "
        "standard upgrade flow"
    )
    assert "claude -c" in body, (
        "README must warn users not to use 'claude -c' after an upgrade — "
        "SKILL changes only take effect in fresh sessions"
    )


def test_readme_does_not_recommend_manual_cache_nuke() -> None:
    """README must not tell users to ``rm -rf`` the plugin cache as a normal upgrade step.

    The ``rm -rf`` cache instructions were a workaround for the missing
    ``"skills"`` declaration in plugin.json (fixed in v0.3.8). They should not
    appear in user-facing docs as part of the primary upgrade flow.
    """
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    # The combination of rm -rf and a cache/paper-wiki path is the red flag.
    # A bare mention of rm -rf for other purposes (e.g. vault pruning) is fine.
    import re

    cache_nuke_pattern = re.compile(r"rm\s+-rf.*cache[/\\]paper-wiki", re.IGNORECASE)
    assert not cache_nuke_pattern.search(body), (
        "README must not tell users to 'rm -rf' the plugin cache as part of the "
        "upgrade flow — use '/plugin uninstall' + '/plugin install' instead. "
        "The rm -rf instructions were a workaround for the missing 'skills' "
        "declaration in plugin.json (fixed in v0.3.8)."
    )
