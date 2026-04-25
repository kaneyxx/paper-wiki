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
    assert data["version"] == "0.3.0"
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
    """After writing the source, analyze must call /paperwiki:wiki-ingest."""
    body = (REPO_ROOT / "skills" / "analyze" / "SKILL.md").read_text(encoding="utf-8")
    assert "/paperwiki:wiki-ingest" in body, (
        "analyze SKILL must hand off to /paperwiki:wiki-ingest after writing"
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
    assert "docs/paperclip-setup.md" in body or "/paperwiki:setup" in body, (
        "bio-search SKILL must point users at setup docs when MCP is missing"
    )


def test_bio_search_slash_command_exists() -> None:
    """`.claude/commands/bio-search.md` registers the slash command."""
    cmd = REPO_ROOT / ".claude" / "commands" / "bio-search.md"
    assert cmd.is_file(), ".claude/commands/bio-search.md must exist"


def test_readme_documents_bio_search_as_optional() -> None:
    """README must surface bio-search in Quick Start as an optional advanced feature."""
    body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "/paperwiki:bio-search" in body, "README must list /paperwiki:bio-search in Quick Start"
    # Position it as optional / opt-in rather than a default surface.
    assert "paperclip" in body, "README must mention paperclip dependency"
    assert "optional" in body.lower(), (
        "README must position bio-search as optional, not a default surface"
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
