"""``paperwiki.runners.diagnostics`` — environment health report.

Invoked by the ``paperwiki:setup`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.diagnostics

Emits a JSON document on stdout describing the plugin's environment
state: paper-wiki version, Python version, plugin-root from
``CLAUDE_PLUGIN_ROOT``, venv layout, expected user-config path, and a
``bundled_recipes`` list. Any detected problems land in ``issues`` so
the SKILL can surface them in plain English without parsing log lines.

The runner does not modify state; it only inspects.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from pydantic import BaseModel, Field

from paperwiki import __version__

_RECIPES_DIR = Path(__file__).resolve().parents[3] / "recipes"


app = typer.Typer(
    add_completion=False,
    help="Print a JSON environment-health report for paper-wiki.",
    invoke_without_command=True,
)


class DiagnosticsReport(BaseModel):
    """Machine-readable environment report consumed by the setup SKILL."""

    paperwiki_version: str
    python_version: str
    plugin_root: str
    venv_path: str
    venv_installed_stamp: bool
    config_path: str
    config_exists: bool
    bundled_recipes: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


# ``claude mcp list`` prints lines shaped like::
#
#     <server-name>: <command-or-url> - ✓ Connected
#     <server-name>: <command-or-url> - ✗ Failed: ...
#
# Server names may themselves contain ``:`` (e.g. ``plugin:foo:bar``), so
# we anchor on the first ``: `` (colon + space) — the field separator.
_MCP_LIST_LINE = re.compile(r"^(?P<name>\S(?:.*?\S)?): \S")


def build_report() -> DiagnosticsReport:
    """Inspect the environment and return a :class:`DiagnosticsReport`."""
    issues: list[str] = []

    plugin_root_str = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root_str:
        issues.append(
            "CLAUDE_PLUGIN_ROOT is unset — set by Claude Code at runtime; "
            "if running outside a Claude Code session this is expected."
        )
        venv_path = Path()
        stamp_present = False
    else:
        plugin_root = Path(plugin_root_str)
        venv_path = plugin_root / ".venv"
        stamp_path = venv_path / ".installed"
        stamp_present = stamp_path.is_file()
        if not stamp_present:
            issues.append("venv .installed stamp missing — run hooks/ensure-env.sh")

    config_path = _resolve_config_path()
    config_exists = config_path.is_file()
    if not config_exists:
        issues.append(f"config not found at {config_path}; run /paperwiki:setup to create one.")

    bundled_recipes = (
        sorted(p.name for p in _RECIPES_DIR.glob("*.yaml")) if _RECIPES_DIR.is_dir() else []
    )

    mcp_servers = _detect_mcp_servers(issues)

    return DiagnosticsReport(
        paperwiki_version=__version__,
        python_version=(
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        plugin_root=plugin_root_str,
        venv_path=str(venv_path) if plugin_root_str else "",
        venv_installed_stamp=stamp_present,
        config_path=str(config_path),
        config_exists=config_exists,
        bundled_recipes=bundled_recipes,
        mcp_servers=mcp_servers,
        issues=issues,
    )


def _detect_mcp_servers(issues: list[str]) -> list[str]:
    """Run ``claude mcp list`` and return the registered server names.

    Failures (CLI missing, non-zero exit) are folded into ``issues`` so
    the SKILL can offer guidance, but never raise — the diagnostics
    runner stays usable even when the surrounding tooling drifts.
    """
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        issues.append(
            "claude CLI not found on PATH; MCP server detection skipped. "
            "Install Claude Code or run inside a Claude Code session."
        )
        return []

    try:
        # argv is fully controlled (resolved by shutil.which + literals);
        # shell=False; user input never reaches the call. S603's "untrusted
        # input" warning does not apply here.
        completed = subprocess.run(  # noqa: S603
            [claude_bin, "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    except FileNotFoundError:
        # `which` resolved a path that subsequently disappeared (e.g.,
        # the CLI was uninstalled mid-session). Treat the same as
        # "not on PATH" — we never want diagnostics to crash.
        issues.append(
            "claude CLI not found on PATH; MCP server detection skipped. "
            "Install Claude Code or run inside a Claude Code session."
        )
        return []
    except (OSError, subprocess.SubprocessError) as exc:
        issues.append(f"claude mcp list failed to launch: {exc}")
        return []

    if completed.returncode != 0:
        issues.append(
            f"claude mcp list exited with code {completed.returncode}; "
            "MCP server list may be incomplete."
        )
        return []

    servers: list[str] = []
    for raw in completed.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("Checking") or line.startswith("No MCP"):
            continue
        match = _MCP_LIST_LINE.match(line)
        if match is not None:
            servers.append(match.group("name"))
    return servers


def _resolve_config_path() -> Path:
    """Return the path to the user's paper-wiki config.toml.

    Honors ``XDG_CONFIG_HOME`` if set; otherwise falls back to
    ``~/.config/paperwiki/config.toml``.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "paperwiki" / "config.toml"
    return Path.home() / ".config" / "paperwiki" / "config.toml"


@app.callback()
def main() -> None:
    """Emit the diagnostics report as JSON on stdout."""
    report = build_report()
    typer.echo(json.dumps(report.model_dump(), indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["DiagnosticsReport", "app", "build_report"]
