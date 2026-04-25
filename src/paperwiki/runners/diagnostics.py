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
    issues: list[str] = Field(default_factory=list)


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
        issues=issues,
    )


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
