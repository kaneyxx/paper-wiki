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
    assert data["version"] == "0.1.0"
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
