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
    assert data["version"] == "0.3.29"
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


def test_wiki_ingest_skill_appends_auto_bootstrap_flag_to_runner_cli() -> None:
    """When wiki-ingest is invoked with --auto-bootstrap, Step 2 must
    instruct the LLM to append the flag to the runner CLI invocation —
    otherwise the flag is dropped between SKILL hop-levels and the
    runner doesn't bootstrap (regression seen in v0.3.10 smoke)."""
    body = (REPO_ROOT / "skills" / "wiki-ingest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())
    assert "<canonical-id> --auto-bootstrap" in flat, (
        "wiki-ingest SKILL Step 2 must show the runner CLI with --auto-bootstrap appended"
    )
    assert "append it to this CLI invocation" in flat, (
        "wiki-ingest SKILL Step 2 must explicitly tell the LLM to append the flag"
    )


def test_wiki_ingest_skill_forbids_inline_python_fallback() -> None:
    """The runner now handles bootstrap natively (v0.3.9). Step 5 must
    explicitly forbid inline Python (<<PYEOF, python -c) as a manual
    fallback — that was v0.3.7 black-magic the runner replaces."""
    body = (REPO_ROOT / "skills" / "wiki-ingest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())
    assert "Do NOT write any inline Python" in flat, (
        "wiki-ingest SKILL must explicitly forbid inline Python fallback in Step 5"
    )
    assert "PYEOF" in flat, (
        "wiki-ingest SKILL must name the specific anti-pattern (<<PYEOF / python -c)"
    )


def test_digest_skill_forbids_asking_before_auto_chain() -> None:
    """``auto_ingest_top: N`` is the user's pre-approval — the SKILL must
    fire the chain immediately, not prompt 'shall I chain?' or 'want me to
    ingest?'. Pins this against LLM caution drift."""
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    # Markdown line-wraps may insert whitespace mid-phrase; collapse to be robust.
    flat = " ".join(body.split())
    assert "without asking the user" in flat, (
        "digest SKILL must explicitly tell the LLM not to prompt before auto-chain"
    )
    assert "pre-approval" in flat, (
        "digest SKILL must frame auto_ingest_top as user pre-approval, "
        "not a hint that the LLM should re-confirm"
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


# ---------------------------------------------------------------------------
# Task 9.16 — wiki-ingest SKILL auto-chain uses only runner (v0.3.13)
# ---------------------------------------------------------------------------


def test_wiki_ingest_skill_auto_chain_path_uses_only_runner() -> None:
    """Auto-bootstrap path must NOT Read or Edit concept files — the runner
    now folds citations atomically. Pin three invariants in SKILL.md so the
    4-minute-hang regression cannot resurface."""
    body = (REPO_ROOT / "skills" / "wiki-ingest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    assert "Do NOT Read or Edit those concept files yourself" in flat, (
        "wiki-ingest SKILL Step 4 must tell the LLM not to Read or Edit concept files "
        "when in auto-bootstrap mode — the runner already did it"
    )
    assert "the runner did it" in flat, (
        "wiki-ingest SKILL Step 4 must state 'the runner did it' so the LLM "
        "doesn't re-do the citation folding via Edit calls"
    )
    assert "folded_citations" in body, (
        "wiki-ingest SKILL must reference the 'folded_citations' JSON field "
        "so the LLM knows which field to read from runner output"
    )


# ---------------------------------------------------------------------------
# Task 9.4 — Per-paper Detailed report synthesis (v0.3.16)
# ---------------------------------------------------------------------------


def test_digest_skill_describes_per_paper_synthesis() -> None:
    """digest SKILL.md must document per-paper Detailed report synthesis:
    - reference the per-paper-slot marker
    - mention 'Detailed report'
    - NOT refer to /paper-wiki:analyze as a fallback for per-paper synthesis
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")

    assert "paper-wiki:per-paper-slot" in body, (
        "digest SKILL.md must reference the 'paper-wiki:per-paper-slot' marker "
        "used to anchor per-paper synthesized sections"
    )
    assert "Detailed report" in body, (
        "digest SKILL.md must mention 'Detailed report' as the synthesized section type"
    )
    # The SKILL must not rely on /paper-wiki:analyze as a per-paper fallback
    # (that's a different flow for single-paper deep dives)
    assert (
        "analyze" not in body.lower().split("suggest")[-1]
        or "/paper-wiki:analyze" not in body[: body.lower().find("per-paper-slot")]
    ), "digest SKILL.md must not use /paper-wiki:analyze as a fallback for per-paper synthesis"


# ---------------------------------------------------------------------------
# Task 9.5 — Auto image extraction for auto_ingest_top papers (v0.3.16)
# ---------------------------------------------------------------------------


def test_digest_skill_chains_extract_images() -> None:
    """digest SKILL.md must document both extract-images AND wiki-ingest in the
    auto-chain step, with extract-images appearing BEFORE wiki-ingest."""
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")

    assert "extract-images" in body or "extract_paper_images" in body, (
        "digest SKILL.md must mention extract-images in the auto-chain step"
    )
    assert "/paper-wiki:wiki-ingest" in body or "wiki-ingest" in body, (
        "digest SKILL.md must mention wiki-ingest in the auto-chain step"
    )

    # Extract-images must appear BEFORE wiki-ingest in the document
    extract_pos = body.find("extract-images")
    if extract_pos == -1:
        extract_pos = body.find("extract_paper_images")
    ingest_pos = body.find("wiki-ingest")
    assert extract_pos < ingest_pos, (
        "In digest SKILL.md, extract-images must appear BEFORE wiki-ingest "
        "in the auto-chain step — figures must be on disk before ingest runs"
    )


# ---------------------------------------------------------------------------
# Task 9.21 — Personal recipe migration (v0.3.23)
# ---------------------------------------------------------------------------


def test_migrate_recipe_skill_anatomy() -> None:
    """skills/migrate-recipe/SKILL.md must exist and follow six-section anatomy."""
    skill = REPO_ROOT / "skills" / "migrate-recipe" / "SKILL.md"
    assert skill.is_file(), "skills/migrate-recipe/SKILL.md must exist"
    body = skill.read_text(encoding="utf-8")

    for section in (
        "## Overview",
        "## When to Use",
        "## Process",
        "## Common Rationalizations",
        "## Red Flags",
        "## Verification",
    ):
        assert section in body, f"migrate-recipe SKILL.md must contain section {section!r}"

    # Must mention AskUserQuestion and dry-run
    flat = " ".join(body.split())
    assert "AskUserQuestion" in flat, (
        "migrate-recipe SKILL must use AskUserQuestion for confirmation"
    )
    assert "--dry-run" in flat, "migrate-recipe SKILL must show --dry-run flag"
    assert "backup" in flat.lower(), "migrate-recipe SKILL must mention backup file"


def test_migrate_recipe_slash_command_exists() -> None:
    """.claude/commands/migrate-recipe.md must exist."""
    cmd = REPO_ROOT / ".claude" / "commands" / "migrate-recipe.md"
    assert cmd.is_file(), ".claude/commands/migrate-recipe.md must exist"


def test_setup_skill_offers_migration_when_recipe_is_stale() -> None:
    """setup SKILL Branch 1 ('Keep current config') must offer a migration option
    when stale keywords are detected (e.g. 'foundation model' in biomedical-pathology)."""
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    assert "migration heuristic" in flat or "migrate" in flat.lower(), (
        "setup SKILL Branch 1 must mention migration when recipe is stale"
    )
    assert "foundation model" in flat, (
        "setup SKILL Branch 1 migration check must specifically mention 'foundation model' "
        "as the stale-marker keyword"
    )
    assert "biomedical-pathology" in flat, (
        "setup SKILL Branch 1 migration check must reference 'biomedical-pathology' topic"
    )
    assert "/paper-wiki:migrate-recipe" in flat, (
        "setup SKILL Branch 1 must hand off to /paper-wiki:migrate-recipe when migration chosen"
    )


# ---------------------------------------------------------------------------
# Task 9.23 — Interpretive Score reasoning (v0.3.23)
# ---------------------------------------------------------------------------


def test_digest_skill_score_reasoning_is_interpretive_not_transcriptive() -> None:
    """digest SKILL.md Process Step 8 'Score reasoning' contract must require
    1-2 interpretive sentences (not sub-score transcription), be GROUNDED in
    sub-scores, and explicitly forbid the number-restating pattern."""
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    # 1-2 sentences requirement
    # The SKILL uses an en-dash in "1-2 sentences maximum"; check for
    # the "sentences maximum" phrase which is robust to the dash variant.
    assert "sentences maximum" in flat, (
        "digest SKILL.md Score reasoning must specify a '...sentences maximum' sentence-count limit"
    )
    # Interpretive requirement
    assert "interpret" in flat.lower(), (
        "digest SKILL.md Score reasoning must say 'interpret' — not just transcribe"
    )
    # GROUNDED requirement
    assert "GROUNDED" in body or "grounded" in body.lower(), (
        "digest SKILL.md Score reasoning must require interpretation to be "
        "GROUNDED in the actual sub-score numbers"
    )
    # Forbidden transcription pattern explicitly called out
    assert "Forbidden pattern" in body or "transcription" in flat.lower(), (
        "digest SKILL.md must explicitly call out the forbidden sub-score "
        "transcription pattern (e.g. '0.79 — relevance 0.99, novelty 0.98...')"
    )
    # Red Flag row for score reasoning
    red_flags_start = body.find("## Red Flags")
    assert red_flags_start != -1, "digest SKILL.md must have Red Flags section"
    red_flags_body = body[red_flags_start:]
    assert "Score reasoning" in red_flags_body or "sub-scores" in red_flags_body, (
        "digest SKILL.md Red Flags must warn against Score reasoning that only "
        "restates the four sub-scores"
    )
    assert "STOP" in red_flags_body, (
        "digest SKILL.md Red Flags must use STOP as an explicit halt signal for "
        "Score reasoning transcription"
    )


# ---------------------------------------------------------------------------
# Task 9.20 — extract-images failure UX (v0.3.23)
# ---------------------------------------------------------------------------


def test_digest_skill_emits_extract_images_summary() -> None:
    """digest SKILL.md Process Step 7a must document the per-paper summary block
    with all four outcome classifications and the four-line format."""
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    # Four outcome classifications must all be present
    assert "success-with-figures" in flat, (
        "digest SKILL.md must document success-with-figures classification"
    )
    assert "success-no-figures" in flat, (
        "digest SKILL.md must document success-no-figures classification"
    )
    assert "skipped-non-arxiv" in flat, (
        "digest SKILL.md must document skipped-non-arxiv classification"
    )
    assert "failed-with-error" in flat, (
        "digest SKILL.md must document failed-with-error classification"
    )
    # The per-paper format: "Image extraction:" header
    assert "Image extraction:" in body, (
        "digest SKILL.md must show the 'Image extraction:' summary block header"
    )
    # The rationalization forbidding silent skip of summary
    assert "confidence signal" in flat, (
        "digest SKILL.md Common Rationalizations must mention 'confidence signal' "
        "to forbid skipping the summary when all extractions succeed"
    )
    # Verification section must reference the summary block
    assert "per-paper summary block" in flat, (
        "digest SKILL.md Verification must mention 'per-paper summary block'"
    )


# ---------------------------------------------------------------------------
# Task 9.9 — concept-matching threshold (v0.3.17)
# ---------------------------------------------------------------------------


def test_composite_scorer_emits_per_topic_strengths() -> None:
    """CompositeScorer.score() must populate ScoreBreakdown.notes['topic_strengths']
    as a JSON-encoded dict[str, float] keyed by topic name."""
    import asyncio
    import json
    from datetime import UTC, datetime

    from paperwiki.core.models import Author, Paper, RunContext, ScoreBreakdown
    from paperwiki.plugins.filters.relevance import Topic
    from paperwiki.plugins.scorers.composite import CompositeScorer

    scorer = CompositeScorer(
        topics=[
            Topic(name="pathology", keywords=["pathology", "histopathology"]),
            Topic(name="unrelated", keywords=["zzz_xyzzy_never"]),
        ]
    )
    paper = Paper(
        canonical_id="arxiv:0001.0001",
        title="Deep learning for pathology histopathology",
        authors=[Author(name="A. B.")],
        abstract="We study histopathology slides.",
        published_at=datetime(2026, 4, 20, tzinfo=UTC),
        categories=["cs.CV"],
    )
    ctx = RunContext(target_date=datetime(2026, 4, 25, tzinfo=UTC), config_snapshot={})

    async def _run() -> ScoreBreakdown:
        return (
            await asyncio.wait_for(
                (scorer.score(_aiter([paper]), ctx).__anext__()),
                timeout=5,
            )
        ).score

    async def _aiter(items):  # type: ignore[no-untyped-def]
        for item in items:
            yield item

    score = asyncio.run(_run())
    assert score.notes is not None
    assert "topic_strengths" in score.notes
    strengths = json.loads(score.notes["topic_strengths"])
    assert isinstance(strengths, dict)
    assert strengths.get("pathology", 0.0) > 0.0
    assert strengths.get("unrelated", 0.0) == 0.0


def test_wiki_upsert_source_filters_by_topic_strength() -> None:
    """MarkdownWikiBackend.upsert_paper(topic_strength_threshold=0.5) must exclude
    topics whose per-topic strength is below the threshold."""
    import asyncio
    import json
    import tempfile
    from datetime import UTC, datetime
    from pathlib import Path

    import yaml

    from paperwiki.core.models import Author, Paper, Recommendation, ScoreBreakdown
    from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

    rec = Recommendation(
        paper=Paper(
            canonical_id="arxiv:0001.9999",
            title="Test Paper",
            authors=[Author(name="T. Tester")],
            abstract="Abstract.",
            published_at=datetime(2026, 4, 20, tzinfo=UTC),
            categories=["cs.CV"],
        ),
        score=ScoreBreakdown(
            relevance=0.8,
            novelty=0.5,
            momentum=0.3,
            rigor=0.4,
            composite=0.55,
            notes={"topic_strengths": json.dumps({"strong": 0.9, "weak": 0.1})},
        ),
        matched_topics=["strong", "weak"],
    )

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        backend = MarkdownWikiBackend(vault_path=vault)
        asyncio.run(backend.upsert_paper(rec, topic_strength_threshold=0.5))

        path = vault / "Wiki" / "sources" / "arxiv_0001.9999.md"
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        end = text.find("\n---\n", 4)
        fm = yaml.safe_load(text[4:end])
        related = fm.get("related_concepts", [])
        assert any("strong" in s for s in related), "strong topic must appear in related_concepts"
        assert not any("weak" in s for s in related), "weak topic must be filtered out"


# ---------------------------------------------------------------------------
# Task 9.12 — auto-stub UX (v0.3.17)
# ---------------------------------------------------------------------------


def test_wiki_ingest_sentinel_body_explains_next_step() -> None:
    """AUTO_CREATED_SENTINEL_BODY must mention /paper-wiki:wiki-ingest as the
    next step to fill the stub — not just lint."""
    from paperwiki.runners._stub_constants import AUTO_CREATED_SENTINEL_BODY

    assert "/paper-wiki:wiki-ingest" in AUTO_CREATED_SENTINEL_BODY, (
        "AUTO_CREATED_SENTINEL_BODY must reference /paper-wiki:wiki-ingest "
        "so users know what to run next after seeing a stub"
    )
    assert "intentionally empty" in AUTO_CREATED_SENTINEL_BODY, (
        "AUTO_CREATED_SENTINEL_BODY must say 'intentionally empty' so users "
        "understand the stub is a placeholder, not an error"
    )


def test_wiki_lint_explains_auto_stub_intent() -> None:
    """wiki-lint SKILL Process Step 2 must explain stubs are intentionally
    empty until /paper-wiki:wiki-ingest is run."""
    body = (REPO_ROOT / "skills" / "wiki-lint" / "SKILL.md").read_text(encoding="utf-8")

    assert "intentionally empty" in body, (
        "wiki-lint SKILL Step 2 must say stubs are 'intentionally empty' "
        "to distinguish them from forgotten orphans"
    )
    assert "/paper-wiki:wiki-ingest" in body, (
        "wiki-lint SKILL Step 2 must reference /paper-wiki:wiki-ingest "
        "as the action to fill auto-created stubs"
    )


# ---------------------------------------------------------------------------
# Task 9.17 — vault .lock (v0.3.18)
# ---------------------------------------------------------------------------


def test_vault_lock_module_exists() -> None:
    """src/paperwiki/_internal/locking.py must expose acquire_vault_lock and VaultLockError."""
    from paperwiki._internal.locking import VaultLockError, acquire_vault_lock

    assert callable(acquire_vault_lock)
    assert issubclass(VaultLockError, Exception)


# ---------------------------------------------------------------------------
# Task 9.18 — Today's Overview crash-safe step ordering (v0.3.18)
# ---------------------------------------------------------------------------


def test_digest_skill_overview_synthesis_comes_after_auto_chain_and_per_paper() -> None:
    """digest SKILL.md must order steps: auto-chain → per-paper synthesis → overview synthesis.

    The overview slot should be filled last so it can reference concepts and
    figures that the earlier steps produced.
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")

    auto_chain_pos = body.find("Auto-chain extract-images")
    per_paper_pos = body.find("Per-paper Detailed report synthesis")
    overview_pos = body.find("Synthesize Today's Overview")

    assert auto_chain_pos != -1, "digest SKILL must describe the auto-chain step"
    assert per_paper_pos != -1, "digest SKILL must describe per-paper synthesis"
    assert overview_pos != -1, "digest SKILL must describe Today's Overview synthesis"

    assert auto_chain_pos < per_paper_pos, (
        "In digest SKILL, auto-chain must appear BEFORE per-paper synthesis"
    )
    assert per_paper_pos < overview_pos, (
        "In digest SKILL, per-paper synthesis must appear BEFORE Today's Overview synthesis — "
        "the overview is written last so it can reference the fully-populated digest"
    )


def test_setup_skill_biomedical_keywords_exclude_generic_terms() -> None:
    """The Biomedical & Pathology topic must not include 'foundation model' in
    its keyword list — it matches every ML paper and inflates relevance scores."""
    body = (REPO_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")

    # Find the Biomedical & Pathology keywords block
    bio_start = body.find("Biomedical & Pathology:")
    assert bio_start != -1, "setup SKILL must define Biomedical & Pathology topic"

    # Extract up to the next topic block
    next_topic = body.find("\n\n", bio_start + len("Biomedical & Pathology:"))
    bio_block = body[bio_start:next_topic] if next_topic != -1 else body[bio_start:]

    # 'foundation model' must not be in the biomedical keyword list
    assert "foundation model" not in bio_block, (
        "Biomedical & Pathology keywords must not include 'foundation model' — "
        "it is a cross-domain term that inflates relevance for unrelated papers"
    )

    # WSI should appear only once (collapsed duplicates)
    wsi_count = bio_block.count("whole slide image") + bio_block.count("whole-slide image")
    assert wsi_count <= 1, (
        f"Biomedical & Pathology should have at most one WSI keyword variant, found {wsi_count}"
    )


# ---------------------------------------------------------------------------
# Task 9.22 — Inline figures in synthesized Detailed reports (v0.3.19)
# ---------------------------------------------------------------------------


def test_digest_skill_inlines_figures_in_detailed_report() -> None:
    """digest SKILL.md Process Step 8 must document the inline-figure embed
    contract: figures from Wiki/sources/<id>/images/ are embedded via
    ![[Wiki/sources/<id>/images/<file>|600]] inside the Detailed report block.
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    assert "![[Wiki/sources/" in flat, (
        "digest SKILL.md must reference the ![[Wiki/sources/ embed shape "
        "for inline figures inside the Detailed report"
    )
    assert "|600]]" in flat, (
        "digest SKILL.md must use |600 width for Detailed-report figure embeds "
        "(distinct from the card teaser's |700)"
    )


def test_digest_skill_picks_alphabetically_first_figures() -> None:
    """digest SKILL.md must describe the deterministic (alphabetical) sort
    heuristic for picking which figures to embed in the Detailed report.
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    assert "sort alphabetically" in flat or "deterministic listing" in flat, (
        "digest SKILL.md must say 'sort alphabetically' or 'deterministic listing' "
        "near the inline-figure step so the pick heuristic is pinned and drift-proof"
    )


# ---------------------------------------------------------------------------
# Task 9.24 — Detailed reports gated by auto_ingest_top (v0.3.19)
# ---------------------------------------------------------------------------


def test_digest_skill_gates_detailed_report_by_auto_ingest_top() -> None:
    """digest SKILL.md Process Step 8 must document that only the top
    auto_ingest_top papers get full Detailed report synthesis; papers below
    the threshold get the analyze-link teaser.
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    assert "auto_ingest_top" in flat, (
        "digest SKILL.md Process Step 8 must reference auto_ingest_top "
        "as the gating field for Detailed report synthesis"
    )
    assert "/paper-wiki:analyze" in flat, (
        "digest SKILL.md must include the /paper-wiki:analyze teaser shape "
        "for papers below the auto_ingest_top threshold"
    )
    assert "for a deep dive" in flat, (
        "digest SKILL.md must include 'for a deep dive' in the teaser wording "
        "so the exact teaser shape is pinned"
    )


def test_digest_skill_zero_auto_ingest_top_uses_teasers_for_all() -> None:
    """digest SKILL.md must describe the auto_ingest_top: 0 edge case —
    all papers get the teaser only, no synthesis at all.
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())

    assert "auto_ingest_top" in flat, "digest SKILL.md must reference auto_ingest_top"
    # The SKILL must describe the zero case explicitly
    assert "auto_ingest_top" in body, "digest SKILL.md must reference auto_ingest_top"
    # The SKILL must describe the zero case explicitly
    zero_described = (
        "auto_ingest_top: 0" in flat
        or "auto_ingest_top is 0" in flat
        or "auto_ingest_top == 0" in flat
        or "auto_ingest_top` is 0" in flat
        or "0` (no auto" in flat
    )
    assert zero_described, (
        "digest SKILL.md must describe the auto_ingest_top: 0 edge case "
        "(all papers get the teaser, no synthesis)"
    )


def test_digest_skill_forbids_synthesizing_below_auto_ingest_top() -> None:
    """digest SKILL.md Red Flags must contain a row warning against synthesizing
    Detailed reports for ALL papers when auto_ingest_top < top_k.
    The row must include both 'auto_ingest_top' and 'STOP'.
    """
    body = (REPO_ROOT / "skills" / "digest" / "SKILL.md").read_text(encoding="utf-8")

    assert "auto_ingest_top" in body, "digest SKILL.md must reference auto_ingest_top"
    assert "STOP" in body, "digest SKILL.md Red Flags must contain STOP as an explicit halt signal"

    # Find paragraphs/rows that contain both 'auto_ingest_top' and 'STOP'
    lines = body.splitlines()
    found = any("auto_ingest_top" in line and "STOP" in line for line in lines)
    # Or check via a window: a STOP line within 3 lines of an auto_ingest_top mention
    if not found:
        for i, line in enumerate(lines):
            if "auto_ingest_top" in line:
                window = lines[max(0, i - 3) : i + 4]
                if any("STOP" in w for w in window):
                    found = True
                    break
    assert found, (
        "digest SKILL.md Red Flags must have a row associating auto_ingest_top "
        "over-synthesis with STOP — warn the SKILL executor to halt and fix"
    )


# ---------------------------------------------------------------------------
# Task 9.25 — 3-priority image extraction (v0.3.20)
# ---------------------------------------------------------------------------


def test_arxiv_source_exports_priority_functions() -> None:
    """arxiv_source must export the three new extraction functions."""
    from paperwiki._internal.arxiv_source import (
        _has_tikz,
        extract_root_pdfs_from_tarball,
        extract_tikz_crop_from_pdf,
    )

    assert callable(extract_root_pdfs_from_tarball)
    assert callable(extract_tikz_crop_from_pdf)
    assert callable(_has_tikz)


def test_extract_result_has_sources_field() -> None:
    """ExtractResult must carry a 'sources' dict with all three priority keys."""
    from paperwiki.runners.extract_paper_images import ExtractResult

    r = ExtractResult(
        canonical_id="arxiv:0001.0001",
        image_count=3,
        images=[],
        cached=False,
        sources={"arxiv-source": 2, "pdf-figure": 1, "tikz-cropped": 0},
    )
    assert r.sources == {"arxiv-source": 2, "pdf-figure": 1, "tikz-cropped": 0}


def test_pymupdf_dependency_declared() -> None:
    """pyproject.toml must declare pymupdf>=1.24 (AGPL, GPL-3.0 compatible)."""
    pyproject = REPO_ROOT / "pyproject.toml"
    body = pyproject.read_text(encoding="utf-8")
    assert "pymupdf" in body.lower(), (
        "pyproject.toml must declare pymupdf>=1.24 as a runtime dependency "
        "(added in Task 9.25 for Priority-2 and Priority-3 image extraction)"
    )


# ---------------------------------------------------------------------------
# Task 9.26 — paperwiki CLI (v0.3.20)
# ---------------------------------------------------------------------------


def test_paperwiki_cli_help_lists_subcommands() -> None:
    """``paperwiki --help`` must list update, status, and uninstall subcommands."""
    from typer.testing import CliRunner

    from paperwiki.cli import app

    result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(app, ["--help"])
    output = result.output
    assert "update" in output, "paperwiki --help must list 'update' subcommand"
    assert "status" in output, "paperwiki --help must list 'status' subcommand"
    assert "uninstall" in output, "paperwiki --help must list 'uninstall' subcommand"


def test_paperwiki_cli_module_importable() -> None:
    """paperwiki.cli must import cleanly and expose app + main."""
    from paperwiki.cli import app, main

    assert callable(main)
    assert app is not None


def test_pyproject_declares_paperwiki_console_script() -> None:
    """pyproject.toml must declare paperwiki = paperwiki.cli:main console-script."""
    pyproject = REPO_ROOT / "pyproject.toml"
    body = pyproject.read_text(encoding="utf-8")
    assert "paperwiki" in body, "pyproject.toml must declare paperwiki console-script"
    assert "paperwiki.cli:main" in body, (
        "pyproject.toml [project.scripts] must map paperwiki → paperwiki.cli:main"
    )


# ---------------------------------------------------------------------------
# Task 9.27 — auto-install ~/.local/bin/paperwiki shim (v0.3.21)
# ---------------------------------------------------------------------------


def test_ensure_env_contains_shim_tag() -> None:
    """Static pin: hooks/ensure-env.sh must contain the shim tag line.

    This check ensures that future edits cannot silently remove the shim
    emission block from ensure-env.sh without a test failure.
    """
    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    body = script.read_text(encoding="utf-8")
    expected_tag = "# paperwiki shim — v0.3.29 (shared venv + self-bootstrap)."
    assert expected_tag in body, (
        "hooks/ensure-env.sh must contain the v0.3.29 shim tag line so "
        "old shims get overwritten on first SessionStart after upgrade"
    )


def test_ensure_env_shim_block_is_idempotent_guard() -> None:
    """ensure-env.sh must use a grep-based guard to skip rewriting an existing shim."""
    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    body = script.read_text(encoding="utf-8")
    assert "grep -qF" in body, (
        "hooks/ensure-env.sh must use 'grep -qF' to check for the tag before "
        "rewriting the shim (idempotency guard)"
    )
    assert "EXPECTED_TAG" in body, (
        "hooks/ensure-env.sh must define EXPECTED_TAG for the idempotency check"
    )


def test_ensure_env_shim_contains_self_bootstrap_branch() -> None:
    """Task 9.32 / D-9.32.1: shim must self-bootstrap when shared venv is missing.

    The heredoc in hooks/ensure-env.sh writes a shim that detects a
    missing ``$VENV_DIR/bin/python`` and inline-invokes
    ``ensure-env.sh`` before exec, so users hitting the
    ``/reload-plugins`` UX trap (no SessionStart fires) still get a
    working ``paperwiki`` from a fresh terminal.
    """
    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    body = script.read_text(encoding="utf-8")
    assert "shared venv missing at $VENV_DIR; bootstrapping..." in body, (
        "shim heredoc must announce missing-venv bootstrap to stderr"
    )
    assert 'bash "$CACHE_ROOT/$LATEST/hooks/ensure-env.sh"' in body, (
        "shim heredoc must invoke the latest cached ensure-env.sh when the shared venv is missing"
    )


def test_ensure_env_shim_respects_paperwiki_home_precedence() -> None:
    """Task 9.32: shim heredoc must honor the full env-var precedence chain.

    Order: PAPERWIKI_VENV_DIR > PAPERWIKI_HOME > PAPERWIKI_CONFIG_DIR > default.
    """
    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    body = script.read_text(encoding="utf-8")
    # The heredoc inlines the same precedence chain as the parent hook,
    # so users can override either var.
    assert (
        'PAPERWIKI_HOME_RESOLVED="${PAPERWIKI_HOME:-${PAPERWIKI_CONFIG_DIR:-$HOME/.config/paper-wiki}}"'
        in body
    ), "shim heredoc must resolve PAPERWIKI_HOME with legacy fallback"
    assert 'VENV_DIR="${PAPERWIKI_VENV_DIR:-$PAPERWIKI_HOME_RESOLVED/venv}"' in body, (
        "shim heredoc must let PAPERWIKI_VENV_DIR override the venv path"
    )


def test_ensure_env_shim_warns_if_local_bin_not_on_path() -> None:
    """ensure-env.sh must emit a one-time PATH warning when ~/.local/bin is missing."""
    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    body = script.read_text(encoding="utf-8")
    assert ".paperwiki-path-warned" in body, (
        "hooks/ensure-env.sh must create a .paperwiki-path-warned marker so the "
        "PATH warning is emitted only once"
    )
    assert "not on your PATH" in body, (
        "hooks/ensure-env.sh must print a message when ~/.local/bin is not on PATH"
    )


def _setup_v0329_idempotent_state(tmp_path: Path, version: str = "0.0.1") -> Path:
    """Set up a fake plugin root + pre-bootstrapped shared venv that will
    short-circuit ensure-env.sh's idempotent-skip branch (Task 9.31).

    Returns the plugin_root path. Caller must set CLAUDE_PLUGIN_ROOT and
    HOME accordingly.
    """
    plugin_root = tmp_path / "plugin"
    init_py = plugin_root / "src" / "paperwiki" / "__init__.py"
    init_py.parent.mkdir(parents=True)
    init_py.write_text(f'__version__ = "{version}"\n', encoding="utf-8")

    # Pre-bootstrapped shared venv at the default location (under
    # PAPERWIKI_HOME = $HOME/.config/paper-wiki). Stamp matches version
    # + symlink at $PLUGIN_ROOT/.venv -> shared.
    shared_venv = tmp_path / ".config" / "paper-wiki" / "venv"
    (shared_venv / "bin").mkdir(parents=True)
    (shared_venv / ".installed").write_text(version, encoding="utf-8")
    (plugin_root / ".venv").symlink_to(shared_venv)

    return plugin_root


def test_ensure_env_shim_integration(tmp_path: Path) -> None:
    """Integration: running ensure-env.sh in a temp HOME creates the shim.

    Pre-creates a v0.3.29 shared-venv state (matching stamp + symlink in
    place) so the bootstrap exits early; only the shim emission block
    runs and is asserted.
    """
    import stat
    import subprocess

    plugin_root = _setup_v0329_idempotent_state(tmp_path)

    # Also create a fake versioned paperwiki binary so the shim has something to exec.
    fake_cache = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "paper-wiki"
        / "paper-wiki"
        / "0.0.1"
        / ".venv"
        / "bin"
    )
    fake_cache.mkdir(parents=True)
    fake_bin = fake_cache / "paperwiki"
    fake_bin.write_text("#!/usr/bin/env bash\necho 'fake paperwiki 0.0.1'\n")
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    # Remove ~/.local/bin from PATH so the warning branch triggers cleanly.
    env["PATH"] = ":".join(p for p in env.get("PATH", "").split(":") if ".local/bin" not in p)

    script = REPO_ROOT / "hooks" / "ensure-env.sh"
    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ensure-env.sh failed:\n{result.stderr}"

    shim = tmp_path / ".local" / "bin" / "paperwiki"
    assert shim.is_file(), "ensure-env.sh must create ~/.local/bin/paperwiki"
    assert os.access(shim, os.X_OK), "shim must be executable"

    body = shim.read_text(encoding="utf-8")
    assert "paperwiki shim — v0.3.29 (shared venv + self-bootstrap)." in body, (
        "shim must contain the v0.3.29 expected tag line"
    )


def test_ensure_env_shim_is_idempotent(tmp_path: Path) -> None:
    """Running ensure-env.sh twice must not change the shim (idempotent)."""
    import subprocess

    plugin_root = _setup_v0329_idempotent_state(tmp_path)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    script = REPO_ROOT / "hooks" / "ensure-env.sh"

    def run() -> None:
        result = subprocess.run(
            ["bash", str(script)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"ensure-env.sh failed:\n{result.stderr}"

    run()
    shim = tmp_path / ".local" / "bin" / "paperwiki"
    assert shim.is_file()
    mtime_first = shim.stat().st_mtime
    content_first = shim.read_text(encoding="utf-8")

    run()
    mtime_second = shim.stat().st_mtime
    content_second = shim.read_text(encoding="utf-8")

    assert content_first == content_second, "shim content must not change on second run"
    # mtime only stays the same if the file was not rewritten; allow for
    # filesystem resolution but content equality is the stronger invariant.
    assert mtime_first == mtime_second, "shim must not be rewritten on second run (mtime changed)"
